#!/usr/bin/env python3
"""Collect Android visual evidence through ADB without changing settings.

Python 3.10+, standard library only. A bounds label does not verify that
Android's layout-bounds diagnostic is enabled. See references/adb-tool.md.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
import zlib


class CaptureError(RuntimeError):
    """An acquisition failed with an action the operator can take."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _ADB:
    def __init__(self, executable: str, serial: str, timeout: float):
        self.executable = executable
        self.serial = serial
        self.timeout = timeout
        self.commands: list[dict] = []

    def run(self, arguments: list[str], step: str, *, discovery: bool = False) -> bytes:
        scope = [] if discovery else ["-s", self.serial]
        # Record the logical command, not the executable's private local path,
        # environment, full device inventory, or arbitrary command output.
        record = {"argv": ["adb", *scope, *arguments], "started_at": _timestamp()}
        self.commands.append(record)
        try:
            result = subprocess.run(
                [self.executable, *scope, *arguments],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                check=False,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as error:
            record.update(status="timeout", completed_at=_timestamp())
            raise CaptureError(
                f"Tempo limite durante {step}. Verifique a conexão e o estado do aparelho; "
                "tente novamente em outro diretório ou aumente --timeout."
            ) from error
        except FileNotFoundError as error:
            record.update(status="unavailable", completed_at=_timestamp())
            raise CaptureError(
                "ADB não encontrado. Instale Android Platform Tools ou informe o executável com --adb."
            ) from error
        except OSError as error:
            record.update(status="unavailable", completed_at=_timestamp())
            raise CaptureError(
                f"Não foi possível executar ADB durante {step}. Confira o caminho --adb e as permissões."
            ) from error
        record.update(returncode=result.returncode, completed_at=_timestamp())
        if result.returncode != 0:
            record["status"] = "failed"
            raise CaptureError(
                f"ADB falhou durante {step} (código {result.returncode}). "
                "Verifique a conexão, a autorização e o suporte ao comando no aparelho."
            )
        record["status"] = "ok"
        return result.stdout


def _select_device(adb: _ADB) -> None:
    inventory = adb.run(["devices", "-l"], "listagem dos dispositivos", discovery=True)
    matches = []
    for line in inventory.decode("utf-8", errors="replace").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == adb.serial:
            matches.append(fields[1])
    if not matches:
        raise CaptureError(
            "O serial exato não aparece em adb devices -l. Confira o serial, o cabo e a Depuração USB."
        )
    if len(matches) != 1:
        raise CaptureError(
            "O serial aparece mais de uma vez na listagem. Resolva a identificação ambígua antes da coleta."
        )
    state = matches[0]
    if state != "device":
        action = (
            "Desbloqueie o aparelho e aceite nele a autorização de Depuração USB."
            if state == "unauthorized" else
            "Reconecte o aparelho e confira a Depuração USB até o estado mudar para device."
        )
        # Device states are a small known vocabulary; do not copy arbitrary
        # inventory data into the error or metadata.
        state_name = state if state in {"unauthorized", "offline", "recovery", "sideload", "bootloader"} else "não pronto"
        raise CaptureError(f"O aparelho está em estado {state_name}. {action}")


def validate_png(data: bytes) -> tuple[int, int]:
    """Validate PNG signature, IHDR dimensions, chunk framing/CRCs and IEND.

    This is structural validation, not a visual/protected-surface detector or
    a full pixel decoder. No shell or text conversion touches screenshot bytes.
    """
    def invalid(reason: str) -> CaptureError:
        return CaptureError(f"PNG inválido: {reason}. Confira a tela e repita a captura em outro diretório.")

    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise invalid("assinatura ausente")
    offset = 8
    dimensions = None
    seen_idat = False
    while offset < len(data):
        if len(data) - offset < 12:
            raise invalid("chunk truncado")
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise invalid("dados truncados")
        content = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        if zlib.crc32(kind + content) & 0xFFFFFFFF != expected_crc:
            raise invalid("CRC incorreto")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                raise invalid("cabeçalho IHDR ausente")
            width, height, depth, color, compression, filter_method, interlace = struct.unpack(">IIBBBBB", content)
            allowed_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if not (0 < width < 2**31 and 0 < height < 2**31):
                raise invalid("dimensões não positivas ou fora do formato")
            if (depth not in allowed_depths.get(color, set()) or compression != 0
                    or filter_method != 0 or interlace not in (0, 1)):
                raise invalid("formato IHDR não suportado pelo PNG")
            dimensions = (width, height)
        elif kind == b"IHDR":
            raise invalid("IHDR duplicado")
        if kind == b"IDAT" and length:
            seen_idat = True
        if kind == b"IEND":
            if length != 0 or not seen_idat or end != len(data):
                raise invalid("final ou dados da imagem inconsistentes")
            return dimensions
        offset = end
    raise invalid("IEND ausente")


def _calibration(adb: _ADB) -> dict:
    size_raw = adb.run(["shell", "wm", "size"], "leitura da resolução").decode("utf-8", errors="replace")
    density_raw = adb.run(["shell", "wm", "density"], "leitura da densidade").decode("utf-8", errors="replace")
    font_raw = adb.run(
        ["shell", "settings", "get", "system", "font_scale"], "leitura da escala de fonte"
    ).decode("utf-8", errors="replace").strip()
    # Store only known calibration values instead of arbitrary device output.
    size: dict = {}
    for key, prefix in (("physical_px", "Physical"), ("override_px", "Override")):
        match = re.search(rf"(?m)^\s*{prefix} size:\s*(\d+)x(\d+)\s*$", size_raw)
        if match:
            values = [int(match.group(1)), int(match.group(2))]
            if min(values) > 0:
                size[key] = values
    density: dict = {}
    for key, prefix in (("physical_dpi", "Physical"), ("override_dpi", "Override")):
        match = re.search(rf"(?m)^\s*{prefix} density:\s*(\d+)\s*$", density_raw)
        if match and int(match.group(1)) > 0:
            density[key] = int(match.group(1))
    size["effective_px"] = size.get("override_px", size.get("physical_px"))
    density["effective_dpi"] = density.get("override_dpi", density.get("physical_dpi"))
    try:
        font_scale = float(font_raw)
    except ValueError as error:
        raise CaptureError(
            "Escala de fonte não disponível. Confira manualmente a configuração do aparelho e repita a coleta."
        ) from error
    if (size["effective_px"] is None or density["effective_dpi"] is None
            or not math.isfinite(font_scale) or font_scale <= 0):
        raise CaptureError(
            "Calibração de resolução, densidade ou fonte inválida. "
            "Verifique wm size, wm density e a escala de fonte no aparelho antes de repetir."
        )
    return {"size": size, "density": density, "font_scale": font_scale}


def _hierarchy(adb: _ADB, output_dir: Path, session_id: str, warnings: list[str]) -> dict:
    remote = f"/sdcard/xray-{session_id}.xml"
    local_temp = output_dir / f"xray-{session_id}.xml"
    result = {"status": "unavailable", "cleanup": "pending", "remote_temporary_path": remote}
    try:
        adb.run(["shell", "uiautomator", "dump", remote], "dump complementar da hierarquia")
        adb.run(["pull", remote, str(local_temp)], "cópia da hierarquia")
        if local_temp.stat().st_size > 32 * 1024 * 1024:
            raise CaptureError("XML de hierarquia excede 32 MiB. Repita em uma tela mais simples ou use --skip-hierarchy.")
        raw = local_temp.read_bytes()
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise CaptureError("XML de hierarquia contém declarações não aceitas. Revise a tela ou use --skip-hierarchy.")
        root = ET.fromstring(raw)
        if root.tag != "hierarchy":
            raise CaptureError("XML não contém uma raiz hierarchy. Confira o suporte ao UI Automator neste aparelho.")
        # Exclusive creation, even inside this new session directory.
        with (output_dir / "hierarchy.xml").open("xb") as stream:
            stream.write(raw)
        result.update(status="available", file="hierarchy.xml", captured_at=_timestamp(), sha256=hashlib.sha256(raw).hexdigest())
    except (CaptureError, OSError, ET.ParseError) as error:
        if isinstance(error, CaptureError):
            message = str(error)
        else:
            message = "Não foi possível ler ou validar o XML. Confira o suporte ao UI Automator neste aparelho."
        warnings.append(f"Hierarquia indisponível: {message} A captura PNG continua válida.")
    finally:
        # This literal session path is the sole remote cleanup target. Never
        # enumerate /sdcard, use globs, reset settings, or remove user inputs.
        try:
            adb.run(["shell", "rm", "-f", remote], "remoção do XML temporário desta sessão")
            result["cleanup"] = "removed"
        except CaptureError:
            result["cleanup"] = "failed"
            warnings.append(
                f"Não foi possível remover o temporário {remote}. Remova somente esse arquivo "
                "quando a conexão voltar; nenhuma configuração foi alterada."
            )
        try:
            local_temp.unlink(missing_ok=True)
        except OSError:
            warnings.append(f"Não foi possível remover o XML temporário local {local_temp.name}.")
    return result


def capture(*, serial: str, output_dir: str | Path, label: str, adb: str = "adb",
            skip_hierarchy: bool = False, timeout: float = 30.0) -> dict:
    """Collect one state into a new directory; never overwrite existing input."""
    if not serial or any(character.isspace() or ord(character) < 32 for character in serial):
        raise CaptureError("Informe um serial exato e sem espaços, obtido por adb devices -l.")
    if label not in {"clean", "bounds"}:
        raise CaptureError("O rótulo deve ser clean ou bounds.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise CaptureError("--timeout deve ser um número finito maior que zero, em segundos.")
    destination = Path(output_dir).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise CaptureError("O diretório de saída já existe. Escolha um novo diretório para preservar os dados existentes.")
    client = _ADB(adb, serial, timeout)
    started_at = _timestamp()
    session_id = str(uuid.uuid4())
    _select_device(client)
    calibration = _calibration(client)
    try:
        destination.mkdir(exist_ok=False)
    except FileExistsError as error:
        raise CaptureError("O diretório de saída já existe. Escolha um novo diretório.") from error
    except OSError as error:
        raise CaptureError("Não foi possível criar a saída. Crie a pasta pai e confira as permissões; use um novo diretório.") from error
    try:
        raw_png = client.run(["exec-out", "screencap", "-p"], "captura PNG")
        captured_at = _timestamp()
        width, height = validate_png(raw_png)
        filename = f"{label}.png"
        with (destination / filename).open("xb") as stream:
            stream.write(raw_png)
        warnings: list[str] = []
        effective_size = calibration["size"]["effective_px"]
        if [width, height] != effective_size:
            warnings.append(
                "Dimensões do PNG diferem de wm size: confira rotação, display, insets e equivalência do estado antes de medir."
            )
        hierarchy = ({"status": "skipped", "cleanup": "not_needed"} if skip_hierarchy else
                     _hierarchy(client, destination, session_id, warnings))
        status = "partial" if (hierarchy["status"] == "unavailable" or hierarchy["cleanup"] == "failed") else "complete"
        metadata = {
            "schema_version": "1.0",
            "session_id": session_id,
            "serial": serial,
            "label": label,
            "status": status,
            "started_at": started_at,
            "completed_at": _timestamp(),
            "calibration": calibration,
            "screenshot": {
                "file": filename, "format": "PNG", "width": width, "height": height,
                "captured_at": captured_at, "sha256": hashlib.sha256(raw_png).hexdigest(),
                "validation": "signature_ihdr_dimensions_chunk_crc_iend",
            },
            "hierarchy": hierarchy,
            "diagnostics": {"layout_bounds": {
                "verified": False, "label_only": True,
                "note": "clean/bounds são rótulos fornecidos pelo operador; o estado de Mostrar limites de layout não foi verificado.",
            }},
            "configuration_changes": [],
            "restoration": {"required": False, "note": "O utilitário não altera configurações; alterações manuais exigem registro e restauração pelo operador."},
            "provenance": {"tool": "interface-xray adb_capture", "transport": "adb", "commands": client.commands},
            "warnings": warnings,
        }
        with (destination / "capture.json").open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(metadata, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        return metadata
    except OSError as error:
        raise CaptureError(
            "Falha ao salvar a coleta. Confira espaço e permissões. Preserve os arquivos já criados e tente outro diretório."
        ) from error


def main(argv: list[str] | None = None) -> int:
    # Windows redirected streams may default to a legacy code page. Keep the
    # caller's streams open and use UTF-8 for paths, help, warnings and errors.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Coleta PNG, calibração e hierarquia Android sem alterar configurações.")
    parser.add_argument("--serial", required=True, help="Serial exato de adb devices -l em estado device")
    parser.add_argument("--output-dir", required=True, help="Novo diretório; a pasta pai deve existir")
    parser.add_argument("--label", required=True, choices=("clean", "bounds"), help="Rótulo; não verifica diagnóstico")
    parser.add_argument("--adb", default="adb", help="Executável ADB ou caminho completo")
    parser.add_argument("--skip-hierarchy", action="store_true", help="Coletar apenas PNG e calibração")
    parser.add_argument("--timeout", type=float, default=30.0, help="Limite de cada comando em segundos (padrão: 30)")
    options = parser.parse_args(argv)
    try:
        metadata = capture(serial=options.serial, output_dir=options.output_dir, label=options.label,
                           adb=options.adb, skip_hierarchy=options.skip_hierarchy, timeout=options.timeout)
    except CaptureError as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 1
    print(str(Path(options.output_dir).expanduser().absolute() / "capture.json"))
    for warning in metadata["warnings"]:
        print(f"Aviso: {warning}", file=sys.stderr)
    if metadata["status"] == "partial":
        print("Coleta parcial: PNG preservado; consulte os avisos em capture.json.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
