"""Behavioral tests using only synthetic local images; run with unittest."""

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "interface-xray" / "scripts" / "image_tools.py"


class ImageToolsTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "O utilitário image_tools.py ainda não existe")
        spec = importlib.util.spec_from_file_location("image_tools_under_test", SCRIPT)
        self.tools = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tools)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT, prefix=".image-tools-test-")
        self.root = Path(self.temp.name)
        self.assertTrue(self.root.resolve().is_relative_to(ROOT.resolve()))
        self.addCleanup(self.temp.cleanup)

    def image(self, name="input.png", size=(8, 8), color=(0, 0, 0), mode="RGB"):
        path = self.root / name
        image = Image.new(mode, size, color)
        if mode == "P":
            image.putpalette([channel for index in range(256) for channel in (index, index, index)])
        image.save(path)
        return path

    def boxes(self, boxes=None, units="px_imagem"):
        path = self.root / "boxes.json"
        if boxes is None:
            boxes = [{"id": "E01", "x": 2, "y": 2, "width": 4, "height": 4}]
        path.write_text(json.dumps({"units": units, "boxes": boxes}), encoding="utf-8")
        return path

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", check=False,
        )

    def test_inspect_reports_native_pixels_dimensions_and_file_hash(self):
        path = self.image(mode="RGBA", color=(1, 2, 3, 4), size=(3, 2))
        before = path.read_bytes()
        result = self.tools.inspect_image(path, points=[(2, 1), (0, 0)])
        self.assertEqual(result["size"], [3, 2])
        self.assertEqual(result["mode"], "RGBA")
        self.assertEqual(result["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(result["points"], [
            {"x": 2, "y": 1, "pixel": [1, 2, 3, 4]},
            {"x": 0, "y": 0, "pixel": [1, 2, 3, 4]},
        ])
        self.assertEqual(path.read_bytes(), before)

    def test_inspect_keeps_palette_indices_instead_of_inventing_rgb(self):
        path = self.image(mode="P", color=7)
        result = self.tools.inspect_image(path, points=[(0, 0)])
        self.assertEqual(result["mode"], "P")
        self.assertEqual(result["points"][0]["pixel"], 7)

    def test_inspect_does_not_apply_exif_orientation(self):
        path = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[274] = 6
        Image.new("RGB", (3, 2)).save(path, exif=exif)
        result = self.tools.inspect_image(path)
        self.assertEqual(result["size"], [3, 2])
        self.assertEqual(result["exif_orientation"], 6)
        self.assertFalse(result["orientation_applied"])

    def test_inspect_rejects_points_outside_image_and_noninteger_points(self):
        path = self.image(size=(2, 2))
        for point in [(-1, 0), (2, 0), (0, 2), (0.5, 0), (True, 0)]:
            with self.subTest(point=point), self.assertRaises(self.tools.ImageToolError):
                self.tools.inspect_image(path, points=[point])

    def test_inspect_invalid_file_is_a_friendly_error(self):
        path = self.root / "not-image.txt"
        path.write_text("not an image", encoding="utf-8")
        with self.assertRaises(self.tools.ImageToolError):
            self.tools.inspect_image(path)

    def test_annotate_writes_separate_same_size_png_and_preserves_inputs(self):
        path = self.image(size=(64, 64))
        boxes = self.boxes()
        original = path.read_bytes()
        original_boxes = boxes.read_bytes()
        output = self.root / "anotação.png"
        result = self.tools.annotate_image(path, boxes, output)
        with Image.open(output) as annotated:
            self.assertEqual(annotated.size, (64, 64))
            self.assertEqual(annotated.format, "PNG")
            self.assertNotEqual(annotated.convert("RGB").getpixel((2, 4)), (0, 0, 0))
            self.assertEqual(annotated.convert("RGB").getpixel((63, 63)), (0, 0, 0))
        self.assertEqual(result["units"], "px_imagem")
        self.assertEqual(result["box_count"], 1)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(boxes.read_bytes(), original_boxes)

    def test_annotate_accepts_box_touching_last_row_and_column(self):
        path = self.image()
        boxes = self.boxes([{"id": "E01", "x": 7, "y": 7, "width": 1, "height": 1}])
        output = self.root / "last-pixel.png"
        self.tools.annotate_image(path, boxes, output)
        with Image.open(output) as annotated:
            self.assertNotEqual(annotated.convert("RGB").getpixel((7, 7)), (0, 0, 0))

    def test_annotate_rejects_bounds_dimensions_and_noninteger_coordinates(self):
        path = self.image()
        base = {"id": "E01", "x": 2, "y": 2, "width": 4, "height": 4}
        mutations = [
            {"x": -1}, {"y": -1}, {"width": 0}, {"height": -1},
            {"width": 7}, {"height": 7}, {"x": 0.5}, {"width": True},
        ]
        for change in mutations:
            output = self.root / "invalid.png"
            with self.subTest(change=change), self.assertRaises(self.tools.ImageToolError):
                self.tools.annotate_image(path, self.boxes([dict(base, **change)]), output)
            self.assertFalse(output.exists())

    def test_annotate_rejects_missing_or_duplicate_ids_and_unknown_units(self):
        path = self.image()
        base = {"id": "E01", "x": 0, "y": 0, "width": 2, "height": 2}
        missing = {key: value for key, value in base.items() if key != "id"}
        for box_list in [[missing], [dict(base, id="")], [dict(base, id="bad\nID")], [base, base]]:
            with self.subTest(boxes=box_list), self.assertRaises(self.tools.ImageToolError):
                self.tools.annotate_image(path, self.boxes(box_list), self.root / "invalid.png")
        with self.assertRaises(self.tools.ImageToolError):
            self.tools.annotate_image(path, self.boxes(units="dp"), self.root / "invalid.png")

    def test_annotate_rejects_invalid_json_and_preserves_output_absence(self):
        path = self.image()
        boxes = self.root / "bad.json"
        boxes.write_text("{", encoding="utf-8")
        output = self.root / "invalid.png"
        with self.assertRaises(self.tools.ImageToolError):
            self.tools.annotate_image(path, boxes, output)
        self.assertFalse(output.exists())

    def test_annotate_rejects_overwrite_of_image_boxes_or_existing_output(self):
        path = self.image()
        boxes = self.boxes()
        existing = self.root / "existing.png"
        existing.write_bytes(b"keep me")
        for target in [path, boxes, existing]:
            before = target.read_bytes()
            with self.subTest(target=target), self.assertRaises(self.tools.ImageToolError):
                self.tools.annotate_image(path, boxes, target)
            self.assertEqual(target.read_bytes(), before)

    def test_compare_has_hand_checked_mae_count_and_fraction(self):
        reference = self.image("reference.png", size=(2, 1))
        actual = self.root / "actual.png"
        image = Image.new("RGB", (2, 1))
        image.putdata([(10, 20, 30), (0, 0, 0)])
        image.save(actual)
        result = self.tools.compare_images(reference, actual, self.root / "comparison", threshold=20)
        self.assertEqual(result["mae_rgb"], 10.0)
        self.assertEqual(result["different_pixels"], 1)
        self.assertEqual(result["total_pixels"], 2)
        self.assertEqual(result["different_fraction"], 0.5)
        self.assertEqual(result["threshold"], 20)
        with Image.open(self.root / "comparison" / "difference.png") as difference:
            self.assertEqual([difference.getpixel((0, 0)), difference.getpixel((1, 0))], [(10, 20, 30), (0, 0, 0)])
        with Image.open(self.root / "comparison" / "overlay.png") as overlay:
            self.assertEqual([overlay.getpixel((0, 0)), overlay.getpixel((1, 0))], [(5, 10, 15), (0, 0, 0)])
        saved = json.loads((self.root / "comparison" / "metrics.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, result)

    def test_compare_threshold_is_strict_and_does_not_change_mae(self):
        reference = self.image("reference.png", size=(1, 1))
        actual = self.image("actual.png", size=(1, 1), color=(5, 0, 0))
        for threshold, expected in [(0, 1), (4, 1), (5, 0), (255, 0)]:
            with self.subTest(threshold=threshold):
                result = self.tools.compare_images(reference, actual, self.root / f"comparison-{threshold}", threshold=threshold)
                self.assertEqual(result["different_pixels"], expected)
                self.assertAlmostEqual(result["mae_rgb"], 5 / 3)

    def test_compare_composites_transparency_on_white(self):
        reference = self.image("reference.png", size=(1, 1), mode="RGBA", color=(255, 0, 0, 0))
        actual = self.image("actual.png", size=(1, 1), color=(255, 255, 255))
        result = self.tools.compare_images(reference, actual, self.root / "comparison", threshold=0)
        self.assertEqual(result["mae_rgb"], 0.0)
        self.assertEqual(result["different_pixels"], 0)
        self.assertEqual(result["conditions"]["alpha_background_rgb"], [255, 255, 255])

    def test_compare_composites_partial_alpha_and_counts_all_rgb_channels(self):
        reference = self.image("reference.png", size=(1, 1), mode="RGBA", color=(0, 0, 0, 128))
        actual = self.image("actual.png", size=(1, 1), color=(127, 127, 127))
        result = self.tools.compare_images(reference, actual, self.root / "comparison", threshold=0)
        self.assertEqual(result["mae_rgb"], 0.0)

    def test_compare_rejects_dimension_mismatch_without_creating_directory(self):
        reference = self.image("reference.png", size=(2, 1))
        actual = self.image("actual.png", size=(1, 2))
        output = self.root / "comparison"
        with self.assertRaises(self.tools.ImageToolError):
            self.tools.compare_images(reference, actual, output, threshold=0)
        self.assertFalse(output.exists())

    def test_compare_rejects_existing_directory_file_and_input_parent(self):
        reference = self.image("reference.png")
        actual = self.image("actual.png")
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep.txt"
        marker.write_text("keep me", encoding="utf-8")
        for output in [existing, reference, self.root]:
            with self.subTest(output=output), self.assertRaises(self.tools.ImageToolError):
                self.tools.compare_images(reference, actual, output, threshold=0)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me")

    def test_compare_rejects_noninteger_or_out_of_range_threshold(self):
        reference = self.image("reference.png")
        actual = self.image("actual.png")
        for threshold in [-1, 256, True, 0.5, "0"]:
            output = self.root / "comparison"
            with self.subTest(threshold=threshold), self.assertRaises(self.tools.ImageToolError):
                self.tools.compare_images(reference, actual, output, threshold=threshold)
            self.assertFalse(output.exists())

    def test_compare_preserves_both_input_files(self):
        reference = self.image("reference.png")
        actual = self.image("actual.png", color=(255, 0, 0))
        before = [reference.read_bytes(), actual.read_bytes()]
        self.tools.compare_images(reference, actual, self.root / "comparison", threshold=0)
        self.assertEqual([reference.read_bytes(), actual.read_bytes()], before)

    def test_cli_inspect_emits_utf8_json_and_repeated_points(self):
        path = self.image("referência.png", color=(11, 22, 33))
        result = self.cli("inspect", path, "--point", "0,0", "--point", "1,1")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(len(data["points"]), 2)
        self.assertEqual(data["points"][1]["pixel"], [11, 22, 33])
        self.assertIn("referência.png", result.stdout)
        self.assertIn("\n  ", result.stdout)

    def test_cli_annotate_and_compare_return_parseable_json(self):
        reference = self.image("reference.png")
        actual = self.image("actual.png", color=(255, 0, 0))
        annotated = self.cli("annotate", "--image", reference, "--boxes", self.boxes(), "--output", self.root / "annotated.png")
        self.assertEqual(annotated.returncode, 0, annotated.stderr)
        self.assertEqual(json.loads(annotated.stdout)["box_count"], 1)
        compared = self.cli("compare", "--reference", reference, "--actual", actual, "--output-dir", self.root / "comparison", "--threshold", "0")
        self.assertEqual(compared.returncode, 0, compared.stderr)
        self.assertEqual(json.loads(compared.stdout)["different_pixels"], 64)

    def test_cli_reports_friendly_json_error_without_traceback(self):
        result = self.cli("inspect", self.root / "missing.png")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_cli_rejects_bad_point_and_requires_explicit_threshold(self):
        path = self.image()
        for command in [
            ["inspect", path, "--point", "1.2,0"],
            ["compare", "--reference", path, "--actual", path, "--output-dir", self.root / "comparison"],
        ]:
            with self.subTest(command=command):
                result = self.cli(*command)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)
                self.assertIn("error", json.loads(result.stderr))


if __name__ == "__main__":
    unittest.main()
