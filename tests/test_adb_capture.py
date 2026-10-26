"""Offline contract tests: only the external ADB subprocess is replaced."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock
import zlib


SCRIPT = Path(__file__).resolve().parents[1] / "interface-xray/scripts/adb_capture.py"


def png_bytes(width=2, height=3):
    """Construct a small real PNG, independent of the capture validator."""
    def chunk(kind, content):
        return (struct.pack(">I", len(content)) + kind + content
                + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = b"\x00\xff\x00\x00\xff" * height if width == 1 else (
        b"\x00" + b"\xff\x00\x00\xff" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b""))


class FakeADB:
    """Model ADB's bytes interface, file pull, and restricted remote cleanup."""

    def __init__(self, devices=None, screenshot=None, hierarchy_failure=None):
        self.devices = devices or (
            b"List of devices attached\r\n"
            b"PIXEL-12 device product:a model:Pixel transport_id:1\r\n"
            b"PIXEL-1 device product:b model:Pixel transport_id:2\r\n\r\n")
        self.screenshot = png_bytes() if screenshot is None else screenshot
        self.hierarchy_failure = hierarchy_failure
        self.calls = []
        self.remote_files = {"/sdcard/keep.xml": b"original"}
        self.created_remote = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if kwargs.get("shell") is not False:
            raise AssertionError("ADB must use an argv list with shell=False")
        if kwargs.get("text") or kwargs.get("encoding"):
            raise AssertionError("All ADB stdout must remain bytes")
        if kwargs.get("timeout", 0) <= 0:
            raise AssertionError("Every ADB call needs a finite timeout")
        if argv[1:] == ["devices", "-l"]:
            return subprocess.CompletedProcess(argv, 0, self.devices, b"")
        if argv[1:3] != ["-s", "PIXEL-1"]:
            raise AssertionError(f"Wrong target or unscoped ADB command: {argv}")
        args = argv[3:]
        outputs = {
            ("shell", "wm", "size"): b"Physical size: 4x6\nOverride size: 2x3\n",
            ("shell", "wm", "density"): b"Physical density: 420\nOverride density: 320\n",
            ("shell", "settings", "get", "system", "font_scale"): b"1.15\n",
            ("exec-out", "screencap", "-p"): self.screenshot,
        }
        if tuple(args) in outputs:
            return subprocess.CompletedProcess(argv, 0, outputs[tuple(args)], b"")
        if args[:3] == ["shell", "uiautomator", "dump"] and len(args) == 4:
            remote = args[3]
            if not remote.startswith("/sdcard/xray-") or not remote.endswith(".xml"):
                raise AssertionError("Remote hierarchy name must belong to this session")
            self.created_remote.append(remote)
            self.remote_files[remote] = b'<?xml version="1.0"?><hierarchy rotation="0"><node text="Hi"/></hierarchy>'
            if self.hierarchy_failure == "dump":
                return subprocess.CompletedProcess(argv, 1, b"", b"uiautomator unavailable")
            if self.hierarchy_failure == "timeout":
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            if self.hierarchy_failure == "xml":
                self.remote_files[remote] = b"<hierarchy><node>"
            return subprocess.CompletedProcess(argv, 0, b"UI hierarchy dumped\n", b"")
        if args[:1] == ["pull"] and len(args) == 3:
            if self.hierarchy_failure == "pull":
                return subprocess.CompletedProcess(argv, 1, b"", b"pull failed")
            Path(args[2]).write_bytes(self.remote_files[args[1]])
            return subprocess.CompletedProcess(argv, 0, b"1 file pulled\n", b"")
        if args[:3] == ["shell", "rm", "-f"] and len(args) == 4:
            if args[3] not in self.created_remote:
                raise AssertionError("Cleanup must only target the session's own XML")
            if self.hierarchy_failure == "cleanup":
                return subprocess.CompletedProcess(argv, 1, b"", b"rm failed")
            self.remote_files.pop(args[3], None)
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        raise AssertionError(f"Unexpected or mutating ADB command: {argv}")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "ADB capture utility is not implemented yet")
        spec = importlib.util.spec_from_file_location("adb_capture_under_test", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory(prefix=".adb-test-", dir=SCRIPT.parents[2] / "tests")
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(SCRIPT.parents[2].resolve()))
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "capture"

    def capture(self, fake=None, **kwargs):
        fake = fake or FakeADB()
        with mock.patch.object(self.module.subprocess, "run", side_effect=fake):
            metadata = self.module.capture(
                serial="PIXEL-1", output_dir=self.output, label="clean", **kwargs)
        return metadata, fake

    def test_success_captures_binary_png_calibration_and_provenance(self):
        metadata, fake = self.capture(adb="C:/Android tools/adb.exe", timeout=7)
        saved = json.loads((self.output / "capture.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata, saved)
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["serial"], "PIXEL-1")
        self.assertEqual(saved["calibration"]["size"]["effective_px"], [2, 3])
        self.assertEqual(saved["calibration"]["size"]["physical_px"], [4, 6])
        self.assertEqual(saved["calibration"]["density"]["effective_dpi"], 320)
        self.assertEqual(saved["calibration"]["font_scale"], 1.15)
        self.assertEqual((self.output / "clean.png").read_bytes(), png_bytes())
        self.assertEqual(saved["screenshot"]["width"], 2)
        self.assertEqual(saved["screenshot"]["height"], 3)
        self.assertEqual(len(saved["screenshot"]["sha256"]), 64)
        self.assertTrue(saved["screenshot"]["captured_at"].endswith("Z"))
        self.assertTrue(saved["completed_at"].endswith("Z"))
        self.assertEqual(saved["hierarchy"]["status"], "available")
        self.assertTrue((self.output / "hierarchy.xml").is_file())
        self.assertEqual(fake.remote_files, {"/sdcard/keep.xml": b"original"})
        self.assertTrue(saved["provenance"]["commands"])
        self.assertEqual(saved["configuration_changes"], [])
        self.assertTrue(all(args[0] == "C:/Android tools/adb.exe" for args, _ in fake.calls))
        self.assertTrue(all(options["timeout"] == 7 for _, options in fake.calls))

    def test_similar_serial_does_not_match_exact_target(self):
        fake = FakeADB(devices=b"List of devices attached\nPIXEL-12 device product:a\n")
        with self.assertRaisesRegex(self.module.CaptureError, "serial|Serial"):
            self.capture(fake)
        self.assertFalse((self.output / "clean.png").exists())
        self.assertEqual(len(fake.calls), 1)

    def test_unauthorized_or_offline_never_proceeds_to_capture(self):
        for state in ("unauthorized", "offline"):
            with self.subTest(state=state):
                fake = FakeADB(devices=("List of devices attached\nPIXEL-1 " + state + "\n").encode())
                with self.assertRaisesRegex(self.module.CaptureError, state):
                    self.capture(fake)
                self.assertEqual(len(fake.calls), 1)
                self.assertFalse((self.output / "clean.png").exists())

    def test_duplicate_serial_is_ambiguous_and_rejected(self):
        fake = FakeADB(devices=b"List of devices attached\nPIXEL-1 device\nPIXEL-1 device\n")
        with self.assertRaises(self.module.CaptureError):
            self.capture(fake)
        self.assertEqual(len(fake.calls), 1)

    def test_invalid_png_signature_is_not_written_or_accepted(self):
        with self.assertRaisesRegex(self.module.CaptureError, "PNG"):
            self.capture(FakeADB(screenshot=b"not an image"))
        self.assertFalse((self.output / "clean.png").exists())
        self.assertFalse((self.output / "capture.json").exists())

    def test_truncated_png_and_zero_dimensions_are_rejected(self):
        for data in (png_bytes()[:33], png_bytes(width=0), png_bytes()[:-1]):
            with self.subTest(data=data[:16]):
                with self.assertRaisesRegex(self.module.CaptureError, "PNG"):
                    self.module.validate_png(data)

    def test_corrupt_png_crc_is_rejected(self):
        data = bytearray(png_bytes())
        data[20] ^= 1
        with self.assertRaisesRegex(self.module.CaptureError, "PNG"):
            self.module.validate_png(bytes(data))

    def test_hierarchy_failures_preserve_screenshot_and_clean_only_own_file(self):
        for reason in ("dump", "pull", "xml", "timeout"):
            with self.subTest(reason=reason):
                self.output = Path(self.temp.name) / reason
                metadata, fake = self.capture(FakeADB(hierarchy_failure=reason))
                self.assertEqual(metadata["status"], "partial")
                self.assertEqual(metadata["hierarchy"]["status"], "unavailable")
                self.assertTrue(metadata["warnings"])
                self.assertEqual((self.output / "clean.png").read_bytes(), png_bytes())
                self.assertFalse((self.output / "hierarchy.xml").exists())
                self.assertEqual(fake.remote_files, {"/sdcard/keep.xml": b"original"})
                self.assertEqual(len(fake.created_remote), 1)

    def test_cleanup_failure_is_explicit_and_screenshot_remains_valid(self):
        metadata, fake = self.capture(FakeADB(hierarchy_failure="cleanup"))
        self.assertEqual(metadata["status"], "partial")
        self.assertEqual(metadata["hierarchy"]["cleanup"], "failed")
        self.assertTrue(metadata["warnings"])
        self.assertTrue((self.output / "clean.png").exists())
        self.assertIn("/sdcard/keep.xml", fake.remote_files)

    def test_skip_hierarchy_does_not_create_remote_temp(self):
        metadata, fake = self.capture(skip_hierarchy=True)
        self.assertEqual(metadata["status"], "complete")
        self.assertEqual(metadata["hierarchy"]["status"], "skipped")
        self.assertEqual(fake.created_remote, [])
        self.assertEqual(fake.remote_files, {"/sdcard/keep.xml": b"original"})

    def test_bounds_label_never_claims_diagnostic_is_verified(self):
        fake = FakeADB()
        with mock.patch.object(self.module.subprocess, "run", side_effect=fake):
            metadata = self.module.capture(
                serial="PIXEL-1", output_dir=self.output, label="bounds", skip_hierarchy=True)
        self.assertFalse(metadata["diagnostics"]["layout_bounds"]["verified"])
        self.assertTrue(metadata["diagnostics"]["layout_bounds"]["label_only"])
        self.assertTrue((self.output / "bounds.png").exists())

    def test_existing_output_is_rejected_without_touching_it_or_adb(self):
        self.output.mkdir()
        original = self.output / "capture.json"
        original.write_text("original", encoding="utf-8")
        fake = FakeADB()
        with self.assertRaisesRegex(self.module.CaptureError, "existe|existente"):
            self.capture(fake)
        self.assertEqual(original.read_text(encoding="utf-8"), "original")
        self.assertEqual(fake.calls, [])

    def test_screenshot_timeout_gives_action_and_does_not_accept_capture(self):
        fake = FakeADB()

        def timeout_screenshot(argv, **kwargs):
            if argv[-3:] == ["exec-out", "screencap", "-p"]:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return fake(argv, **kwargs)

        with mock.patch.object(self.module.subprocess, "run", side_effect=timeout_screenshot):
            with self.assertRaisesRegex(self.module.CaptureError, "tempo|Tempo") as error:
                self.module.capture(serial="PIXEL-1", output_dir=self.output, label="clean", timeout=2)
        self.assertIn("--timeout", str(error.exception))
        self.assertFalse((self.output / "capture.json").exists())

    def test_missing_adb_has_actionable_error(self):
        with mock.patch.object(self.module.subprocess, "run", side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(self.module.CaptureError, "--adb"):
                self.module.capture(serial="PIXEL-1", output_dir=self.output, label="clean")

    def test_bad_timeout_rejected_before_external_work(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout):
                fake = FakeADB()
                with self.assertRaises(self.module.CaptureError):
                    self.capture(fake, timeout=timeout)
                self.assertEqual(fake.calls, [])

    def test_cli_returns_partial_code_and_prints_capture_path(self):
        fake = FakeADB(hierarchy_failure="dump")
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(self.module.subprocess, "run", side_effect=fake):
            with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                result = self.module.main([
                    "--serial", "PIXEL-1", "--output-dir", str(self.output),
                    "--label", "clean", "--timeout", "4"])
        self.assertEqual(result, 2)
        self.assertIn("capture.json", stdout.getvalue())
        self.assertIn("parcial", stderr.getvalue().lower())

    def test_cli_prints_unicode_output_path_with_legacy_windows_streams(self):
        self.output = Path(self.temp.name) / "测试"
        stdout_bytes, stderr_bytes = io.BytesIO(), io.BytesIO()
        with io.TextIOWrapper(stdout_bytes, encoding="cp1252", write_through=True) as stdout:
            with io.TextIOWrapper(stderr_bytes, encoding="cp1252", write_through=True) as stderr:
                with mock.patch.object(self.module.subprocess, "run", side_effect=FakeADB()):
                    with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                        result = self.module.main([
                            "--serial", "PIXEL-1", "--output-dir", str(self.output),
                            "--label", "clean", "--skip-hierarchy"])
                self.assertEqual(result, 0)
                self.assertEqual(
                    stdout_bytes.getvalue().decode("utf-8").strip(),
                    str(self.output.absolute() / "capture.json"))
                self.assertTrue((self.output / "capture.json").is_file())
                self.assertFalse(stdout.closed)
                self.assertFalse(stderr.closed)

    def test_cli_prints_unicode_errors_to_legacy_stderr_without_closing_streams(self):
        stdout_bytes, stderr_bytes = io.BytesIO(), io.BytesIO()
        with io.TextIOWrapper(stdout_bytes, encoding="cp1252", write_through=True) as stdout:
            with io.TextIOWrapper(stderr_bytes, encoding="cp1252", write_through=True) as stderr:
                with mock.patch.object(self.module, "capture", side_effect=self.module.CaptureError("Destino 测试 indisponível")):
                    with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
                        result = self.module.main([
                            "--serial", "PIXEL-1", "--output-dir", str(self.output), "--label", "clean"])
                self.assertEqual(result, 1)
                self.assertIn("Destino 测试 indisponível", stderr_bytes.getvalue().decode("utf-8"))
                self.assertEqual(stdout_bytes.getvalue(), b"")
                self.assertFalse(stdout.closed)
                self.assertFalse(stderr.closed)


if __name__ == "__main__":
    unittest.main()
