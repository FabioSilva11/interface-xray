#!/usr/bin/env python3
"""Inspeção, anotação e comparação local de rasters, sem alterar entradas."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import warnings

try:
    import PIL
    from PIL import Image, ImageChops, ImageDraw, ImageStat
except ImportError:
    PIL = None


class ImageToolError(ValueError):
    """Entrada ou operação inválida, com mensagem adequada à CLI."""


def _path(value) -> Path:
    # absolute() retains a final symlink so even dangling outputs are rejected.
    return Path(os.path.abspath(os.fspath(value)))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def _open_image(path: Path):
    if PIL is None:
        raise ImageToolError("Dependência ausente: instale Pillow>=10 com Python>=3.10.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as raster:
                raster.seek(0)
                raster.load()
                yield raster
    except ImageToolError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageToolError(f"Não foi possível ler ou processar a imagem '{path}': {exc}") from exc


def _metadata(path: Path, image) -> dict:
    profile = image.info.get("icc_profile")
    return {
        "image": str(path),
        "sha256": _sha256(path),
        "size": [image.width, image.height],
        "mode": image.mode,
        "format": image.format,
        "bands": list(image.getbands()),
        "frame_count": getattr(image, "n_frames", 1),
        "frame_index": 0,
        "exif_orientation": image.getexif().get(274),
        "orientation_applied": False,
        "has_transparency": "A" in image.getbands() or "transparency" in image.info,
        "icc_profile_present": bool(profile),
        "icc_profile_sha256": hashlib.sha256(profile).hexdigest() if profile else None,
    }


def inspect_image(image_path, points=()) -> dict:
    """Retorne metadados e amostras nativas; coordenadas inteiras, origem (0, 0)."""
    path = _path(image_path)
    with _open_image(path) as image:
        samples = []
        for point in points:
            if not isinstance(point, (tuple, list)) or len(point) != 2:
                raise ImageToolError("Cada ponto deve conter duas coordenadas inteiras: X,Y.")
            x, y = point
            if type(x) is not int or type(y) is not int:
                raise ImageToolError("As coordenadas de amostragem devem ser números inteiros.")
            if not (0 <= x < image.width and 0 <= y < image.height):
                raise ImageToolError(f"Ponto ({x},{y}) fora da imagem de {image.width}×{image.height} px_imagem.")
            pixel = image.getpixel((x, y))
            samples.append({"x": x, "y": y, "pixel": list(pixel) if isinstance(pixel, tuple) else pixel})
        result = _metadata(path, image)
        result.update({"units": "px_imagem", "points": samples})
        return result


def _ensure_new_path(path: Path):
    if os.path.lexists(path):
        raise ImageToolError(f"A saída já existe e não será sobrescrita: '{path}'. Escolha um nome novo.")
    if not path.parent.is_dir():
        raise ImageToolError(f"A pasta de destino não existe: '{path.parent}'.")


def _load_boxes(boxes_path: Path, size: tuple[int, int]) -> list[dict]:
    try:
        document = json.loads(boxes_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImageToolError(f"Não foi possível ler o JSON de caixas '{boxes_path}': {exc}") from exc
    if not isinstance(document, dict) or document.get("units") != "px_imagem":
        raise ImageToolError('O JSON deve ser um objeto com "units": "px_imagem" e uma lista "boxes".')
    boxes = document.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        raise ImageToolError('O campo "boxes" deve ser uma lista não vazia.')
    seen = set()
    required = {"id", "x", "y", "width", "height"}
    for index, box in enumerate(boxes):
        if not isinstance(box, dict) or not required.issubset(box):
            raise ImageToolError(f"Caixa {index}: informe id, x, y, width e height.")
        identifier = box["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", identifier):
            raise ImageToolError(f"Caixa {index}: ID inválido; use letra ASCII inicial e até 64 letras, números, _, - ou .")
        if identifier in seen:
            raise ImageToolError(f"ID de caixa repetido: '{identifier}'.")
        seen.add(identifier)
        if any(type(box[key]) is not int for key in ("x", "y", "width", "height")):
            raise ImageToolError(f"Caixa '{identifier}': coordenadas e dimensões devem ser inteiros em px_imagem.")
        x, y, width, height = (box[key] for key in ("x", "y", "width", "height"))
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ImageToolError(f"Caixa '{identifier}': x/y não negativos e width/height positivos são obrigatórios.")
        if x + width > size[0] or y + height > size[1]:
            raise ImageToolError(f"Caixa '{identifier}' ultrapassa a imagem de {size[0]}×{size[1]} px_imagem.")
    return boxes


def _write_png_new(image, output_path: Path):
    # Encode before creating the file, and use exclusive creation to avoid races.
    _ensure_new_path(output_path)
    payload = BytesIO()
    image.save(payload, format="PNG")
    with output_path.open("xb") as output:
        output.write(payload.getvalue())


def annotate_image(image_path, boxes_path, output_path) -> dict:
    """Crie PNG RGBA separado, com caixas e IDs do JSON em px_imagem."""
    source, boxes_file, output = map(_path, (image_path, boxes_path, output_path))
    _ensure_new_path(output)
    if output.suffix.lower() != ".png":
        raise ImageToolError("A anotação deve ter extensão .png para preservar o raster sem perdas.")
    try:
        with _open_image(source) as image:
            boxes = _load_boxes(boxes_file, image.size)
            result = image.convert("RGBA")
            # An output is a diagnostic raster; do not retain orientation/profile
            # tags that could make viewers transform these native coordinates.
            result.info.clear()
            draw = ImageDraw.Draw(result)
            for box in boxes:
                x, y, width, height = (box[key] for key in ("x", "y", "width", "height"))
                draw.rectangle((x, y, x + width - 1, y + height - 1), outline=(255, 0, 0, 255), width=1)
                label = box["id"]
                left, top, right, bottom = draw.textbbox((0, 0), label)
                label_width, label_height = right - left + 4, bottom - top + 4
                label_x = max(0, min(x, image.width - label_width))
                label_y = max(0, y - label_height)
                draw.rectangle((label_x, label_y, label_x + label_width - 1, label_y + label_height - 1), fill=(255, 0, 0, 255))
                draw.text((label_x + 2 - left, label_y + 2 - top), label, fill=(255, 255, 255, 255))
            _write_png_new(result, output)
            return {"image": str(source), "image_sha256": _sha256(source), "boxes": str(boxes_file),
                    "output": str(output), "size": [image.width, image.height], "units": "px_imagem",
                    "box_count": len(boxes), "orientation_applied": False}
    except ImageToolError:
        raise
    except (OSError, ValueError) as exc:
        raise ImageToolError(f"Não foi possível gravar a anotação '{output}': {exc}") from exc


def _rgb_on_white(image):
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    result = Image.alpha_composite(white, rgba).convert("RGB")
    result.info.clear()
    return result


def compare_images(reference_path, actual_path, output_dir, *, threshold: int) -> dict:
    """Compare rasters de mesmo tamanho, com MAE RGB e limiar por canal."""
    if type(threshold) is not int or not 0 <= threshold <= 255:
        raise ImageToolError("O limiar --threshold deve ser um inteiro de 0 a 255.")
    reference_file, actual_file, directory = map(_path, (reference_path, actual_path, output_dir))
    _ensure_new_path(directory)
    try:
        with _open_image(reference_file) as reference, _open_image(actual_file) as actual:
            if reference.size != actual.size:
                raise ImageToolError(f"Dimensões diferentes: referência {reference.width}×{reference.height}; atual {actual.width}×{actual.height}. Não há redimensionamento nem realinhamento automático.")
            reference_meta, actual_meta = _metadata(reference_file, reference), _metadata(actual_file, actual)
            reference_rgb, actual_rgb = _rgb_on_white(reference), _rgb_on_white(actual)
            difference = ImageChops.difference(reference_rgb, actual_rgb)
            channels = difference.split()
            maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
            different_pixels = sum(maximum.histogram()[threshold + 1:])
            total_pixels = reference.width * reference.height
            mae_per_channel = ImageStat.Stat(difference).mean
            metrics = {
                "reference": reference_meta,
                "actual": actual_meta,
                "size": [reference.width, reference.height],
                "units": "px_imagem",
                "threshold": threshold,
                "mae_rgb": sum(mae_per_channel) / 3,
                "mae_per_channel": dict(zip(("R", "G", "B"), mae_per_channel)),
                "different_pixels": different_pixels,
                "total_pixels": total_pixels,
                "different_fraction": different_pixels / total_pixels,
                "conditions": {
                    "difference_rule": "max(abs(R_ref-R_actual), abs(G_ref-G_actual), abs(B_ref-B_actual)) > threshold",
                    "mae_rule": "sum(abs(channel_ref-channel_actual)) / (width * height * 3); independent of threshold",
                    "alpha_background_rgb": [255, 255, 255],
                    "alpha_compositing": "Pillow Image.alpha_composite, 8-bit RGBA, then RGB",
                    "color_management": "Pillow mode conversion only; ICC profiles are not applied; 8-bit RGB code values, not linear light",
                    "orientation_applied": False,
                    "resize_applied": False,
                    "alignment_applied": False,
                    "frame_index": 0,
                    "overlay_reference_weight": 0.5,
                    "difference_image": "absolute RGB difference, no amplification and no threshold masking",
                    "pillow_version": PIL.__version__,
                },
                "outputs": {"overlay": str(directory / "overlay.png"), "difference": str(directory / "difference.png"), "metrics": str(directory / "metrics.json")},
            }
            # mkdir is exclusive; never adopt an existing directory or replace it.
            directory.mkdir()
            _write_png_new(Image.blend(reference_rgb, actual_rgb, 0.5), directory / "overlay.png")
            _write_png_new(difference, directory / "difference.png")
            with (directory / "metrics.json").open("x", encoding="utf-8", newline="\n") as output:
                json.dump(metrics, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
            return metrics
    except ImageToolError:
        raise
    except (OSError, ValueError) as exc:
        raise ImageToolError(f"Não foi possível gerar a comparação em '{directory}': {exc}") from exc


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ImageToolError(f"Argumentos inválidos: {message}. Use --help para consultar os comandos.")


def _point(text: str) -> tuple[int, int]:
    if not re.fullmatch(r"-?\d+,-?\d+", text):
        raise argparse.ArgumentTypeError("o ponto deve usar X,Y com dois inteiros, sem espaços")
    x, y = text.split(",")
    return int(x), int(y)


def main(argv=None) -> int:
    """CLI: JSON UTF-8 no sucesso; erro JSON em stderr e código 2."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    inspect_parser = commands.add_parser("inspect", help="Leia metadados e pixels nativos.")
    inspect_parser.add_argument("image")
    inspect_parser.add_argument("--point", type=_point, action="append", default=[], metavar="X,Y")
    annotate_parser = commands.add_parser("annotate", help="Anote uma cópia PNG com caixas em px_imagem.")
    annotate_parser.add_argument("--image", required=True)
    annotate_parser.add_argument("--boxes", required=True, help="Caminho do arquivo JSON de caixas.")
    annotate_parser.add_argument("--output", required=True, help="Novo arquivo .png.")
    compare_parser = commands.add_parser("compare", help="Compare imagens com as mesmas dimensões.")
    compare_parser.add_argument("--reference", required=True)
    compare_parser.add_argument("--actual", required=True)
    compare_parser.add_argument("--output-dir", required=True, help="Diretório novo, com pasta pai existente.")
    compare_parser.add_argument("--threshold", required=True, type=int, help="Inteiro de 0 a 255; um canal acima do limiar marca o pixel.")
    try:
        arguments = parser.parse_args(argv)
        if arguments.command == "inspect":
            result = inspect_image(arguments.image, arguments.point)
        elif arguments.command == "annotate":
            result = annotate_image(arguments.image, arguments.boxes, arguments.output)
        else:
            result = compare_images(arguments.reference, arguments.actual, arguments.output_dir, threshold=arguments.threshold)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ImageToolError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
