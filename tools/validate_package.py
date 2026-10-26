"""Validate the portable skill without importing or executing its scripts."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote, urlsplit

import yaml


SKILL_NAME = "interface-xray"
DEFAULT_ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {
    "__pycache__", ".git", ".agents", ".codex", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".venv", "venv", "build", "dist",
    "output", "outputs", "capture", "captures",
}
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
INLINE_LINK = re.compile(
    r"!?\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<bare>(?:\\.|[^\s\\)])+))"
    r"(?:\s+[^)\n]*)?\)"
)
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*(?:<([^>\n]+)>|(\S+))", re.MULTILINE)


def _is_link(path: Path) -> bool:
    """Also exclude Windows junctions/reparse points on Python 3.10."""
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _skill_files(skill: Path) -> list[Path]:
    files: list[Path] = []
    for directory, subdirectories, filenames in os.walk(skill, followlinks=False):
        base = Path(directory)
        subdirectories[:] = sorted(
            name for name in subdirectories
            if name.lower() not in IGNORED_DIRECTORIES
            and not name.startswith(".")
            and not _is_link(base / name)
        )
        for name in sorted(filenames):
            path = base / name
            if not name.startswith(".") and path.is_file() and not _is_link(path):
                files.append(path)
    return sorted(files, key=lambda path: path.relative_to(skill).as_posix())


def distributable_files(skill: Path) -> list[Path]:
    """Return the explicit release allowlist; generated assets stay outside it."""
    result: list[Path] = []
    for path in _skill_files(skill):
        relative = path.relative_to(skill)
        if relative.as_posix() in {"SKILL.md", "MANUAL.md", "requirements.txt", "requirements-contour.txt"}:
            result.append(path)
        elif len(relative.parts) > 1 and (
            relative.parts[0] == "references" and path.suffix.lower() == ".md"
            or relative.parts[0] == "scripts" and path.suffix.lower() == ".py"
        ):
            result.append(path)
    return result


def _manifest_errors(contents: str) -> list[str]:
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        return ["SKILL.md: YAML frontmatter must start with ---."]
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end is None:
        return ["SKILL.md: YAML frontmatter is not closed with ---. "]
    try:
        manifest = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        return [f"SKILL.md: invalid YAML frontmatter: {exc}"]
    if not isinstance(manifest, dict):
        return ["SKILL.md: YAML frontmatter must be a mapping."]
    errors: list[str] = []
    if manifest.get("name") != SKILL_NAME:
        errors.append(f"SKILL.md: name must be {SKILL_NAME!r}, matching the skill directory.")
    description = manifest.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        errors.append("SKILL.md: description must be a nonempty string with at most 1024 characters.")
    return errors


def _markdown_prose(contents: str, label: str) -> tuple[str, list[str]]:
    """Remove fenced examples while checking matching marker and minimum length."""
    prose: list[str] = []
    opened: tuple[str, int, int] | None = None
    for number, line in enumerate(contents.splitlines(), start=1):
        match = FENCE.match(line)
        if opened is None:
            if match and not (match[1][0] == "`" and "`" in match[2]):
                opened = (match[1][0], len(match[1]), number)
                prose.append("")
            else:
                prose.append(line)
        else:
            if match and match[1][0] == opened[0] and len(match[1]) >= opened[1] and not match[2].strip():
                opened = None
            prose.append("")
    errors = [] if opened is None else [f"{label}:{opened[2]}: unclosed Markdown fence."]
    return "\n".join(prose), errors


def _markdown_targets(prose: str) -> list[str]:
    targets = [match["angle"] or match["bare"] for match in INLINE_LINK.finditer(prose)]
    targets.extend(match[1] or match[2] for match in REFERENCE_LINK.finditer(prose))
    return targets


def validate_package(root: str | Path) -> list[str]:
    """Return integrity errors for ``root/interface-xray`` without running apps."""
    root = Path(root).resolve()
    skill = root / SKILL_NAME
    if not skill.is_dir() or _is_link(skill):
        return [f"Expected a real {SKILL_NAME}/ directory under {root}."]
    manifest_path = skill / "SKILL.md"
    if not manifest_path.is_file() or _is_link(manifest_path):
        return ["interface-xray/SKILL.md is missing or is a symbolic link."]
    errors: list[str] = []
    try:
        contents = manifest_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return [f"SKILL.md: could not read UTF-8 text: {exc}"]
    errors.extend(_manifest_errors(contents))
    try:
        files = _skill_files(skill)
        distributed = {path.resolve() for path in distributable_files(skill)}
        for path in files:
            label = path.relative_to(skill).as_posix()
            if path.suffix.lower() == ".py":
                try:
                    ast.parse(path.read_bytes(), filename=label)
                except (SyntaxError, ValueError) as exc:
                    errors.append(f"{label}: Python syntax error: {exc}")
                except OSError as exc:
                    errors.append(f"{label}: could not read Python source: {exc}")
            elif path.suffix.lower() == ".md":
                try:
                    markdown = path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError) as exc:
                    errors.append(f"{label}: could not read UTF-8 Markdown: {exc}")
                    continue
                prose, fence_errors = _markdown_prose(markdown, label)
                errors.extend(fence_errors)
                for target in _markdown_targets(prose):
                    try:
                        parsed = urlsplit(target)
                    except ValueError:
                        errors.append(f"{label}: invalid Markdown reference {target!r}.")
                        continue
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue
                    decoded = unquote(parsed.path)
                    if Path(decoded).suffix.lower() != ".md":
                        continue
                    destination = (path.parent / decoded).resolve()
                    if not destination.is_relative_to(skill):
                        errors.append(f"{label}: Markdown reference escapes the skill: {target!r}.")
                    elif not destination.is_file() or destination not in distributed:
                        errors.append(f"{label}: missing or undistributed Markdown reference {target!r}.")
    except OSError as exc:
        errors.append(f"Could not inspect the skill files: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Repository root containing interface-xray/.")
    args = parser.parse_args(argv)
    errors = validate_package(args.root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Package validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
