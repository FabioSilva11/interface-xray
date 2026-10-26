"""Isolated behavioral tests for skill validation and release packaging."""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    validator = importlib.import_module("tools.validate_package")
except ModuleNotFoundError as exc:
    if exc.name not in {"tools", "tools.validate_package"}:
        raise
    validator = None

try:
    builder = importlib.import_module("tools.build_release")
except ModuleNotFoundError as exc:
    if exc.name not in {"tools", "tools.build_release"}:
        raise
    builder = None


class PackageFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix=".package-test-", dir=REPO_ROOT)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.skill = self.root / "interface-xray"
        (self.skill / "references").mkdir(parents=True)
        (self.skill / "scripts").mkdir()
        self.write("SKILL.md", self.manifest() + "\nRead [guide](references/guide.md).\n")
        self.write("references/guide.md", "# Guide\n\n```python\nprint('example')\n```\n")
        self.write("scripts/example.py", "raise RuntimeError('validation must never execute this')\n")
        self.write("requirements.txt", "Pillow>=10,<13\n")
        self.write("MANUAL.md", "# Portable manual\n")

    @staticmethod
    def manifest(name: str = "interface-xray", description: str = "A portable interface analysis skill.") -> str:
        return f"---\nname: {name}\ndescription: {description}\n---\n"

    def write(self, relative: str, contents: str) -> Path:
        path = self.skill / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8", newline="\n")
        return path

    def validate(self) -> list[str]:
        self.assertIsNotNone(validator, "tools.validate_package has not been implemented")
        return validator.validate_package(self.root)

    def build(self, output_dir: Path | None = None, version: str = "1.2.3") -> tuple[Path, Path]:
        self.assertIsNotNone(builder, "tools.build_release has not been implemented")
        return builder.build_release(self.root, version, output_dir or self.root / "dist")

    @contextmanager
    def cp1252_streams(self):
        stdout_bytes = io.BytesIO()
        stderr_bytes = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", newline="\n", write_through=True)
        stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", newline="\n", write_through=True)
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                yield stdout, stderr, stdout_bytes, stderr_bytes
        finally:
            stdout.close()
            stderr.close()


class ValidationTests(PackageFixture):
    def test_valid_package_is_checked_without_executing_scripts(self) -> None:
        self.assertEqual([], self.validate())

    def test_rejects_invalid_yaml(self) -> None:
        self.write("SKILL.md", "---\nname: [unterminated\n---\n")
        self.assertTrue(any("yaml" in error.lower() for error in self.validate()))

    def test_rejects_non_mapping_or_missing_manifest(self) -> None:
        for content in ("# No frontmatter\n", "---\n- name\n---\n"):
            with self.subTest(content=content):
                self.write("SKILL.md", content)
                self.assertTrue(self.validate())

    def test_enforces_name_description_and_directory(self) -> None:
        for manifest in (
            self.manifest(name="another-skill"),
            self.manifest(description="''"),
            self.manifest(description="x" * 1025),
            "---\nname: interface-xray\ndescription: [a, list]\n---\n",
        ):
            with self.subTest(manifest=manifest[:80]):
                self.write("SKILL.md", manifest)
                self.assertTrue(self.validate())
        self.skill.rename(self.root / "different-name")
        self.assertTrue(self.validate())

    def test_rejects_broken_local_markdown_links(self) -> None:
        self.write("references/guide.md", "See [missing](missing.md#part).\n")
        errors = self.validate()
        self.assertTrue(any("missing.md" in error for error in errors), errors)

    def test_checks_reference_links_and_percent_encoded_filenames(self) -> None:
        self.write("references/space guide.md", "# Details\n")
        self.write("references/guide.md", "[details][ref]\n\n[ref]: <space%20guide.md#details>\n")
        self.assertEqual([], self.validate())
        (self.skill / "references/space guide.md").unlink()
        self.assertTrue(any("space" in error for error in self.validate()))

    def test_ignores_remote_links_anchors_and_code_examples(self) -> None:
        self.write(
            "references/guide.md",
            "[remote](https://example.com/unavailable.md) [anchor](#part)\n"
            "~~~markdown\n[example](nonexistent-example.md)\n```\n~~~\n",
        )
        self.assertEqual([], self.validate())

    def test_rejects_reference_outside_distributed_skill(self) -> None:
        (self.root / "outside.md").write_text("# Outside\n", encoding="utf-8")
        self.write("references/guide.md", "[outside](../../outside.md)\n")
        self.assertTrue(self.validate())

    def test_rejects_python_syntax_error(self) -> None:
        self.write("scripts/example.py", "def broken(:\n")
        errors = self.validate()
        self.assertTrue(any("example.py" in error and "syntax" in error.lower() for error in errors), errors)

    def test_rejects_unclosed_fence_in_any_markdown(self) -> None:
        for fence in ("```python\nprint(1)\n", "~~~~\ntext\n~~~\n"):
            with self.subTest(fence=fence):
                self.write("references/guide.md", fence)
                errors = self.validate()
                self.assertTrue(any("fence" in error.lower() for error in errors), errors)

    def test_validator_cli_returns_failure_for_invalid_fixture(self) -> None:
        self.write("scripts/example.py", "def broken(:\n")
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools/validate_package.py"), "--root", str(self.root)],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("example.py", result.stdout + result.stderr)

    def test_validator_main_reports_unicode_errors_with_legacy_windows_streams(self) -> None:
        self.assertIsNotNone(validator)
        self.write("references/guide.md", "[missing](確認.md)\n")
        with self.cp1252_streams() as (stdout, stderr, _, stderr_bytes):
            try:
                result = validator.main(["--root", str(self.root)])
            except UnicodeEncodeError:
                self.fail("Validator main could not emit a Unicode diagnostic through a cp1252 stream")
            self.assertEqual(1, result)
            self.assertFalse(stdout.closed)
            self.assertFalse(stderr.closed)
            self.assertIn("確認.md", stderr_bytes.getvalue().decode("utf-8"))
            stdout.write("Caller retains the stream: 確認\n")


class ReleaseTests(PackageFixture):
    def test_zip_contains_only_distributed_skill_files_and_real_checksum(self) -> None:
        self.write("__pycache__/cached.pyc", "cache")
        self.write("scripts/__pycache__/ignored.py", "raise SyntaxError\n")
        self.write("references/output/generated.md", "# Generated output\n")
        self.write("scripts/capture.png", "image output")
        self.write("unrelated.txt", "not distributed")
        (self.root / "GUIA.md").write_text("Full repository manual\n", encoding="utf-8")
        archive, checksum = self.build()
        self.assertEqual("interface-xray-1.2.3.zip", archive.name)
        self.assertEqual("SHA256SUMS", checksum.name)
        with zipfile.ZipFile(archive) as release:
            self.assertEqual(
                [
                    "interface-xray/MANUAL.md",
                    "interface-xray/SKILL.md",
                    "interface-xray/references/guide.md",
                    "interface-xray/requirements.txt",
                    "interface-xray/scripts/example.py",
                ],
                release.namelist(),
            )
            self.assertEqual(b"Pillow>=10,<13\n", release.read("interface-xray/requirements.txt"))
        actual_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        self.assertEqual(f"{actual_digest}  {archive.name}\n", checksum.read_text(encoding="utf-8"))

    def test_release_is_reproducible_despite_source_metadata(self) -> None:
        first, _ = self.build(self.root / "first")
        os.utime(self.skill / "SKILL.md", (1_500_000_000, 1_500_000_000))
        second, _ = self.build(self.root / "second")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_release_excludes_file_and_directory_symlinks(self) -> None:
        outside = self.root / "outside.py"
        outside.write_text("secret = 'outside'\n", encoding="utf-8")
        outside_dir = self.root / "outside-references"
        outside_dir.mkdir()
        (outside_dir / "secret.md").write_text("secret\n", encoding="utf-8")
        try:
            (self.skill / "scripts/linked.py").symlink_to(outside)
            (self.skill / "references/linked").symlink_to(outside_dir, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"OS does not permit creating symlinks: {exc}")
        archive, _ = self.build()
        with zipfile.ZipFile(archive) as release:
            self.assertFalse(any("linked" in name for name in release.namelist()))

    def test_invalid_package_creates_no_release(self) -> None:
        self.write("SKILL.md", self.manifest() + "[broken](missing.md)\n")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "dist").exists())

    def test_refuses_existing_archive_without_modifying_it(self) -> None:
        destination = self.root / "dist"
        destination.mkdir()
        original = destination / "interface-xray-1.2.3.zip"
        original.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            self.build(destination)
        self.assertEqual(b"existing archive", original.read_bytes())
        self.assertFalse((destination / "SHA256SUMS").exists())

    def test_refuses_existing_checksum_without_creating_zip(self) -> None:
        destination = self.root / "dist"
        destination.mkdir()
        original = destination / "SHA256SUMS"
        original.write_text("existing checksum\n", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.build(destination)
        self.assertEqual("existing checksum\n", original.read_text(encoding="utf-8"))
        self.assertFalse((destination / "interface-xray-1.2.3.zip").exists())

    def test_refuses_destination_inside_skill(self) -> None:
        for destination in (self.skill, self.skill / "dist", self.skill / "nested/deep"):
            with self.subTest(destination=destination):
                with self.assertRaises(ValueError):
                    self.build(destination)
        self.assertFalse((self.skill / "dist").exists())

    def test_rejects_versions_that_could_escape_output_directory(self) -> None:
        for version in ("../1.2.3", "1.2", "v1.2.3", "1.2.3-beta", "1.2.3/other"):
            with self.subTest(version=version):
                with self.assertRaises(ValueError):
                    self.build(version=version)
        self.assertFalse((self.root / "dist").exists())

    def test_builder_cli_accepts_explicit_root_output_and_version(self) -> None:
        destination = self.root / "cli-release"
        result = subprocess.run(
            [
                sys.executable, str(REPO_ROOT / "tools/build_release.py"),
                "--root", str(self.root), "--version", "2.0.1", "--output-dir", str(destination),
            ],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((destination / "interface-xray-2.0.1.zip").is_file())
        self.assertTrue((destination / "SHA256SUMS").is_file())

    def test_builder_main_prints_unicode_paths_with_legacy_windows_streams(self) -> None:
        self.assertIsNotNone(builder)
        destination = self.root / "確認"
        with self.cp1252_streams() as (stdout, stderr, stdout_bytes, _):
            try:
                result = builder.main([
                    "--root", str(self.root), "--version", "1.2.3", "--output-dir", str(destination),
                ])
            except UnicodeEncodeError:
                self.fail("Builder main could not print the Unicode release path through a cp1252 stream")
            self.assertEqual(0, result)
            self.assertFalse(stdout.closed)
            self.assertFalse(stderr.closed)
            self.assertIn(str(destination), stdout_bytes.getvalue().decode("utf-8"))
            stderr.write("Caller retains the stream: 確認\n")
        self.assertTrue((destination / "interface-xray-1.2.3.zip").is_file())
        self.assertTrue((destination / "SHA256SUMS").is_file())

    def test_builder_main_reports_unicode_collision_with_legacy_windows_streams(self) -> None:
        self.assertIsNotNone(builder)
        destination = self.root / "確認"
        destination.mkdir()
        original = destination / "interface-xray-1.2.3.zip"
        original.write_bytes(b"existing archive")
        with self.cp1252_streams() as (stdout, stderr, _, stderr_bytes):
            try:
                result = builder.main([
                    "--root", str(self.root), "--version", "1.2.3", "--output-dir", str(destination),
                ])
            except UnicodeEncodeError:
                self.fail("Builder main could not emit a Unicode error through a cp1252 stream")
            self.assertEqual(1, result)
            self.assertFalse(stdout.closed)
            self.assertFalse(stderr.closed)
            self.assertIn(str(destination), stderr_bytes.getvalue().decode("utf-8"))
        self.assertEqual(b"existing archive", original.read_bytes())
        self.assertFalse((destination / "SHA256SUMS").exists())


if __name__ == "__main__":
    unittest.main()
