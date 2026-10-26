"""Build a validated, deterministic portable skill ZIP and SHA256SUMS."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import sys
import zipfile

if __package__:
    from .validate_package import DEFAULT_ROOT, SKILL_NAME, distributable_files, validate_package
else:
    from validate_package import DEFAULT_ROOT, SKILL_NAME, distributable_files, validate_package


VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
FIXED_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def build_release(root: str | Path, version: str, output_dir: str | Path = "dist") -> tuple[Path, Path]:
    """Validate first, then exclusively create a ZIP and its real SHA-256 file.

    Relative output directories are interpreted from the repository root.
    Raises ValueError for invalid input/package and FileExistsError on collision.
    """
    if not VERSION.fullmatch(version):
        raise ValueError("Version must use X.Y.Z with nonnegative integer components and no leading zeroes.")
    root = Path(root).resolve()
    skill = root / SKILL_NAME
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = root / destination
    destination = destination.resolve()
    if destination.is_relative_to(skill.resolve()):
        raise ValueError("The output directory must be outside the skill directory.")
    errors = validate_package(root)
    if errors:
        raise ValueError("Package validation failed:\n" + "\n".join(errors))
    archive_path = destination / f"{SKILL_NAME}-{version}.zip"
    checksum_path = destination / "SHA256SUMS"
    for path in (archive_path, checksum_path):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to overwrite existing release output: {path}")
    files = distributable_files(skill)
    destination.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    try:
        with archive_path.open("xb") as stream:
            created.append(archive_path)
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for path in files:
                    relative = path.relative_to(skill).as_posix()
                    entry = zipfile.ZipInfo(f"{SKILL_NAME}/{relative}", FIXED_ZIP_DATE)
                    entry.create_system = 3
                    entry.external_attr = 0o100644 << 16
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(entry, path.read_bytes(), compresslevel=9)
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        with checksum_path.open("x", encoding="utf-8", newline="\n") as stream:
            created.append(checksum_path)
            stream.write(f"{digest}  {archive_path.name}\n")
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return archive_path, checksum_path


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version in X.Y.Z form.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Repository root containing interface-xray/.")
    parser.add_argument("--output-dir", type=Path, default=Path("dist"), help="Output directory, relative to --root unless absolute.")
    args = parser.parse_args(argv)
    try:
        archive, checksum = build_release(args.root, args.version, args.output_dir)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Created {archive}")
    print(f"Created {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
