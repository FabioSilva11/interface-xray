#!/usr/bin/env python3
"""Análise matemática de contornos e bordas de um componente de interface.

Comandos:
  analyze  – a partir de uma captura e de um bbox, grava em uma pasta nova a especificação
             JSON, o SVG com caminhos editáveis, diagnósticos e métricas.
  revise   – aplica correções (cores, deslocamentos de faixas, brilho ou vértices) a uma
             especificação anterior e grava uma nova revisão, sem refazer a detecção.

Requer Pillow (image_tools.py) e NumPy (requirements-contour.txt). Não altera entradas
nem sobrescreve saídas existentes. Os resultados são estimativas com método e métricas
declarados; a aprovação visual continua sendo decisão do usuário.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
from io import BytesIO
from xml.sax.saxutils import escape

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import image_tools  # noqa: E402  (Pillow, leitura segura de imagens e validação de caixas)

try:
    import numpy as np
    import contour_geometry as geo
    import contour_diagnostics as diagnostic
except ImportError:  # NumPy ausente: o módulo continua importável; os comandos informam o requisito.
    np = None
    geo = None


class ContourToolError(ValueError):
    """Entrada, dependência ou operação inválida, com mensagem adequada à CLI."""


SCHEMA = "interface-xray.contour-element/1"
TOLERANCE_PX = 0.6            # erro máximo aceito entre primitivo e evidência
PEAK_THRESHOLD = 18.0         # variação de cor por 0,5 px que caracteriza uma transição
MIN_BAND_OFFSET = 1.25        # transições mais próximas são a própria borda da região
MAX_BAND_OFFSET = 14.0
MAX_BANDS = 4
MATCH_PX = 1.5                # distância de correspondência para precisão e cobertura
MIN_SIDE = 8
MAX_SIDE = 2000
MIN_REGION_FRACTION = 0.25    # a região de cor precisa cobrir ao menos esta fração do bbox
DIAGNOSTIC_SCALE = 4
EVIDENCE_LIMIT = 1200         # evita viés de Chamfer por lacunas artificiais entre amostras
REVISION_KEYS = {"colors", "offsets_px", "glow", "base_vertices", "base_path"}


def _require_numpy():
    if geo is None:
        raise ContourToolError(
            "Dependência ausente: instale NumPy com `python -m pip install -r requirements-contour.txt`, "
            "a partir da pasta da skill."
        )


def _path(value) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _sha256(path: Path) -> str:
    return image_tools._sha256(path)


def _rounded(value, digits=3):
    return round(float(value), digits)


def _points_list(points):
    return [[_rounded(x), _rounded(y)] for x, y in np.asarray(points, dtype=np.float64)]


def _load_rgb(path: Path):
    """RGB 8 bits; transparências são compostas sobre branco, como em image_tools.compare."""
    try:
        with image_tools._open_image(path) as raster:
            rgba = raster.convert("RGBA")
            white = image_tools.Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            rgb = image_tools.Image.alpha_composite(white, rgba).convert("RGB")
            return np.asarray(rgb, dtype=np.float64), rgb.size
    except image_tools.ImageToolError as exc:
        raise ContourToolError(str(exc)) from exc


def _encode_png(array):
    payload = BytesIO()
    image_tools.Image.fromarray(np.clip(np.rint(array), 0, 255).astype(np.uint8)).save(payload, format="PNG")
    return payload.getvalue()


def _write_bytes_new(data: bytes, path: Path):
    if os.path.lexists(path):
        raise ContourToolError(f"A saída já existe e não será sobrescrita: '{path}'.")
    with path.open("xb") as output:
        output.write(data)


def _write_text_new(text: str, path: Path):
    _write_bytes_new(text.encode("utf-8"), path)


def _write_json_new(document, path: Path):
    _write_text_new(json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n", path)


def _create_output_dir(path: Path) -> Path:
    if os.path.lexists(path):
        raise ContourToolError(f"A pasta de saída já existe e não será reutilizada: '{path}'. Use um nome novo por revisão.")
    if not path.parent.is_dir():
        raise ContourToolError(f"A pasta pai da saída não existe: '{path.parent}'.")
    os.mkdir(path)
    os.mkdir(path / "diagnostics")
    return path


def _nearest_flags(mask, points):
    columns = np.clip(np.floor(points[:, 0]).astype(int), 0, mask.shape[1] - 1)
    rows = np.clip(np.floor(points[:, 1]).astype(int), 0, mask.shape[0] - 1)
    return mask[rows, columns]


def _nearest_index(source, targets):
    """Índice do ponto de `source` mais próximo de cada ponto de `targets`."""
    difference = targets[:, None, :] - source[None, :, :]
    return np.argmin(np.sum(difference * difference, axis=2), axis=1)


def _dilate(mask):
    result = mask.copy()
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        result |= geo._shift(mask, dr, dc)
    return result


def _markup_mask(rgb):
    """Pixels de cores puras de marcações diagnósticas (heurística; a contagem é reportada)."""
    mask = np.zeros(rgb.shape[:2], dtype=bool)
    for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), (255, 0, 255)):
        mask |= np.max(np.abs(rgb - np.asarray(color, dtype=np.float64)), axis=2) <= 16
    return mask


def _exclusion_mask(shape, boxes, origin):
    mask = np.zeros(shape, dtype=bool)
    for box in boxes:
        left = box["x"] - origin[0]
        top = box["y"] - origin[1]
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(shape[1], left + box['width']), min(shape[0], top + box['height'])
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _validate_bbox(bbox, width, height):
    if len(bbox) != 4 or any(type(v) is not int for v in bbox):
        raise ContourToolError('bbox exige quatro inteiros em px_imagem.')
    x, y, box_width, box_height = bbox
    if x < 0 or y < 0 or box_width < MIN_SIDE or box_height < MIN_SIDE:
        raise ContourToolError(f"bbox inválido: use x,y não negativos e largura/altura de pelo menos {MIN_SIDE} px_imagem.")
    if x + box_width > width or y + box_height > height:
        raise ContourToolError(f"bbox ultrapassa a imagem de {width}×{height} px_imagem.")
    return x, y, box_width, box_height


# --------------------------------------------------------------------------- região e contorno

def _region_mask(crop, seed, tolerance, excluded, markup, box_area):
    """Região de cor, ampliando a tolerância para gradientes; falha se vazar ou for pequena."""
    last_error = "tolerância insuficiente"
    for factor in (1, 2, 3):
        try:
            mask = geo.color_region(crop, seed, tolerance * factor, allowed=~excluded, passable=markup)
        except geo.GeometryError as exc:
            last_error = str(exc)
            continue
        touches = bool(mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any())
        if touches or mask.mean() > 0.9:
            raise geo.GeometryError("a região de cor vaza para a borda do recorte")
        if mask.sum() >= MIN_REGION_FRACTION * box_area:
            return mask, tolerance * factor
        last_error = "região de cor pequena demais em relação ao componente"
    raise geo.GeometryError(last_error)


def _ray_contour(edges, unknown, seed, shape):
    """Contorno em estrela por raios a partir da semente, para regiões que vazam ou são transparentes."""
    height, width = shape
    center_x, center_y = seed[0] + 0.5, seed[1] + 0.5
    angles = np.linspace(0.0, 2 * math.pi, 180, endpoint=False)
    steps = np.arange(3.0, math.hypot(height, width), 0.5)
    radii = np.full(angles.shape, np.nan)
    for index, angle in enumerate(angles):
        xs = center_x + steps * math.cos(angle)
        ys = center_y + steps * math.sin(angle)
        inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
        if not inside.any():
            continue
        rows = np.floor(ys[inside]).astype(int)
        columns = np.floor(xs[inside]).astype(int)
        hit = edges[rows, columns] & ~unknown[rows, columns]
        if hit.any():
            radii[index] = steps[inside][int(np.argmax(hit))]
    found = ~np.isnan(radii)
    fraction = float(found.mean())
    if fraction < 0.5:
        raise geo.GeometryError("menos da metade dos raios encontrou borda; o contorno não foi determinado")
    indices = np.arange(len(angles))
    filled = np.interp(indices, indices[found], radii[found], period=len(angles))
    smoothed = np.median(np.stack([np.roll(filled, shift) for shift in range(-2, 3)]), axis=0)
    points = np.column_stack([center_x + smoothed * np.cos(angles), center_y + smoothed * np.sin(angles)])
    return points, fraction


def _orient_inward(points, shape):
    """Normais para dentro do polígono, verificadas pela distância assinada."""
    normals = geo.closed_normals(points, None)
    inside = _sample_nearest(geo.signed_distance(points, shape), points + 1.5 * normals) < 0
    return -normals if np.mean(inside) < 0.5 else normals


def _sample_nearest(array, points):
    columns = np.clip(np.floor(points[:, 0]).astype(int), 0, array.shape[1] - 1)
    rows = np.clip(np.floor(points[:, 1]).astype(int), 0, array.shape[0] - 1)
    return array[rows, columns]


def _known_sample_footprint(unknown,xs,ys):
    """Todos os quatro pixels da interpolação bilinear precisam ser confiáveis."""
    rows=np.clip(np.floor(ys-0.5).astype(int),0,unknown.shape[0]-1)
    cols=np.clip(np.floor(xs-0.5).astype(int),0,unknown.shape[1]-1)
    other_rows=np.minimum(rows+1,unknown.shape[0]-1)
    other_cols=np.minimum(cols+1,unknown.shape[1]-1)
    return ~(unknown[rows,cols]|unknown[other_rows,cols]|unknown[rows,other_cols]|unknown[other_rows,other_cols])


def _detect_bands(rgb, points, outward, observed, unknown=None):
    """Transições de cor ao longo das normais externas: bordas com deslocamento medido por ponto."""
    offsets = np.arange(-6.0, MAX_BAND_OFFSET + 0.25, 0.25)
    xs = points[:, 0, None] + offsets[None, :] * outward[:, 0, None]
    ys = points[:, 1, None] + offsets[None, :] * outward[:, 1, None]
    profile = geo.bilinear(rgb, xs, ys)
    strength = np.max(np.abs(profile[:, 2:, :] - profile[:, :-2, :]), axis=2)
    centers = offsets[1:-1]
    peak = (strength > PEAK_THRESHOLD) & (strength >= np.roll(strength, 1, axis=1)) & (strength >= np.roll(strength, -1, axis=1))
    peak &= (centers >= MIN_BAND_OFFSET) & (centers <= MAX_BAND_OFFSET)[None, :]
    peak &= observed[:, None]
    if unknown is not None:
        valid=_known_sample_footprint(unknown,xs,ys)
        peak &= valid[:,:-2] & valid[:,1:-1] & valid[:,2:]

    pooled = sorted(((int(index), float(centers[column])) for index, column in zip(*np.nonzero(peak))), key=lambda item: item[1])
    if not pooled:
        return []
    clusters = [[pooled[0]]]
    for item in pooled[1:]:
        if item[1] - clusters[-1][-1][1] <= 1.0:
            clusters[-1].append(item)
        else:
            clusters.append([item])

    observed_count = max(1, int(observed.sum()))
    bands = []
    for cluster in clusters:
        distinct = len({index for index, _ in cluster})
        if distinct < 0.5 * observed_count:
            continue
        values = np.array([value for _, value in cluster])
        median = float(np.median(values))
        per_point = np.full(len(points), np.nan)
        best = np.full(len(points), np.inf)
        for index, value in cluster:
            if abs(value - median) < best[index]:
                best[index] = abs(value - median)
                per_point[index] = value
        known = ~np.isnan(per_point)
        per_point = np.interp(np.arange(len(points)), np.nonzero(known)[0], per_point[known], period=len(points))
        bands.append({
            "offset_px": median,
            "support": distinct / observed_count,
            "range_px": [float(values.min()), float(values.max())],
            "per_point": per_point,
        })
    bands.sort(key=lambda band: band["offset_px"])
    return bands[:MAX_BANDS]


def _detect_glow(rgb, points, outward, observed, unknown=None):
    """Halo (ou sombra) por ajuste de Gaussiana ao excesso de luminância externo."""
    # A transição de borda fica em 0–1,25 px; o halo é ajustado a partir daí.
    span = np.arange(MIN_BAND_OFFSET, 24.5, 0.25)
    xs = points[:, 0, None] + span[None, :] * outward[:, 0, None]
    ys = points[:, 1, None] + span[None, :] * outward[:, 1, None]
    usable=observed.copy()
    if unknown is not None:
        usable &= _known_sample_footprint(unknown,xs,ys).all(axis=1)
    samples = geo.bilinear(rgb, xs, ys)[usable]
    if len(samples) < 8:
        return None
    luminance = geo.luminance(samples)
    far = float(np.median(luminance[:, span >= 18.0]))
    excess = np.mean(luminance - far, axis=0)
    best = None
    for sigma in np.linspace(0.8, 12.0, 60):
        basis = np.exp(-(span * span) / (2 * sigma * sigma))
        amplitude = float(excess @ basis / max(float(basis @ basis), 1e-12))
        error = float(np.sum((excess - amplitude * basis) ** 2))
        if best is None or error < best[0]:
            best = (error, float(sigma), amplitude)
    error, sigma, amplitude = best
    total = float(np.sum((excess - excess.mean()) ** 2))
    r_squared = 1.0 - error / total if total > 1e-9 else 0.0
    peak_index = int(np.argmax(np.abs(excess[span <= 6.0])))
    peak_color = samples[:, peak_index].mean(axis=0)
    contrast = float(geo.luminance(peak_color) - far)
    if abs(amplitude) < 4.0 or r_squared < 0.5 or abs(contrast) < 1.0:
        return None
    # A cor do pico já é uma composição com o fundo: se o contraste de cor não explica a
    # intensidade medida, a alfa fica limitada a 1 e a estimativa passa a baixa confiança.
    explained = abs(contrast) >= abs(amplitude)
    return {
        "kind": "glow" if amplitude > 0 else "shadow",
        "amplitude_luminance": _rounded(amplitude, 3),
        "sigma_px": _rounded(sigma, 3),
        "r_squared": _rounded(r_squared, 3),
        "color": [_rounded(v, 2) for v in peak_color],
        "background_luminance": _rounded(far, 2),
        "amplitude_alpha": _rounded(min(1.0, abs(amplitude) / abs(contrast)), 3),
        "confidence": "média" if r_squared >= 0.8 and explained else "baixa",
        "note": "" if explained else "intensidade maior que o contraste da cor do pico; cor do brilho não separada do fundo",
    }


def _ring_samples(rgb, points, outward, low, high, usable, count=6, unknown=None):
    """Posições e cores amostradas entre deslocamentos `low` e `high` (arrays por ponto)."""
    fractions = np.linspace(0.15, 0.85, count)[None, :]
    offsets = low[:, None] + fractions * (high - low)[:, None]
    xs = points[:, 0, None] + offsets * outward[:, 0, None]
    ys = points[:, 1, None] + offsets * outward[:, 1, None]
    valid=np.broadcast_to(usable[:,None],xs.shape).copy()
    if unknown is not None:
        valid &= _known_sample_footprint(unknown,xs,ys)
    colors=geo.bilinear(rgb,xs,ys)[valid]
    positions=np.column_stack([xs[valid],ys[valid]])
    return positions,colors.reshape(-1,3)


def _fit_color(positions, colors, origin):
    """Cor sólida ou linear por regressão c = a + b·(x − ox) + d·(y − oy), com R² reportado."""
    if len(colors) < 12:
        return {"kind": "desconhecida", "confidence": "baixa", "reason": "amostras insuficientes"}
    median = np.median(colors, axis=0)
    design = np.column_stack([np.ones(len(positions)), positions - origin])
    beta, *_ = np.linalg.lstsq(design, colors, rcond=None)
    predicted = design @ beta
    total = np.sum((colors - colors.mean(axis=0)) ** 2, axis=0)
    residual = np.sum((colors - predicted) ** 2, axis=0)
    r_squared = float(np.mean(1.0 - residual / np.maximum(total, 1e-9)))
    spread = float(np.max(np.ptp(predicted, axis=0)))
    if r_squared >= 0.6 and spread >= 16.0:
        return {
            "kind": "linear",
            "origin": [_rounded(origin[0]), _rounded(origin[1])],
            "color": [_rounded(v, 2) for v in beta[0]],
            "slope": [[_rounded(v, 5) for v in beta[1]], [_rounded(v, 5) for v in beta[2]]],
            "r_squared": _rounded(r_squared),
            "confidence": "média" if r_squared >= 0.85 else "baixa",
        }
    spread_sample = float(np.max(np.std(colors, axis=0)))
    return {
        "kind": "solid",
        "color": [_rounded(v, 2) for v in median],
        "spread_levels": _rounded(spread, 2),
        "confidence": "alta" if spread_sample < 6 else "média",
    }


def _segment_json(segment, origin):
    entry = {"type": segment["type"], "max_error_px": _rounded(segment["max_error_px"]),
             'evidence_class':'estimado','confidence':'média',
             'confidence_basis':'ajuste ao contraste observado; erro geométrico declarado, sem probabilidade calibrada'}
    if segment["type"] == "line":
        entry["start"] = {"crop": _points_list([segment["start"]])[0], "image": _points_list([segment["start"] + origin])[0]}
        entry["end"] = {"crop": _points_list([segment["end"]])[0], "image": _points_list([segment["end"] + origin])[0]}
    elif segment["type"] == "arc":
        entry.update({
            "center": {"crop": _points_list([segment["center"]])[0], "image": _points_list([segment["center"] + origin])[0]},
            "radius_px": _rounded(segment["radius"]),
            "start_angle_deg": _rounded(math.degrees(segment["start_angle"]), 2),
            "sweep_deg": _rounded(math.degrees(segment["sweep"]), 2),
            "start": _points_list([segment["start"]])[0],
            "end": _points_list([segment["end"]])[0],
            'start_image':_points_list([segment['start']+origin])[0],
            'end_image':_points_list([segment['end']+origin])[0],
            'raw_start_end_frame':'crop',
        })
    else:
        entry["control_points"] = {"crop": _points_list(segment["control"]), "image": _points_list(segment["control"] + origin)}
    return entry


def _path_data(segments, origin=(0.0, 0.0), closed=True):
    """Caminho SVG (M/L/A/C) no quadro do recorte."""
    ox, oy = origin
    first = segments[0]['control'][0] if segments[0]['type'] in {'cubic', 'quadratic'} else segments[0]['start']
    commands = [f"M{first[0] - ox:.3f},{first[1] - oy:.3f}"]
    for segment in segments:
        if segment['type'] == 'quadratic':
            control, end = segment['control'][1:]
            commands.append(f'Q{control[0]-ox:.3f},{control[1]-oy:.3f} {end[0]-ox:.3f},{end[1]-oy:.3f}')
            continue
        if segment["type"] == "cubic":
            c1, c2, end = segment["control"][1], segment["control"][2], segment["control"][3]
            commands.append(f"C{c1[0] - ox:.3f},{c1[1] - oy:.3f} {c2[0] - ox:.3f},{c2[1] - oy:.3f} {end[0] - ox:.3f},{end[1] - oy:.3f}")
            continue
        end = segment["end"]
        if segment["type"] == "line":
            commands.append(f"L{end[0] - ox:.3f},{end[1] - oy:.3f}")
        else:
            large = 1 if abs(segment["sweep"]) > math.pi else 0
            sweep = 1 if segment["sweep"] > 0 else 0
            radius = segment["radius"]
            commands.append(f"A{radius:.3f},{radius:.3f} 0 {large} {sweep} {end[0] - ox:.3f},{end[1] - oy:.3f}")
    if closed:
        commands.append('Z')
    return " ".join(commands)


def _is_right_angle(first, second):
    a = first["end"] - first["start"]
    b = second["end"] - second["start"]
    cosine = abs(float(a @ b)) / max(math.hypot(*a) * math.hypot(*b), 1e-9)
    return cosine <= math.cos(math.radians(87))


def _classify_decision(base_segments, bands, glow, method):
    """Procedimento tradicional ou matemático, pela geometria observada e pelos efeitos."""
    reasons = []
    if method != "regiao_de_cor":
        reasons.append("contorno obtido por raios de borda, sem região de cor consistente")
    if bands:
        reasons.append(f"{len(bands)} faixa(s) de borda medida(s) além da região principal")
    if glow is not None:
        reasons.append("halo ou sombra externa detectado")
    if any(s["type"] == "cubic" for s in base_segments):
        reasons.append("trechos curvos sem arco simples, exigindo Bézier cúbica")
    lines = [s for s in base_segments if s["type"] == "line"]
    if any(abs(math.degrees(math.atan2(s["end"][1] - s["start"][1], s["end"][0] - s["start"][0])) % 90 - 45) < 8
           and math.hypot(*(s["end"] - s["start"])) >= 2.0 for s in lines):
        reasons.append("chanfros ou segmentos diagonais observados")
    count = len(base_segments)
    orthogonal = all(
        _is_right_angle(base_segments[i], base_segments[(i + 1) % count])
        for i in range(count)
        if base_segments[i]["type"] == "line" and base_segments[(i + 1) % count]["type"] == "line"
    )
    types = {s["type"] for s in base_segments}
    if not reasons and types <= {"line", "arc"} and orthogonal:
        return "tradicional", ["retângulo, arco, círculo ou retângulo arredondado sem efeitos adicionais"]
    return "matematica", reasons or ["geometria irregular"]


# --------------------------------------------------------------------------- métricas e diagnósticos

def _metrics(crop, rendered_rgb, rendered_alpha, interior, boundary_zone, evidence_count, model_points, chamfer, unknown):
    result = {"conditions": {
        "units": "px_imagem",
        "match_tolerance_px": MATCH_PX,
        "evidence": "pontos refinados do contorno base, fora de marcações e áreas excluídas",
        "frame": "recorte com margem; o fundo fora do elemento não é reconstruído e não entra nas métricas de aparência",
    }}
    if chamfer is None:
        result["geometry"] = {"status": "não calculado: evidência insuficiente"}
    else:
        result["geometry"] = {
            "evidence_points": int(evidence_count),
            "model_points": int(len(model_points)),
            "bidirectional_chamfer_mean_px": _rounded(chamfer["bidirectional_mean_px"]),
            "model_to_evidence_mean_px": _rounded(chamfer["mean_model_to_evidence_px"]),
            "evidence_to_model_mean_px": _rounded(chamfer["mean_evidence_to_model_px"]),
            "hausdorff_px": _rounded(chamfer["hausdorff_px"]),
            "precision_within_1_5px": _rounded(np.mean(chamfer["to_evidence"] <= MATCH_PX), 4),
            "coverage_within_1_5px": _rounded(np.mean(chamfer["to_model"] <= MATCH_PX), 4),
        }
    difference = np.abs(crop - rendered_rgb)
    opaque = interior & (rendered_alpha > 0.999) & ~unknown
    appearance = {"interior": {"pixels": int(opaque.sum())}}
    if opaque.any():
        ssim_map = geo.ssim_luminance(geo.luminance(crop), geo.luminance(rendered_rgb))
        margin = 4
        # SSIM usa vizinhança: exclua também janelas contaminadas.
        trusted = geo.box_filter((~unknown).astype(float), 7) > 1-1e-9
        inner = (opaque & trusted)[margin:-margin, margin:-margin]
        appearance["interior"].update({
            "mae_rgb": _rounded(difference[opaque].mean()),
            "ssim_mean": _rounded(ssim_map[inner].mean(), 4) if inner.any() else None,
            "ssim_note": "SSIM de luminância, janela uniforme 7×7; não é porcentagem de fidelidade",
        })
    zone = boundary_zone & (rendered_alpha > 0.0) & ~unknown
    if zone.any():
        appearance["boundary_zone"] = {
            "pixels": int(zone.sum()),
            "mae_rgb": _rounded(difference[zone].mean()),
            "note": "faixa de ±2 px ao redor do contorno; sensível a deslocamentos de 0,5 px",
        }
    appearance["unknown_pixels_excluded"] = int(unknown.sum())
    result["appearance"] = appearance
    return result


def _write_diagnostics(output, crop, rendered_rgb, rendered_alpha, edges, unknown, refined, base_dense,
                       evidence_mask, contour_segments, closed=True):
    folder = output / "diagnostics"
    scale = DIAGNOSTIC_SCALE
    height, width = crop.shape[:2]
    white = np.full(crop.shape, 255.0)
    over_white = rendered_rgb * rendered_alpha[..., None] + white * (1 - rendered_alpha[..., None])
    checker = np.where((np.arange(height)[:, None] // 6 + np.arange(width)[None, :] // 6)[..., None] % 2 == 0, 200.0, 240.0)
    over_checker = rendered_rgb * rendered_alpha[..., None] + np.broadcast_to(checker, crop.shape) * (1 - rendered_alpha[..., None])
    overlay = (crop + over_white) / 2.0
    difference = np.abs(crop - over_white)

    def enlarge(array):
        return np.repeat(np.repeat(array, scale, axis=0), scale, axis=1)

    edge_view = np.zeros(crop.shape)
    edge_view[edges] = 255.0
    edge_view[unknown] = edge_view[unknown] * 0.3 + np.array([255.0, 0.0, 255.0]) * 0.7

    background = image_tools.Image.fromarray(np.clip(enlarge(crop * 0.6), 0, 255).astype(np.uint8))
    draw = image_tools.ImageDraw.Draw(background)
    for px, py in refined[evidence_mask]:
        draw.ellipse((px * scale - 1, py * scale - 1, px * scale + 1, py * scale + 1), fill=(0, 255, 0))
    for px, py in base_dense[::4]:
        draw.point((px * scale, py * scale), fill=(255, 255, 0))

    curves = image_tools.Image.fromarray(np.clip(enlarge(crop * 0.5), 0, 255).astype(np.uint8))
    draw_curves = image_tools.ImageDraw.Draw(curves)
    palette = [(0, 200, 255), (255, 120, 0), (255, 0, 160), (120, 255, 80), (255, 255, 0)]
    for index, segments in enumerate(contour_segments):
        points = geo.sample_segments(segments) * scale
        plot = np.vstack([points,points[:1]]) if closed else points
        draw_curves.line([(float(x),float(y)) for x,y in plot], fill=palette[index % len(palette)], width=1)
        for segment in segments:
            controls = segment.get('control')
            if controls is not None:
                handles = [(float(p[0]*scale),float(p[1]*scale)) for p in controls]
                draw_curves.line(handles, fill=(180,180,180), width=1)
                for hx,hy in handles:
                    draw_curves.ellipse((hx-2,hy-2,hx+2,hy+2),fill=(255,255,255))

    files = {
        "source_crop_x4": ("source_crop_x4.png", enlarge(crop)),
        "render_x4": ("render_x4.png", enlarge(over_checker)),
        "overlay_x4": ("overlay_x4.png", enlarge(overlay)),
        "difference_x4": ("difference_x4.png", enlarge(difference)),
        "edges_x4": ("edges_x4.png", enlarge(edge_view)),
    }
    written = {}
    for key, (name, array) in files.items():
        _write_bytes_new(_encode_png(array), folder / name)
        written[key] = str(folder / name)
    for key, name, image in (("points_x4", "points_x4.png", background), ("curves_x4", "curves_x4.png", curves)):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        _write_bytes_new(buffer.getvalue(), folder / name)
        written[key] = str(folder / name)
    written["note"] = (
        "Diagnósticos ampliados ×4 por repetição de pixels, sem interpolação. "
        "A diferença não é amplificada; a sobreposição mistura original e render 50/50."
    )
    return written


def _svg_document(element, contour_segments, fills, glow, shape):
    height, width = shape
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f"  <title>{escape(element['id'])}: contornos reconstruídos (quadro do recorte, px_imagem)</title>",
        f"  <desc>Recorte x={element['analysis_frame']['x']}, y={element['analysis_frame']['y']} da captura de origem. "
        "Caminhos editáveis; cores e efeitos estimados estão em element.json.</desc>",
    ]
    defs = []
    paints = {}
    corners = np.array([[0, 0], [width, 0], [0, height], [width, height]], dtype=np.float64)
    for index, fill in enumerate(fills):
        if fill.get("kind") != "linear":
            continue
        slope = np.asarray(fill["slope"], dtype=np.float64)
        weights = np.array([0.2126, 0.7152, 0.0722])
        direction = np.array([slope[0] @ weights, slope[1] @ weights])
        norm = float(np.hypot(*direction))
        unit = direction / norm if norm > 1e-9 else np.array([1.0, 0.0])
        origin = np.asarray(fill["origin"], dtype=np.float64)
        projection = (corners-origin) @ unit
        base = np.asarray(fill["color"], dtype=np.float64)
        start, end = origin+projection.min()*unit, origin+projection.max()*unit
        stops = []
        for point in (start, end):
            delta = point - origin
            stops.append(np.clip(base + delta[0] * slope[0] + delta[1] * slope[1], 0, 255))
        gid = f"grad{index}"
        paints[index] = f"url(#{gid})"
        defs.append(
            f'    <linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{start[0]:.2f}" y1="{start[1]:.2f}" '
            f'x2="{end[0]:.2f}" y2="{end[1]:.2f}"><stop offset="0" stop-color="rgb({stops[0][0]:.0f},{stops[0][1]:.0f},{stops[0][2]:.0f})"/>'
            f'<stop offset="1" stop-color="rgb({stops[1][0]:.0f},{stops[1][1]:.0f},{stops[1][2]:.0f})"/></linearGradient>'
        )
    if glow is not None:
        defs.append(f'    <filter id="halo" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="{glow["sigma_px"]:.2f}"/></filter>')
    if defs:
        lines.append("  <defs>")
        lines.extend(defs)
        lines.append("  </defs>")
    if glow is not None:
        color = glow["color"]
        lines.append(
            f'  <path id="effect-{glow["kind"]}" d="{_path_data(contour_segments[-1])}" '
            f'fill="rgb({color[0]:.0f},{color[1]:.0f},{color[2]:.0f})" fill-opacity="{glow["amplitude_alpha"]:.3f}" '
            'filter="url(#halo)" data-note="aproximação por desfoque gaussiano do contorno externo"/>'
        )
    for index in range(len(contour_segments) - 1, -1, -1):
        fill = fills[index]
        if index in paints:
            paint = paints[index]
        elif fill.get("kind") == "solid":
            color = fill["color"]
            paint = f"rgb({color[0]:.0f},{color[1]:.0f},{color[2]:.0f})"
        else:
            paint = "#808080"
        role = "fill_interior" if index == 0 else f"border_band_{index}"
        path = _path_data(contour_segments[index])
        for hole in element.get('revision_state', {}).get('holes_crop', []):
            path += ' ' + _path_data(geo.fit_primitives(np.asarray(hole), TOLERANCE_PX))
        lines.append(f'  <path id="C{index}" d="{path}" fill="{paint}" fill-rule="evenodd" data-role="{role}"/>')
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- análise

def analyze_element(image_path, bbox, output_dir, *, seed=None, fill_tolerance=24, margin=10,
                    exclusions=(), element_id="E01", scale=None, markup_filter=False,
                    tolerance=0.6, max_iterations=30, loss_weights=None):
    """Analisa um componente e grava especificação, SVG, diagnósticos e métricas em pasta nova."""
    _require_numpy()
    if type(fill_tolerance) is not int or not 0 <= fill_tolerance <= 255:
        raise ContourToolError("A tolerância de cor deve ser um inteiro de 0 a 255.")
    if type(margin) is not int or not 0 <= margin <= 200:
        raise ContourToolError("A margem deve ser um inteiro de 0 a 200 px.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,63}", element_id):
        raise ContourToolError("ID do elemento inválido.")
    if scale is not None and (not np.isfinite(scale) or scale <= 0):
        raise ContourToolError('A escala deve ser finita e positiva.')
    if not np.isfinite(tolerance) or not 0.05 <= tolerance <= 5:
        raise ContourToolError('A tolerância deve estar entre 0,05 e 5 px.')
    if type(max_iterations) is not int or not 1 <= max_iterations <= 200:
        raise ContourToolError('Use entre 1 e 200 iterações.')
    weights = {'contour':1.,'color':1.,'thickness':0.05,'regularization':0.0025}
    if loss_weights:
        if not isinstance(loss_weights,dict) or set(loss_weights)-set(weights):
            raise ContourToolError('Pesos aceitos: contour, color, thickness, regularization.')
        weights.update(loss_weights)
    if any(type(v) not in (int,float) or not np.isfinite(v) or v<0 for v in weights.values()) or weights['contour']<=0:
        raise ContourToolError('Pesos devem ser finitos e não negativos; contour deve ser positivo.')
    source = _path(image_path)
    output = _create_output_dir(_path(output_dir))

    full, (full_width, full_height) = _load_rgb(source)
    x, y, box_width, box_height = _validate_bbox(bbox, full_width, full_height)
    left, top = max(0, x - margin), max(0, y - margin)
    right, bottom = min(full_width, x + box_width + margin), min(full_height, y + box_height + margin)
    if right - left > MAX_SIDE or bottom - top > MAX_SIDE:
        raise ContourToolError(f"Recorte maior que {MAX_SIDE} px; reduza a margem ou o componente.")
    crop = full[top:bottom, left:right].copy()
    shape = crop.shape[:2]
    origin = np.array([left, top], dtype=np.float64)
    if seed is None:
        seed_local = (x - left + box_width // 2, y - top + box_height // 2)
    else:
        seed_local = (seed[0] - left, seed[1] - top)
    if not (0 <= seed_local[0] < shape[1] and 0 <= seed_local[1] < shape[0]):
        raise ContourToolError("A semente está fora do recorte analisado.")

    gray = geo.luminance(crop)
    edges, _, _ = geo.canny_edges(crop)
    markup = _dilate(_markup_mask(crop)) if markup_filter else np.zeros(shape, dtype=bool)
    excluded = _exclusion_mask(shape, exclusions, (left, top))
    unknown = markup | excluded
    notes = []
    hole_count = 0
    hole_paths = []

    try:
        mask, used_tolerance = _region_mask(crop, seed_local, fill_tolerance, excluded, markup, box_width * box_height)
        outer, holes = geo.trace_loops(mask)
        base_loop = max(outer, key=lambda loop: abs(geo._shoelace(loop)))
        dense = geo.resample(geo.simplify_closed(base_loop, 1.0), 1.0)
        normals = geo.closed_normals(dense, mask)
        hole_count = len(holes)
        hole_paths = [geo.sample_segments(geo.fit_primitives(h, tolerance)) for h in holes
                      if abs(geo._shoelace(h)) >= 4 and not _nearest_flags(unknown,h).any()]
        method = "regiao_de_cor"
        if used_tolerance != fill_tolerance:
            notes.append(f"tolerância ampliada para {used_tolerance} para cobrir gradiente da região")
    except geo.GeometryError as exc:
        method = "raios_de_borda"
        ray_points, hit_fraction = _ray_contour(edges, unknown, seed_local, shape)
        notes.append(f"região de cor não utilizável ({exc}); contorno por raios de borda Canny ({hit_fraction:.0%} dos raios com borda)")
        dense = geo.resample(ray_points, 1.0)
        normals = _orient_inward(dense, shape)

    refined, _, subpixel_confidence = geo.refine_subpixel(gray, dense, normals)
    refined = geo.smooth_closed(refined, window=1)
    observed = ~_nearest_flags(excluded, refined)
    unknown_refined = _nearest_flags(unknown, refined)
    evidence_mask = observed & ~unknown_refined
    outward = -normals
    bands = _detect_bands(crop, refined, outward, evidence_mask,unknown)
    # Regularização de espessura periódica, sem assumir espessura constante.
    for band in bands:
        original = band['per_point'].copy()
        value = original.copy()
        strength = weights['thickness']
        for _ in range(20):
            value = (original+strength*(np.roll(value,1)+np.roll(value,-1)))/(1+2*strength)
        band['per_point'] = value
    outermost = refined + bands[-1]["per_point"][:, None] * outward if bands else refined
    glow = _detect_glow(crop, outermost, outward, evidence_mask,unknown)

    # Ajuste iterativo dos vértices do contorno base: o candidato mais simples que atinge a tolerância vence.
    evidence = refined[evidence_mask]
    base_vertices = None
    optimization = {"status": "não executado", "reason": "evidência insuficiente"}
    circle_model=geo.fit_circle(evidence) if len(evidence)>=12 and not unknown.any() else None
    if circle_model is not None and circle_model[3]<=tolerance:
        optimization={'status':'círculo por mínimos quadrados','parameters':3,
                      'max_radial_error_px':_rounded(circle_model[3]),
                      'criterion':'modelo circular simples aceito apenas com suporte completo e erro dentro da tolerância'}
    else:
        circle_model=None
    if circle_model is None and len(evidence) >= 8:
        if len(evidence) > EVIDENCE_LIMIT:
            evidence = evidence[np.linspace(0, len(evidence) - 1, EVIDENCE_LIMIT).astype(int)]
        candidates = []
        for epsilon in (1.5, 0.8, 0.4):
            initial = geo.simplify_closed(refined, epsilon)
            if len(initial) < 3:
                continue
            vertices, history, final = geo.fit_polygon_vertices(initial, evidence, max_iterations=max_iterations,
                  contour_weight=math.sqrt(weights['contour']),anchor_weight=math.sqrt(weights['regularization']),known_mask=~unknown)
            candidates.append((vertices, history, epsilon, float(np.sqrt(np.mean(final ** 2)))))
            if candidates[-1][3] <= tolerance:
                break
        if candidates:
            chosen = next((item for item in candidates if item[3] <= tolerance), min(candidates,key=lambda item:item[3]))
            base_vertices = chosen[0]
            optimization = {
                "status": "executado",
                "candidates": [{"vertices": int(len(c[0])), "epsilon_px": c[2], "rms_px": _rounded(c[3])} for c in candidates],
                "chosen": {"vertices": int(len(chosen[0])), "epsilon_px": chosen[2], "rms_px": _rounded(chosen[3])},
                "cost_initial": _rounded(chosen[1][0]),
                "cost_final": _rounded(chosen[1][-1]),
                "criterion": f"menor número de vértices com erro médio ≤ {tolerance} px; se nenhum atingir, o de menor erro",
            }

    circle_segments=geo.circle_primitives(*circle_model[:3],fit_error=circle_model[3]) if circle_model is not None else None
    base_dense = (geo.sample_segments(circle_segments,1.) if circle_segments is not None else
                  (geo.resample(base_vertices, 1.0) if base_vertices is not None else refined))
    mapping = _nearest_index(refined, base_dense)
    observed_base = observed[mapping]
    unknown_base = unknown_refined[mapping]
    base_outward = -_orient_inward(base_dense, shape)
    band_offsets = [band["per_point"][mapping] for band in bands]
    base_segments = circle_segments if circle_segments is not None else geo.fit_primitives(base_vertices if base_vertices is not None else base_dense, tolerance)

    contour_points = [base_dense] + [base_dense + offset[:, None] * base_outward for offset in band_offsets]
    contour_offsets = [np.zeros(len(base_dense))] + band_offsets
    contour_segments = [base_segments] + [geo.fit_primitives(points, tolerance) for points in contour_points[1:]]

    # Cores: interior de C0 (faixa entre −5,5 e −2 px) e cada anel entre contornos consecutivos.
    usable_fill = observed_base & ~unknown_base
    origin_point = base_dense.mean(axis=0)
    fill_positions, fill_colors = _ring_samples(crop, base_dense, base_outward,
                                                np.full(len(base_dense), -5.5), np.full(len(base_dense), -2.0), usable_fill,unknown=unknown)
    fills = [_fit_color(fill_positions, fill_colors, origin_point)]
    for index in range(1, len(contour_points)):
        low = contour_offsets[index - 1] + 1.0
        high = contour_offsets[index] - 1.0
        usable = usable_fill & (high > low)
        if not usable.any():
            fills.append({"kind": "desconhecida", "confidence": "baixa", "reason": "anel fino demais para amostragem"})
            continue
        ring_positions, ring_colors = _ring_samples(crop, base_dense, base_outward, low, high, usable,unknown=unknown)
        fills.append(_fit_color(ring_positions, ring_colors, origin_point))

    decision, reasons = _classify_decision(base_segments, bands, glow, method)

    contour_records = []
    for index, segments in enumerate(contour_segments):
        offsets = contour_offsets[index]
        contour_records.append({
            "id": f"C{index}",
            "role": "fill_region_boundary" if index == 0 else f"border_band_{index}_outer_edge",
            "offset_px": {"median": _rounded(np.median(offsets)), "min": _rounded(offsets.min()), "max": _rounded(offsets.max())},
            "points": int(len(contour_points[index])),
            "segments_crop": [_segment_json(s, origin) for s in segments],
            "segments_image": [_segment_json(s, origin) for s in segments],
            "max_fit_error_px": _rounded(max((s["max_error_px"] for s in segments), default=0.0)),
            'width_samples_px':[_rounded(v) for v in offsets],
            'evidence_class':'estimado; transições amostradas e interpolação nos intervalos sem suporte',
            'confidence':'média' if evidence_mask.mean()>0.9 else 'baixa',
        })

    layers = []
    if glow is not None:
        layers.append({"contour": None, "role": glow["kind"], "color_model": {"kind": "solid", "color": glow["color"]},
                       "parameters": glow, "confidence": glow["confidence"]})
    for index in range(len(contour_points) - 1, -1, -1):
        layers.append({
            "contour": f"C{index}",
            "role": "fill_interior" if index == 0 else f"border_band_{index}",
            "color_model": fills[index],
            "confidence": fills[index].get("confidence", "média"),
        })
    for order, layer in enumerate(layers):
        layer["order"] = order

    render_layers = []
    if glow is not None:
        render_layers.append({"kind": "glow", "polygon": geo.sample_segments(contour_segments[-1]),
                              "color": glow["color"], "amplitude": glow["amplitude_alpha"], "sigma": glow["sigma_px"]})
    for index in range(len(contour_points) - 1, -1, -1):
        render_layers.append({"kind": "fill", "polygon": geo.sample_segments(contour_segments[index]),
                              "holes":hole_paths, "fill": _renderable(fills[index])})
    rendered = geo.render_layers(shape, render_layers)
    rendered_rgb, rendered_alpha = rendered[..., :3], rendered[..., 3] / 255.0

    model_points = geo.sample_segments(base_segments)
    visible_model = model_points[~_nearest_flags(unknown, model_points)]
    chamfer = geo.bidirectional_chamfer(visible_model, refined[evidence_mask]) if evidence_mask.any() and len(visible_model) else None
    signed = geo.signed_distance(model_points, shape)
    for hole in hole_paths:
        signed = np.maximum(signed,-geo.signed_distance(hole,shape))
    interior = (signed < -2.0) & ~unknown
    boundary_zone = (np.abs(signed) <= 2.0) & ~unknown
    metrics_data = _metrics(crop, rendered_rgb, rendered_alpha, interior, boundary_zone, int(evidence_mask.sum()),
                            model_points, chamfer, unknown)

    diagnostics = _write_diagnostics(output, crop, rendered_rgb, rendered_alpha, edges, unknown, refined, base_dense,
                                     evidence_mask, contour_segments)
    context = diagnostic.write_context(output, source, full, (left,top,shape[1],shape[0]), rendered, unknown,model_points,hole_paths)
    diagnostics['context'] = context
    metrics_data['context'] = context['metrics']
    terms = {
        'contour':float(chamfer['bidirectional_mean_px']**2) if chamfer else None,
        'color':float(metrics_data['appearance']['interior'].get('mae_rgb',0))/255,
        'thickness':float(np.mean([np.mean(np.diff(b['per_point'])**2) for b in bands])) if bands else 0.,
        'regularization':float(optimization.get('cost_final',0)),
    }
    metrics_data['objective'] = {'weights':weights,'terms':terms,
        'weighted_total':sum(weights[k]*v for k,v in terms.items() if v is not None),
        'scope':'ajuste alternado: Chamfer/ancoragem, regressão de cor, espessura e gaussiana; não é solução global de composição',
        'units':'termos heterogêneos normalizados conforme campos; não é porcentagem de fidelidade'}
    if glow is not None and glow["kind"] == "shadow":
        notes.append("efeito externo escuro identificado como sombra")

    element = {
        "id": element_id,
        "schema": SCHEMA,
        "source": {"image": str(source), "sha256": _sha256(source), "size": [full_width, full_height], "units": "px_imagem"},
        "bbox_original_image": {"x": x, "y": y, "width": box_width, "height": box_height},
        "analysis_frame": {"x": int(left), "y": int(top), "width": int(shape[1]), "height": int(shape[0]), "margin_px": margin},
        "reference_frame": "coordenadas 'crop' são do recorte; 'image' são da captura completa, origem (0,0) no canto superior esquerdo",
        "scale_reference": {
            "unit": "px_imagem",
            "image_px_per_css_px": scale,
            "status": "hipótese informada pelo usuário" if scale else "desconhecida",
        },
        "method": {
            "segmentation": method,
            "fill_tolerance_used": int(used_tolerance) if method == "regiao_de_cor" else None,
            "seed_crop": [int(seed_local[0]), int(seed_local[1])],
            "edges": "Canny (Sobel, supressão não máxima, histerese) sobre o maior gradiente entre canais",
            "subpixel": "cruzamento de 50% entre interior e exterior ao longo da normal (±2 px, limitado a ±1,5 px)",
            "markup_filter": bool(markup_filter),
            "markup_pixels_dilated": int(markup.sum()),
            "excluded_pixels": int(excluded.sum()),
            "holes_detected": hole_count,
            "holes_exported":len(hole_paths),
            "holes_ignored": hole_count-len(hole_paths),
            "notes": notes,
        },
        "geometry": {
            "type": "closed_path",
            'parametric_circle':({'center_crop':list(circle_model[:2]),'center_image':list(np.array(circle_model[:2])+origin),
                                  'radius_px':circle_model[2],'confidence':'média','evidence_class':'estimado por mínimos quadrados'}
                                  if circle_model is not None else None),
            "primitives_crop": [_segment_json(s, origin) for s in base_segments],
            "primitives_image": [_segment_json(s, origin) for s in base_segments],
            "vertices_crop": _points_list(base_vertices) if base_vertices is not None else [],
            "optimization": optimization,
            'internal_paths':[{'closed':True,'points_crop':_points_list(h),'points_image':_points_list(h+origin),
                               'evidence_class':'estimado','confidence':'média'} for h in hole_paths],
            'hidden_segments_status':'desconhecido; fechamento do modelo é hipótese e não evidência de pixels ocultos',
            'observed_samples_crop':_points_list(base_dense[~unknown_base]),
            'unknown_samples_crop':_points_list(base_dense[unknown_base]),
            "observed_fraction": _rounded(evidence_mask.mean()),
            "unobserved_note": "trechos sob áreas excluídas ou ocultas por outro componente são estimados, não observados",
        },
        "contours": contour_records,
        "layers": layers,
        "effects": {"glow_or_shadow": glow},
        "decision": {
            "procedure": decision,
            "reasons": reasons,
            "rule": "decidido pela geometria observada (retas, ângulos, arcos, faixas e efeitos), não pelo nome do componente",
        },
        "evidence_class": {
            "geometria_do_contorno": "medido (cruzamento de contraste) e estimado (vértices após ajuste)",
            "espessura_de_borda": "medido por ponto" if bands else "sem faixa acima de 1,25 px detectada",
            "cores": "medido por amostras; gradiente linear é estimativa por regressão" if any(f.get("kind") == "linear" for f in fills) else "medido por amostras",
            "brilho_ou_sombra": "estimado por ajuste gaussiano; pode ser contaminado por vizinhos" if glow else "não detectado",
            "partes_ocultas": "desconhecido" if evidence_mask.mean() < 1.0 else "não aplicável nesta captura",
        },
        "confidence": {
            'interpretation':'qualitativa; subpixel_mean é um indicador de contraste, não probabilidade calibrada',
            "subpixel_mean": _rounded(subpixel_confidence.mean()),
            "observed_fraction": _rounded(evidence_mask.mean()),
            "method": "alta" if method == "regiao_de_cor" and evidence_mask.mean() > 0.9 else "média",
        },
        "unknown": [
            "espessuras abaixo de 1,25 px não são separadas da borda principal",
            "pixels cobertos por outro componente não são recuperados",
            "cores de camadas translúcidas são estimativas do composto visível",
        ],
        "revision_state": {
            'edge_runs':diagnostic.encode_mask(edges),
            'analysis_parameters':{'tolerance':tolerance,'max_iterations':max_iterations,'loss_weights':weights},
            'unknown_runs':diagnostic.encode_mask(unknown),
            'holes_crop':[_points_list(h) for h in hole_paths],
            "base_dense_crop": _points_list(base_dense),
            "base_outward_normals": [[_rounded(x, 5), _rounded(y, 5)] for x, y in base_outward],
            "contour_offsets": {f"C{i}": [_rounded(v) for v in offsets] for i, offsets in enumerate(contour_offsets)},
            "fills": fills,
            "glow": glow,
            "evidence_crop": _points_list(evidence),
        },
        "diagnostics": diagnostics,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        'approval':{'status':'pending','note':'gerar métricas não aprova esta etapa'},
        'export_notes':['SVG contém geometria editável; filtro de halo e planos RGB não colineares são aproximações de aparência'],
    }
    _write_json_new(element, output / "element.json")
    _write_text_new(_svg_document(element, contour_segments, fills, glow, shape), output / "element.svg")
    _write_json_new(metrics_data, output / "metrics.json")
    return {
        "output_dir": str(output),
        "element": str(output / "element.json"),
        "svg": str(output / "element.svg"),
        "metrics": str(output / "metrics.json"),
        "diagnostics": diagnostics,
        "decision": decision,
        "segmentation": method,
    }


def _renderable(fill):
    """Converte o modelo de cor em entrada do renderizador: RGB sólido ou campo linear."""
    if fill.get("kind") == "linear":
        return fill
    if fill.get("kind") == "solid":
        return fill["color"]
    return [128.0, 128.0, 128.0]


# --------------------------------------------------------------------------- revisão

def trace_open_element(image_path,bbox,output_dir,*,start,end,element_id='E01',stroke_width=1.,tolerance=0.6):
    """Extrai um caminho Canny conectado entre âncoras observadas e exporta M/L/Q/C aberto."""
    _require_numpy()
    if not np.isfinite(stroke_width) or not 0<stroke_width<=100 or not 0.05<=tolerance<=5:
        raise ContourToolError('Espessura deve estar entre 0 e 100 px; tolerância entre 0,05 e 5 px.')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}',element_id):
        raise ContourToolError('ID inválido.')
    source=_path(image_path)
    full,(fw,fh)=_load_rgb(source)
    x,y,w,h=_validate_bbox(bbox,fw,fh)
    if max(w,h)>MAX_SIDE:
        raise ContourToolError('Região excede o orçamento de tamanho.')
    crop=full[y:y+h,x:x+w]
    edges,_,_=geo.canny_edges(crop)
    points=geo.trace_edge_path(edges,(start[0]-x,start[1]-y),(end[0]-x,end[1]-y))
    segments=geo.fit_open_primitives(points,tolerance)
    sampled=geo.sample_segments(segments)
    last=segments[-1]['control'][-1] if 'control' in segments[-1] else segments[-1]['end']
    sampled=np.vstack([sampled,last])
    field=geo.unsigned_distance(sampled,(h,w))
    alpha=np.clip(0.5+stroke_width/2-field,0,1)
    colors=crop[np.floor(points[:,1]).astype(int),np.floor(points[:,0]).astype(int)]
    color=np.median(colors,axis=0)
    rgba=np.dstack([np.broadcast_to(color,crop.shape),alpha*255])
    unknown=np.zeros((h,w),bool)
    output=_create_output_dir(_path(output_dir))
    diagnostics=_write_diagnostics(output,crop,rgba[...,:3],alpha,edges,unknown,points,sampled,
                    np.ones(len(points),bool),[segments],closed=False)
    context=diagnostic.write_context(output,source,full,(x,y,w,h),rgba,unknown,sampled,distance_field=field)
    diagnostics['context']=context
    distance=geo.bidirectional_chamfer(sampled,points)
    metrics=_metrics(crop,rgba[...,:3],alpha,np.zeros((h,w),bool),field<=stroke_width/2+2,len(points),sampled,distance,unknown)
    metrics['context']=context['metrics']
    model={'id':element_id,'schema':SCHEMA,'source':{'image':str(source),'sha256':_sha256(source),'size':[fw,fh]},
        'bbox_original_image':{'x':x,'y':y,'width':w,'height':h},
        'analysis_frame':{'x':x,'y':y,'width':w,'height':h},
        'geometry':{'type':'open_path','closed':False,'primitives_crop':[_segment_json(s,np.array([x,y])) for s in segments]},
        'method':{'edges':'Canny; menor caminho na componente conectada entre âncoras fornecidas',
                  'ui_membership':'candidato selecionado pelo operador; não classificação semântica automática'},
        'layers':[{'role':'stroke','width_px':stroke_width,'color':color.tolist(),'evidence_class':'espessura proposta; cor do composto amostrada'}],
        'diagnostics':diagnostics,'approval':{'status':'pending'},
        'unknown':['borda Canny não determina automaticamente a linha central de um traço','interior/exterior não determinados para caminho aberto']}
    path=_path_data(segments,closed=False)
    svg=(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">'
         f'<path d="{path}" fill="none" stroke="rgb({color[0]:.2f},{color[1]:.2f},{color[2]:.2f})" stroke-width="{stroke_width}"/></svg>\n')
    _write_json_new(model,output/'element.json')
    _write_text_new(svg,output/'element.svg')
    _write_json_new(metrics,output/'metrics.json')
    return {'element':str(output/'element.json'),'svg':str(output/'element.svg'),'diagnostics':diagnostics}


def _decode_revision_path(records):
    """Decodifica retas, quadráticas, cúbicas e arcos editáveis; exige continuidade fechada."""
    if not isinstance(records,list) or not 1<=len(records)<=128:
        raise ContourToolError('base_path exige de 1 a 128 segmentos.')
    result=[]
    def point(value):
        if isinstance(value,dict):
            value=value['crop']
        array=np.asarray(value,float)
        if array.shape!=(2,) or not np.isfinite(array).all():
            raise ContourToolError('Pontos devem ser pares finitos no quadro do recorte.')
        return array
    for record in records:
        kind=record['type']
        fit_error=float(record.get('max_error_px',0.))
        if not math.isfinite(fit_error) or fit_error<0:
            raise ContourToolError('Erro de ajuste deve ser finito e não negativo.')
        segment={'type':kind,'max_error_px':fit_error}
        if kind=='line':
            segment.update(start=point(record['start']),end=point(record['end']))
        elif kind in ('quadratic','cubic'):
            controls=record.get('control',record.get('control_points',{}))
            if isinstance(controls,dict):
                controls=controls.get('crop')
            controls=np.asarray(controls,float)
            if controls.shape!=((3 if kind=='quadratic' else 4),2) or not np.isfinite(controls).all():
                raise ContourToolError('Quantidade ou valores de pontos de controle inválidos.')
            segment['control']=controls
        elif kind=='arc':
            center=point(record['center'])
            radius=float(record.get('radius_px',record.get('radius',0)))
            start=math.radians(float(record['start_angle_deg']))
            sweep=math.radians(float(record['sweep_deg']))
            if not all(map(math.isfinite,(radius,start,sweep))) or radius<=0 or not 0<abs(sweep)<=2*math.pi:
                raise ContourToolError('Arco exige raio positivo e varredura entre 0 e 360 graus.')
            segment.update(center=center,radius=radius,start_angle=start,sweep=sweep,
                           start=center+radius*np.array([math.cos(start),math.sin(start)]),
                           end=center+radius*np.array([math.cos(start+sweep),math.sin(start+sweep)]))
            # Modelos gerados guardam as junções compartilhadas observadas. Não
            # substitua essas junções por projeções de círculos ajustados separadamente.
            for name in ('start','end'):
                if name in record:
                    original=point(record[name])
                    allowed=max(0.01,float(record.get('max_error_px',0))+0.01)
                    if np.linalg.norm(original-segment[name])>allowed:
                        raise ContourToolError('Extremo de arco incompatível com os parâmetros declarados.')
                    segment[name]=original
        else:
            raise ContourToolError('Tipos de caminho: line, quadratic, cubic, arc.')
        result.append(segment)
    endpoints=[(s['control'][0],s['control'][-1]) if 'control' in s else (s['start'],s['end']) for s in result]
    if any(np.linalg.norm(endpoints[i][1]-endpoints[(i+1)%len(result)][0])>0.01 for i in range(len(result))):
        raise ContourToolError('base_path deve ser contínuo e fechado; use trace-open para contornos abertos.')
    return result


def revise_element(model_path, overrides_path, output_dir, *, image_path):
    """Aplica correções a um element.json e grava uma revisão nova, sem nova detecção."""
    _require_numpy()
    model_file = _path(model_path)
    source = _path(image_path)
    try:
        model = json.loads(model_file.read_text(encoding="utf-8-sig"))
        overrides = json.loads(_path(overrides_path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContourToolError(f"Não foi possível ler o modelo ou as correções: {exc}") from exc
    if not isinstance(model, dict) or model.get("schema") != SCHEMA:
        raise ContourToolError("O arquivo não é uma especificação gerada por contour_tools.py analyze.")
    if model.get('geometry',{}).get('type')=='open_path':
        raise ContourToolError('Para caminhos abertos, ajuste âncoras/espessura com trace-open ou edite o SVG; revise opera em regiões fechadas.')
    if not isinstance(overrides, dict) or set(overrides) - REVISION_KEYS:
        raise ContourToolError(f"Correções aceitas: {sorted(REVISION_KEYS)}.")
    if _sha256(source) != model["source"]["sha256"]:
        raise ContourToolError("A imagem informada não é a mesma usada na análise (SHA-256 diferente).")
    output = _create_output_dir(_path(output_dir))

    full, _ = _load_rgb(source)
    frame = model["analysis_frame"]
    crop = full[frame["y"]:frame["y"] + frame["height"], frame["x"]:frame["x"] + frame["width"]].copy()
    shape = crop.shape[:2]
    origin = np.array([frame["x"], frame["y"]], dtype=np.float64)
    state = model["revision_state"]
    unknown = diagnostic.decode_mask(state.get('unknown_runs', []), shape)
    hole_paths = [np.asarray(h,dtype=float) for h in state.get('holes_crop',[])]
    base_dense = np.asarray(state["base_dense_crop"], dtype=np.float64)
    base_outward = np.asarray(state["base_outward_normals"], dtype=np.float64)
    fills = json.loads(json.dumps(state["fills"]))
    offsets = {key: np.asarray(value, dtype=np.float64) for key, value in state["contour_offsets"].items()}
    glow = state["glow"]
    changes = []
    base_path=_decode_revision_path(model['geometry']['primitives_crop'])
    if 'base_path' in overrides:
        if 'base_vertices' in overrides:
            raise ContourToolError('Use base_path ou base_vertices, não ambos.')
        base_path=_decode_revision_path(overrides['base_path'])
        base_dense=geo.sample_segments(base_path)
        base_outward=-_orient_inward(base_dense,shape)
        offsets={key:np.zeros(len(base_dense)) if key=='C0' else np.full(len(base_dense),float(np.median(value))) for key,value in offsets.items()}
        changes.append('base_path: pontos de controle corrigidos pelo usuário; faixas preservadas pela espessura mediana')

    if "base_vertices" in overrides:
        vertices = np.asarray(overrides["base_vertices"], dtype=np.float64)
        if vertices.ndim != 2 or vertices.shape[1] != 2 or len(vertices) < 3:
            raise ContourToolError("base_vertices deve ser uma lista de pares [x, y] com ao menos 3 vértices.")
        base_dense = geo.resample(vertices, 1.0)
        base_path=geo.fit_primitives(vertices,TOLERANCE_PX)
        base_outward = -_orient_inward(base_dense, shape)
        offsets = {key: np.zeros(len(base_dense)) if key == "C0" else np.full(len(base_dense), float(np.median(value)))
                   for key, value in offsets.items()}
        changes.append("base_vertices substituiu o contorno C0; faixas passaram a usar o deslocamento mediano, constante")
    for key, value in (overrides.get("offsets_px") or {}).items():
        if key not in offsets or key == "C0":
            raise ContourToolError(f"Deslocamento inválido para '{key}'.")
        if not isinstance(value, (int, float)) or value <= 0:
            raise ContourToolError(f"Deslocamento de {key} deve ser positivo, em px.")
        offsets[key] = np.full(len(base_dense), float(value))
        changes.append(f"{key} deslocado para {float(value):.3f} px (constante ao longo do contorno)")
    for key, color in (overrides.get("colors") or {}).items():
        if key not in offsets:
            raise ContourToolError(f"Contorno desconhecido para cor: '{key}'.")
        if not (isinstance(color, list) and len(color) == 3 and all(isinstance(v, (int, float)) and 0 <= v <= 255 for v in color)):
            raise ContourToolError(f"Cor de {key} deve ser [R, G, B] de 0 a 255.")
        fills[int(key[1:])] = {"kind": "solid", "color": [float(v) for v in color], "confidence": "corrigida pelo usuário"}
        changes.append(f"cor de {key} definida como {color} pelo usuário")
    if "glow" in overrides:
        glow_override = overrides["glow"]
        if glow_override is None or glow_override.get("enabled") is False:
            glow = None
            changes.append("halo ou sombra removido pelo usuário")
        else:
            glow = dict(glow or {"kind": "glow", "sigma_px": 3.0, "amplitude_alpha": 0.3, "color": [255.0, 255.0, 255.0]})
            glow.update({k: v for k, v in glow_override.items() if k != "enabled"})
            if (not math.isfinite(glow['sigma_px']) or glow['sigma_px']<=0 or
                not math.isfinite(glow['amplitude_alpha']) or not 0<=glow['amplitude_alpha']<=1 or
                len(glow['color'])!=3 or any(not np.isfinite(v) or not 0<=v<=255 for v in glow['color'])):
                raise ContourToolError('Brilho exige sigma positivo, alfa entre 0 e 1 e cor RGB finita entre 0 e 255.')
            changes.append("parâmetros de brilho ajustados pelo usuário")

    order = sorted(offsets, key=lambda k: int(k[1:]))
    contour_points = [base_dense + offsets[key][:, None] * base_outward for key in order]
    contour_segments = [base_path]+[geo.fit_primitives(points,TOLERANCE_PX) for points in contour_points[1:]]
    render_layers = []
    if glow is not None:
        render_layers.append({"kind": "glow", "polygon": geo.sample_segments(contour_segments[-1]),
                              "color": glow["color"], "amplitude": glow["amplitude_alpha"], "sigma": glow["sigma_px"]})
    for index in range(len(order) - 1, -1, -1):
        render_layers.append({"kind": "fill", "polygon": geo.sample_segments(contour_segments[index]),
                              "holes":hole_paths, "fill": _renderable(fills[index])})
    rendered = geo.render_layers(shape, render_layers)
    rendered_rgb, rendered_alpha = rendered[..., :3], rendered[..., 3] / 255.0

    evidence = np.asarray(state["evidence_crop"], dtype=np.float64).reshape(-1, 2)
    model_points = geo.sample_segments(base_path)
    visible_model = model_points[~_nearest_flags(unknown, model_points)]
    chamfer = geo.bidirectional_chamfer(visible_model, evidence) if len(evidence) and len(visible_model) else None
    signed = geo.signed_distance(model_points, shape)
    for hole in hole_paths:
        signed = np.maximum(signed,-geo.signed_distance(hole,shape))
    metrics_data = _metrics(crop, rendered_rgb, rendered_alpha, (signed < -2.0), (np.abs(signed) <= 2.0), len(evidence),
                            model_points, chamfer, unknown)
    metrics_data["revision"] = {"changes": changes, "from_model_sha256": _sha256(model_file)}

    revised = json.loads(json.dumps(model))
    revised["revision_state"].update({
        "base_dense_crop": _points_list(base_dense),
        "base_outward_normals": [[_rounded(x, 5), _rounded(y, 5)] for x, y in base_outward],
        "contour_offsets": {key: [_rounded(v) for v in offsets[key]] for key in order},
        "fills": fills,
        "glow": glow,
    })
    revised["effects"] = {"glow_or_shadow": glow}
    revised["revision"] = {"changes": changes, "from_model_sha256": _sha256(model_file)}
    revised['revision']['evidence_class']='parâmetros propostos/corrigidos pelo usuário; não nova medição'
    if 'base_path' in overrides or 'base_vertices' in overrides:
        revised['geometry']['optimization']={'status':'correção paramétrica explícita, sem nova detecção'}
        vertices=np.array([s['control'][0] if 'control' in s else s['start'] for s in base_path])
        revised['geometry']['vertices_crop']=_points_list(vertices)
        revised['geometry']['vertices_image']=_points_list(vertices+origin)
    revised['geometry']['observed_samples_crop']=_points_list(base_dense[~_nearest_flags(unknown,base_dense)])
    revised['geometry']['unknown_samples_crop']=_points_list(base_dense[_nearest_flags(unknown,base_dense)])
    revised["geometry"]["primitives_crop"] = [_segment_json(s, origin) for s in contour_segments[0]]
    revised["geometry"]["primitives_image"] = [_segment_json(s, origin) for s in contour_segments[0]]
    revised["contours"] = [
        {"id": key, "offset_px": {"median": _rounded(np.median(offsets[key]))},
         "segments_crop": [_segment_json(s, origin) for s in contour_segments[index]],
         "segments_image": [_segment_json(s, origin) for s in contour_segments[index]]}
        for index, key in enumerate(order)
    ]
    revised["layers"] = [
        {"order": position, "contour": key, "role": "fill_interior" if key == "C0" else f"border_band_{key[1:]}",
         "color_model": fills[int(key[1:])], "confidence": fills[int(key[1:])].get("confidence", "média")}
        for position, key in enumerate(reversed(order))
    ]
    if glow is not None:
        revised['layers'].insert(0,{'role':glow['kind'],'parameters':glow,'confidence':'proposto/corrigido'})
    for position,layer in enumerate(revised['layers']):
        layer['order']=position
    edge_map=diagnostic.decode_mask(state['edge_runs'],shape) if 'edge_runs' in state else geo.canny_edges(crop)[0]
    diagnostics = _write_diagnostics(output, crop, rendered_rgb, rendered_alpha, edge_map, unknown,
                                     evidence, base_dense, np.ones(len(evidence), dtype=bool), contour_segments)
    context = diagnostic.write_context(output,source,full,(frame['x'],frame['y'],frame['width'],frame['height']),
                                       rendered,unknown,model_points,hole_paths)
    diagnostics['context'] = context
    metrics_data['context'] = context['metrics']
    revised["diagnostics"] = diagnostics
    _write_json_new(revised, output / "element.json")
    _write_text_new(_svg_document(revised, contour_segments, fills, glow, shape), output / "element.svg")
    _write_json_new(metrics_data, output / "metrics.json")
    return {"output_dir": str(output), "changes": changes, "element": str(output / "element.json"),
            "svg": str(output / "element.svg"), "metrics": str(output / "metrics.json")}


# --------------------------------------------------------------------------- CLI

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ContourToolError(f"Argumentos inválidos: {message}. Use --help para consultar os comandos.")


def _bbox_argument(text: str):
    if not re.fullmatch(r"-?\d+,-?\d+,\d+,\d+", text):
        raise argparse.ArgumentTypeError("o bbox deve usar x,y,largura,altura com inteiros, sem espaços")
    return tuple(int(part) for part in text.split(","))


def _point_argument(text: str):
    if not re.fullmatch(r"-?\d+,-?\d+", text):
        raise argparse.ArgumentTypeError("o ponto deve usar X,Y com dois inteiros, sem espaços")
    return tuple(int(part) for part in text.split(","))


def main(argv=None) -> int:
    """CLI: JSON UTF-8 no sucesso; erro JSON em stderr e código 2."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    analyze_parser = commands.add_parser("analyze", help="Analise um componente e grave uma pasta nova de resultados.")
    analyze_parser.add_argument("--image", required=True)
    analyze_parser.add_argument("--bbox", required=True, type=_bbox_argument, help="x,y,largura,altura em px_imagem.")
    analyze_parser.add_argument("--output-dir", required=True, help="Pasta NOVA; não é reutilizada.")
    analyze_parser.add_argument("--seed", type=_point_argument, help="X,Y no original; padrão: centro do bbox.")
    analyze_parser.add_argument("--fill-tolerance", type=int, default=24, help="Tolerância de cor 0–255 (máximo entre canais).")
    analyze_parser.add_argument("--margin", type=int, default=10, help="Contexto ao redor do bbox, em px.")
    analyze_parser.add_argument("--exclude-json", help="JSON de caixas (formato de image_tools) de áreas ocultas a ignorar.")
    analyze_parser.add_argument("--element-id", default="E01")
    analyze_parser.add_argument("--scale", type=float, help="Escala em px_imagem por CSS px, informada (hipótese, não medida).")
    analyze_parser.add_argument('--detect-markup', action='store_true', help='Heurística opt-in de cores de marcação; pode confundir UI saturada. Prefira exclusões explícitas.')
    analyze_parser.add_argument('--tolerance',type=float,default=0.6,help='Erro do ajuste em px; de 0.05 a 5.')
    analyze_parser.add_argument('--max-iterations',type=int,default=30,help='Orçamento por candidato, de 1 a 200.')
    analyze_parser.add_argument('--loss-weights',help='Objeto JSON: contour, color, thickness, regularization.')
    analyze_parser.add_argument("--keep-markup", action="store_true", help="Compatibilidade: mantém pixels saturados (já é o padrão).")
    revise_parser = commands.add_parser("revise", help="Aplique correções a um element.json e grave uma revisão nova.")
    revise_parser.add_argument("--model", required=True, help="element.json de uma análise anterior.")
    revise_parser.add_argument("--overrides", required=True, help="JSON com colors, offsets_px, glow, base_vertices ou base_path.")
    revise_parser.add_argument("--image", required=True, help="Mesma captura da análise; o SHA-256 é verificado.")
    revise_parser.add_argument("--output-dir", required=True, help="Pasta NOVA da revisão.")
    open_parser=commands.add_parser('trace-open',help='Extraia uma borda aberta Canny entre duas âncoras observadas.')
    open_parser.add_argument('--image',required=True)
    open_parser.add_argument('--bbox',required=True,type=_bbox_argument)
    open_parser.add_argument('--start',required=True,type=_point_argument)
    open_parser.add_argument('--end',required=True,type=_point_argument)
    open_parser.add_argument('--output-dir',required=True)
    open_parser.add_argument('--element-id',default='E01')
    open_parser.add_argument('--stroke-width',type=float,default=1.)
    open_parser.add_argument('--tolerance',type=float,default=0.6)
    try:
        arguments = parser.parse_args(argv)
        if arguments.command == "analyze":
            exclusions = ()
            if arguments.exclude_json:
                _require_numpy()
                with image_tools.Image.open(arguments.image) as probe:
                    size = probe.size
                try:
                    exclusions = image_tools._load_boxes(_path(arguments.exclude_json), size)
                except image_tools.ImageToolError as exc:
                    raise ContourToolError(str(exc)) from exc
            result = analyze_element(
                arguments.image, arguments.bbox, arguments.output_dir,
                seed=arguments.seed, fill_tolerance=arguments.fill_tolerance, margin=arguments.margin,
                exclusions=exclusions, element_id=arguments.element_id, scale=arguments.scale,
                markup_filter=arguments.detect_markup and not arguments.keep_markup,
                tolerance=arguments.tolerance,max_iterations=arguments.max_iterations,
                loss_weights=json.loads(arguments.loss_weights) if arguments.loss_weights else None,
            )
        elif arguments.command=='trace-open':
            result=trace_open_element(arguments.image,arguments.bbox,arguments.output_dir,start=arguments.start,end=arguments.end,
                                      element_id=arguments.element_id,stroke_width=arguments.stroke_width,tolerance=arguments.tolerance)
        else:
            result = revise_element(arguments.model, arguments.overrides, arguments.output_dir, image_path=arguments.image)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ContourToolError, image_tools.ImageToolError, ValueError, OSError, KeyError, TypeError) as exc:
        # GeometryError herda de ValueError; ambos são falhas de entrada ou de dados.
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
