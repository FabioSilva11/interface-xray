"""Synthetic-geometry tests for contour_tools.py; run with unittest.

Every test image is drawn here with Pillow and NumPy, independently of the analysis code.
The ground-truth parameters are known, so the tests measure how far the recovered values
are from the originals. Tests are skipped when NumPy is not installed.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

try:
    import numpy as np
    from PIL import Image, ImageDraw
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "interface-xray" / "scripts"
CLI = SCRIPTS / "contour_tools.py"
if HAS_NUMPY:
    sys.path.insert(0, str(SCRIPTS))
    import contour_geometry as geo
    import contour_tools as ct

REPORT = []  # linhas de medição: parâmetro original × recuperado


def _aa(size, items, background, scale=4):
    """Desenha formas com supersampling; items = [("poly", pontos, cor) | ("ellipse", (cx, cy, r), cor)]."""
    width, height = size
    canvas = Image.new("RGB", (width * scale, height * scale), background)
    draw = ImageDraw.Draw(canvas)
    for kind, shape, color in items:
        if kind == "poly":
            draw.polygon([(x * scale, y * scale) for x, y in shape], fill=color)
        else:
            cx, cy, radius = shape
            draw.ellipse(((cx - radius) * scale, (cy - radius) * scale, (cx + radius) * scale, (cy + radius) * scale), fill=color)
    return np.asarray(canvas.resize((width, height), Image.BOX), dtype=np.float64)


def _mask(size, points, scale=4):
    width, height = size
    canvas = Image.new("L", (width * scale, height * scale), 0)
    ImageDraw.Draw(canvas).polygon([(x * scale, y * scale) for x, y in points], fill=255)
    return np.asarray(canvas.resize((width, height), Image.BOX), dtype=np.float64) / 255.0


def _cubic(p0, p1, p2, p3, count=200):
    t = np.linspace(0.0, 1.0, count)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, dtype=np.float64) for p in (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


def _rebuild(primitives, origin):
    """Reconstrói primitivos do JSON em quadro do recorte, para amostragem."""
    segments = []
    for item in primitives:
        if item["type"] == "line":
            segments.append({"type": "line", "start": np.array(item["start"]["crop"]), "end": np.array(item["end"]["crop"]), "max_error_px": 0.0})
        elif item["type"] == "arc":
            segments.append({"type": "arc", "start": np.array(item["start"]), "end": np.array(item["end"]),
                             "center": np.array(item["center"]["crop"]), "radius": item["radius_px"],
                             "start_angle": math.radians(item["start_angle_deg"]), "sweep": math.radians(item["sweep_deg"]),
                             "max_error_px": 0.0})
        else:
            segments.append({"type": "cubic", "control": np.array(item["control_points"]["crop"]), "max_error_px": 0.0})
    return segments


def _image_points(element):
    """Amostra o contorno base recuperado em coordenadas da captura completa."""
    frame = element["analysis_frame"]
    origin = np.array([frame["x"], frame["y"]], dtype=np.float64)
    return geo.sample_segments(_rebuild(element["geometry"]["primitives_crop"], origin)) + origin


def _endpoints(element):
    frame = element["analysis_frame"]
    origin = np.array([frame["x"], frame["y"]], dtype=np.float64)
    points = []
    for item in element["geometry"]["primitives_crop"]:
        if item["type"] == "line":
            points.append(np.array(item["start"]["image"]))
        elif item["type"] == "arc":
            points.append(np.array(item["start"]) + origin)
        else:
            points.append(np.array(item["control_points"]["image"][0]))
    return np.array(points)


def _max_vertex_error(truth, element):
    """Maior distância de um vértice verdadeiro até o extremo recuperado mais próximo."""
    recovered = _endpoints(element)
    distances = [np.min(np.hypot(*(recovered - np.asarray(v)).T)) for v in truth]
    return float(max(distances))


def _record(label, original, recovered, unit="px"):
    REPORT.append(f"{label:<44} original={original!s:<14} recuperado={recovered!s:<14} {unit}")


_WORK = None
_CACHE = {}


def setUpModule():
    global _WORK
    _WORK = tempfile.TemporaryDirectory(prefix="contour-tests-")


def tearDownModule():
    if _WORK is not None:
        _WORK.cleanup()
    if REPORT:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print("\nMedição de parâmetros (original × recuperado):")
        print("\n".join(REPORT))


def _analyze(name, array, bbox, **kwargs):
    """Analisa uma imagem sintética uma vez por nome, em pasta nova do diretório temporário."""
    fingerprint = hashlib.sha256(array.tobytes() + repr((bbox, kwargs)).encode()).hexdigest()[:16]
    key = name + '-' + fingerprint
    if key not in _CACHE:
        folder = Path(_WORK.name) / key
        folder.mkdir()
        image = folder / "capture.png"
        Image.fromarray(np.clip(np.rint(array), 0, 255).astype(np.uint8)).save(image)
        output = folder / "analysis"
        result = ct.analyze_element(image, bbox, output, **kwargs)
        element = json.loads((output / "element.json").read_text(encoding="utf-8"))
        metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
        _CACHE[key] = {"image": image, "output": output, "result": result, "element": element, "metrics": metrics}
    return _CACHE[key]


@unittest.skipUnless(HAS_NUMPY, "requer NumPy (requirements-contour.txt)")
class GeometryPrimitiveTests(unittest.TestCase):
    def test_circle_fit_recovers_center_and_radius(self):
        angles = np.linspace(0, 2 * math.pi, 120, endpoint=False)
        points = np.column_stack([5 + 30 * np.cos(angles), 7 + 30 * np.sin(angles)])
        cx, cy, radius, residual = geo.fit_circle(points)
        self.assertAlmostEqual(cx, 5, places=6)
        self.assertAlmostEqual(cy, 7, places=6)
        self.assertAlmostEqual(radius, 30, places=6)
        self.assertLess(residual, 1e-6)

    def test_cubic_fit_reproduces_known_curve(self):
        truth = np.array([[0, 0], [10, 40], [50, 40], [60, 0]], dtype=np.float64)
        samples = _cubic(*truth)
        fitted = geo.fit_cubic(samples)
        curve_truth = _cubic(*truth)
        curve_fit = _cubic(*fitted)
        measure = geo.bidirectional_chamfer(curve_fit, curve_truth)
        self.assertLess(measure["hausdorff_px"], 0.1)
        _record("cúbica: erro de Hausdorff do ajuste", "0 (exato)", f"{measure['hausdorff_px']:.3f}", "px")

    def test_trace_loops_separates_outer_boundary_from_hole(self):
        mask = np.zeros((20, 20), dtype=bool)
        mask[2:18, 2:18] = True
        mask[6:12, 6:12] = False
        outer, holes = geo.trace_loops(mask)
        self.assertEqual(len(outer), 1)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(abs(geo._shoelace(outer[0])), 16 * 16)
        self.assertAlmostEqual(abs(geo._shoelace(holes[0])), 6 * 6)

    def test_levenberg_marquardt_converges_on_linear_residual(self):
        target = np.array([3.0, -2.0])
        solution, history = geo.levenberg_marquardt(lambda x: x - target, np.zeros(2))
        np.testing.assert_allclose(solution, target, atol=1e-6)
        self.assertLessEqual(history[-1], history[0])

    def test_render_coverage_is_antialiased_across_an_edge(self):
        polygon = np.array([[2.0, 2.0], [10.0, 2.0], [10.0, 10.0], [2.0, 10.0]])
        layer = {"kind": "fill", "polygon": polygon, "fill": [255.0, 0.0, 0.0]}
        rendered = geo.render_layers((12, 12), [layer])
        self.assertAlmostEqual(rendered[5, 5, 3], 255.0, places=3)
        self.assertAlmostEqual(rendered[5, 1, 3], 0.0, places=3)
        self.assertAlmostEqual(rendered[5, 10, 3], 0.0, places=3)


@unittest.skipUnless(HAS_NUMPY, "requer NumPy (requirements-contour.txt)")
class ContourRecoveryTests(unittest.TestCase):
    def test_hollow_ring_exports_hole_instead_of_painting_center(self):
        array=_aa((100,100), [('ellipse',(50,50,30),(40,120,220)),
                              ('ellipse',(50,50,20),(20,20,30))],(20,20,30))
        case=_analyze('hollow',array,(20,20,60,60),seed=(75,50))
        self.assertEqual(case['element']['method']['holes_exported'],1)
        self.assertIn('fill-rule="evenodd"',(case['output']/'element.svg').read_text())
        self.assertLess(case['metrics']['appearance']['interior']['mae_rgb'],3)

    def test_variable_width_is_preserved_as_samples(self):
        angle=np.linspace(0,2*math.pi,240,endpoint=False)
        radius=58+2*np.cos(angle)
        outer=np.column_stack([100+radius*np.cos(angle),90+radius*np.sin(angle)])
        array=_aa((200,180), [('poly',outer,(230,230,230)),('ellipse',(100,90,50),(40,120,220))],(25,25,35))
        case=_analyze('variable',array,(38,28,124,124))
        samples=case['element']['contours'][1]['width_samples_px']
        self.assertLess(abs(np.median(samples)-8),1)
        self.assertGreater(np.ptp(samples),2.5)

    def test_marked_pixels_do_not_become_the_fill_color(self):
        image=Image.new('RGB',(100,90),(20,20,30))
        pen=ImageDraw.Draw(image)
        pen.rectangle((20,15,80,75),fill=(40,120,220))
        pen.rectangle((23,18,77,72),outline=(255,0,0),width=3)
        case=_analyze('marked',np.asarray(image,float),(20,15,60,60),markup_filter=True,max_iterations=2)
        self.assertGreater(case['element']['method']['markup_pixels_dilated'],0)
        fill=case['element']['revision_state']['fills'][0]
        np.testing.assert_allclose(fill['color'],[40,120,220],atol=2)

    def test_chamfered_rectangle_recovers_eight_lines_and_vertices(self):
        outline = [(40, 30), (160, 30), (172, 42), (172, 100), (160, 112), (40, 112), (28, 100), (28, 42)]
        array = _aa((200, 140), [("poly", outline, (40, 120, 220))], (30, 40, 60))
        case = _analyze("chamfer", array, (28, 30, 145, 83))
        element = case["element"]
        lines = [p for p in element["geometry"]["primitives_crop"] if p["type"] == "line"]
        self.assertGreaterEqual(len(lines), 8)
        self.assertLessEqual(len(lines), 9)
        self.assertEqual(element["decision"]["procedure"], "matematica")
        error = _max_vertex_error(outline, element)
        _record("chanfro: maior erro de vértice", "0", f"{error:.3f}", "px")
        self.assertLess(error, 1.0)
        fill = element["layers"][-1]["color_model"]
        _record("chanfro: cor do preenchimento (R,G,B)", "40,120,220", ",".join(f"{v:.0f}" for v in fill["color"]))
        np.testing.assert_allclose(fill["color"], [40, 120, 220], atol=2.0)

    def test_asymmetric_polygon_recovers_five_vertices(self):
        outline = [(45, 40), (150, 28), (172, 92), (112, 132), (48, 108)]
        array = _aa((200, 150), [("poly", outline, (200, 90, 60))], (20, 20, 30))
        case = _analyze("asymmetric", array, (45, 28, 127, 104))
        element = case["element"]
        lines = [p for p in element["geometry"]["primitives_crop"] if p["type"] == "line"]
        self.assertEqual(len(lines), 5)
        error = _max_vertex_error(outline, element)
        _record("polígono assimétrico: maior erro de vértice", "0", f"{error:.3f}", "px")
        self.assertLess(error, 1.0)

    def test_bezier_lens_is_recovered_within_curve_tolerance(self):
        top = _cubic((30, 80), (60, 10), (140, 10), (170, 80))
        bottom = _cubic((170, 80), (140, 150), (60, 150), (30, 80))
        outline = np.vstack([top, bottom[1:]])
        array = _aa((200, 160), [("poly", outline, (120, 60, 200))], (20, 20, 30))
        case = _analyze("bezier", array, (28, 8, 145, 145))
        element = case["element"]
        curves = [p for p in element["geometry"]["primitives_crop"] if p["type"] != "line"]
        self.assertGreaterEqual(len(curves), 1, "esperava trechos curvos (Bézier ou arco)")
        measure = geo.bidirectional_chamfer(_image_points(element), outline)
        _record("Bézier: Hausdorff entre curva recuperada e verdadeira", "0", f"{measure['hausdorff_px']:.3f}", "px")
        self.assertLess(measure["hausdorff_px"], 1.5)

    def test_concentric_ring_recovers_border_width_and_radius(self):
        array = _aa((200, 180), [("ellipse", (100, 90, 60), (230, 230, 230)), ("ellipse", (100, 90, 52), (40, 120, 220))], (25, 25, 35))
        case = _analyze("ring", array, (40, 30, 120, 120))
        element = case["element"]
        self.assertTrue(all(p['type']=='arc' for p in element['geometry']['primitives_crop']),
                        'um círculo observado deve preferir arcos, não dezenas de cúbicas')
        bands = [c for c in element["contours"] if c["id"] != "C0"]
        self.assertEqual(len(bands), 1)
        width = bands[0]["offset_px"]["median"]
        _record("anel: largura da borda", "8", f"{width:.2f}", "px")
        self.assertLess(abs(width - 8.0), 1.0)
        radii = np.hypot(*(_image_points(element) - np.array([100, 90])).T)
        _record("anel: raio do preenchimento", "52", f"{np.median(radii):.2f}", "px")
        self.assertLess(abs(np.median(radii) - 52.0), 1.0)

    def test_double_border_yields_two_measured_bands(self):
        array = _aa((200, 180), [("ellipse", (100, 90, 62), (230, 230, 230)), ("ellipse", (100, 90, 58), (20, 20, 20)),
                                 ("ellipse", (100, 90, 50), (40, 120, 220))], (25, 25, 35))
        case = _analyze("double", array, (40, 30, 120, 120))
        bands = sorted(c["offset_px"]["median"] for c in case["element"]["contours"] if c["id"] != "C0")
        self.assertEqual(len(bands), 2)
        _record("borda dupla: deslocamento da borda interna", "8", f"{bands[0]:.2f}", "px")
        _record("borda dupla: deslocamento da borda externa", "12", f"{bands[1]:.2f}", "px")
        self.assertLess(abs(bands[0] - 8.0), 1.0)
        self.assertLess(abs(bands[1] - 12.0), 1.0)

    def test_gaussian_halo_is_detected_with_recovered_dispersion(self):
        size = (220, 160)
        rows, cols = np.mgrid[0:size[1], 0:size[0]]
        px, py = cols + 0.5, rows + 0.5
        x0, y0, x1, y1 = 70, 50, 150, 110
        distance = np.hypot(np.maximum(np.maximum(x0 - px, 0), px - x1), np.maximum(np.maximum(y0 - py, 0), py - y1))
        alpha = 0.6 * np.exp(-distance ** 2 / (2 * 5.0 ** 2))
        halo = np.array([255.0, 200.0, 80.0])
        background = np.array([20.0, 25.0, 35.0])
        base = background[None, None, :] * (1 - alpha[..., None]) + halo[None, None, :] * alpha[..., None]
        panel = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        coverage = _mask(size, panel)[..., None]
        array = base * (1 - coverage) + np.array([40.0, 120.0, 220.0]) * coverage
        case = _analyze("halo", array, (70, 50, 80, 60), margin=30)
        glow = case["element"]["effects"]["glow_or_shadow"]
        self.assertIsNotNone(glow, "halo gaussiano não detectado")
        self.assertEqual(glow["kind"], "glow")
        _record("halo gaussiano: desvio padrão σ", "5.0", f"{glow['sigma_px']:.2f}", "px")
        self.assertLess(abs(glow["sigma_px"] - 5.0) / 5.0, 0.35)

    def test_partial_occlusion_keeps_visible_corners_and_flags_hidden_edge(self):
        panel = [(50, 40), (170, 40), (170, 120), (50, 120)]
        occluder = [(140, 25), (200, 25), (200, 135), (140, 135)]
        array = _aa((220, 150), [("poly", panel, (40, 120, 220)), ("poly", occluder, (250, 250, 250))], (25, 30, 40))
        exclusions = [{"id": "oclusor", "x": 140, "y": 25, "width": 60, "height": 110}]
        case = _analyze("occlusion", array, (50, 40, 120, 80), exclusions=exclusions)
        element = case["element"]
        left_corners = [(50, 40), (50, 120)]
        error = _max_vertex_error(left_corners, element)
        _record("oclusão: erro dos cantos visíveis", "0", f"{error:.3f}", "px")
        self.assertLess(error, 1.0)
        observed = element["geometry"]["observed_fraction"]
        _record("oclusão: fração de contorno observado", "≈0,75", f"{observed:.2f}")
        self.assertGreater(observed, 0.55)
        self.assertLess(observed, 0.9)

    def test_textured_background_does_not_crash_and_reports_method(self):
        rng = np.random.default_rng(1)
        background = rng.uniform(0, 255, size=(150, 200, 3))
        panel_mask = _mask((200, 150), [(40, 40), (160, 40), (160, 110), (40, 110)])[..., None]
        panel = 0.8 * np.array([40.0, 120.0, 220.0]) + 0.2 * background
        array = background * (1 - panel_mask) + panel * panel_mask
        case = _analyze("textured", array, (36, 36, 128, 78))
        element = case["element"]
        self.assertIn(element["method"]["segmentation"], {"regiao_de_cor", "raios_de_borda"})
        self.assertEqual(element["decision"]["procedure"], "matematica")
        points = _image_points(element)
        box = np.array([points[:, 0].min(), points[:, 1].min(), points[:, 0].max(), points[:, 1].max()])
        truth = np.array([40, 40, 160, 110])
        _record("fundo com textura: erro da caixa externa (máx.)", "0", f"{np.max(np.abs(box - truth)):.2f}", "px")


@unittest.skipUnless(HAS_NUMPY, "requer NumPy (requirements-contour.txt)")
class CommandLineTests(unittest.TestCase):
    def test_revision_preserves_unknown_mask_and_metrics(self):
        panel=[(50,40),(170,40),(170,120),(50,120)]
        occluder=[(140,25),(200,25),(200,135),(140,135)]
        array=_aa((220,150),[('poly',panel,(40,120,220)),('poly',occluder,(250,250,250))],(25,30,40))
        exclusions=[{'id':'oclusor','x':140,'y':25,'width':60,'height':110}]
        case=_analyze('occlusion',array,(50,40,120,80),exclusions=exclusions)
        override=Path(_WORK.name)/'mask-overrides.json'; override.write_text('{}')
        output=Path(_WORK.name)/'mask-revision'
        ct.revise_element(case['output']/'element.json',override,output,image_path=case['image'])
        revised=json.loads((output/'element.json').read_text(encoding='utf-8'))
        metrics=json.loads((output/'metrics.json').read_text(encoding='utf-8'))
        self.assertEqual(revised['revision_state']['unknown_runs'],case['element']['revision_state']['unknown_runs'])
        self.assertEqual(metrics['appearance']['unknown_pixels_excluded'],case['metrics']['appearance']['unknown_pixels_excluded'])

    def test_revision_accepts_its_own_arc_model(self):
        image=Image.new('RGB',(100,90),(20,20,30))
        ImageDraw.Draw(image).ellipse((20,15,80,75),fill=(40,120,220))
        case=_analyze('arc-regression',np.asarray(image,dtype=float),(20,15,60,60),max_iterations=2)
        overrides=Path(_WORK.name)/'arc-overrides.json'
        overrides.write_text(json.dumps({'colors':{'C0':[180,70,30]}}),encoding='utf-8')
        result=ct.revise_element(case['output']/'element.json',overrides,Path(_WORK.name)/'arc-revision',image_path=case['image'])
        self.assertTrue(Path(result['svg']).is_file())
        second=ct.revise_element(result['element'],overrides,Path(_WORK.name)/'arc-revision-2',image_path=case['image'])
        self.assertTrue(Path(second['svg']).is_file())

    def _cli(self, *args):
        return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True,
                              encoding="utf-8", check=False)

    def test_analyze_refuses_existing_output_directory(self):
        outline = [(40, 30), (160, 30), (160, 110), (40, 110)]
        array = _aa((200, 140), [("poly", outline, (40, 120, 220))], (30, 40, 60))
        case = _analyze("chamfer", array, (28, 30, 145, 83))
        result = self._cli("analyze", "--image", case["image"], "--bbox", "28,30,145,83", "--output-dir", case["output"].parent)
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))
        self.assertNotIn("Traceback", result.stderr)

    def test_revision_changes_color_without_touching_original_model(self):
        case = _analyze("chamfer", _aa((200, 140), [("poly", [(40, 30), (160, 30), (172, 42), (172, 100), (160, 112), (40, 112), (28, 100), (28, 42)], (40, 120, 220))], (30, 40, 60)), (28, 30, 145, 83))
        model = case["output"] / "element.json"
        before = hashlib.sha256(model.read_bytes()).hexdigest()
        overrides = Path(_WORK.name) / "ov-red.json"
        overrides.write_text(json.dumps({"colors": {"C0": [255, 0, 0]}}), encoding="utf-8")
        revision = Path(_WORK.name) / "rev-red"
        result = ct.revise_element(model, overrides, revision, image_path=case["image"])
        self.assertEqual(hashlib.sha256(model.read_bytes()).hexdigest(), before)
        revised = json.loads((revision / "element.json").read_text(encoding="utf-8"))
        fill = [layer for layer in revised["layers"] if layer["contour"] == "C0"][0]["color_model"]
        self.assertEqual(fill["color"], [255.0, 0.0, 0.0])
        self.assertTrue(result["changes"])
        self.assertIn("C0", result["changes"][0])

    def test_revision_rejects_different_capture(self):
        case = _analyze("chamfer", _aa((200, 140), [("poly", [(40, 30), (160, 30), (172, 42), (172, 100), (160, 112), (40, 112), (28, 100), (28, 42)], (40, 120, 220))], (30, 40, 60)), (28, 30, 145, 83))
        other = Path(_WORK.name) / "other.png"
        Image.new("RGB", (200, 140), (1, 2, 3)).save(other)
        overrides = Path(_WORK.name) / "ov-none.json"
        overrides.write_text("{}", encoding="utf-8")
        result = self._cli("revise", "--model", case["output"] / "element.json", "--overrides", overrides,
                           "--image", other, "--output-dir", Path(_WORK.name) / "rev-mismatch")
        self.assertEqual(result.returncode, 2)
        self.assertIn("SHA-256", json.loads(result.stderr)["error"])

    def test_svg_is_well_formed_and_editable_paths(self):
        case = _analyze("chamfer", _aa((200, 140), [("poly", [(40, 30), (160, 30), (172, 42), (172, 100), (160, 112), (40, 112), (28, 100), (28, 42)], (40, 120, 220))], (30, 40, 60)), (28, 30, 145, 83))
        root = ET.parse(case["output"] / "element.svg").getroot()
        self.assertTrue(root.tag.endswith("svg"))
        paths = [el for el in root.iter() if el.tag.endswith("path") and el.get("id", "").startswith("C")]
        self.assertEqual(len(paths), len(case["element"]["contours"]))
        self.assertTrue(paths[0].get("d", "").startswith("M"))

    def test_diagnostic_images_are_written_as_new_png_files(self):
        case = _analyze("chamfer", _aa((200, 140), [("poly", [(40, 30), (160, 30), (172, 42), (172, 100), (160, 112), (40, 112), (28, 100), (28, 42)], (40, 120, 220))], (30, 40, 60)), (28, 30, 145, 83))
        names = {"source_crop_x4", "render_x4", "overlay_x4", "difference_x4", "edges_x4", "points_x4", "curves_x4"}
        for key in names:
            path = Path(case["result"]["diagnostics"][key])
            self.assertTrue(path.is_file(), key)
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")


if __name__ == "__main__":
    unittest.main()
