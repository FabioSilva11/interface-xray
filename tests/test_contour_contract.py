"""Invariantes geométricos e de evidência, independentes do detector."""
import inspect
from pathlib import Path
import sys
import unittest
import tempfile
import json
import xml.etree.ElementTree as ET

try:
    import numpy as np
except ImportError:
    np = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'interface-xray/scripts'))
if np is not None:
    import contour_geometry as geo
    import contour_tools as ct


@unittest.skipIf(np is None, 'NumPy opcional ausente')
class EvidenceContractTests(unittest.TestCase):
    def test_color_sampling_rejects_masked_interpolation_footprint(self):
        rgb=np.zeros((20,20,3)); rgb[4:7]=[255,0,0]
        unknown=np.zeros((20,20),bool); unknown[4:7]=True
        positions,colors=ct._ring_samples(rgb,np.array([[10.,10.]]),np.array([[0.,-1.]]),
                     np.array([5.]),np.array([5.]),np.array([True]),unknown=unknown)
        self.assertEqual(len(colors),0)

    def test_svg_gradient_preserves_spatial_direction(self):
        fill={'kind':'linear','origin':[0.,0.],'color':[50.,50.,50.],'slope':[[1.,1.,1.],[0.5,0.5,0.5]]}
        path=[{'type':'line','start':np.array([0.,0.]),'end':np.array([100.,0.]),'max_error_px':0}]
        model={'id':'E01','analysis_frame':{'x':0,'y':0}}
        svg=ct._svg_document(model,[path],[fill],None,(100,100))
        gradient=ET.fromstring(svg).find('.//{http://www.w3.org/2000/svg}linearGradient')
        dx=float(gradient.get('x2'))-float(gradient.get('x1'))
        dy=float(gradient.get('y2'))-float(gradient.get('y1'))
        self.assertAlmostEqual(dx/dy,2,places=2)

    def test_open_screenshot_exports_editable_path_and_context(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            image=Image.new('RGB',(50,40),'black')
            ImageDraw.Draw(image).line([(8,20),(41,20)],fill='white',width=5)
            image.save(root/'source.png')
            result=ct.trace_open_element(root/'source.png',(0,0,50,40),root/'out',start=(8,17),end=(41,17))
            model=json.loads((root/'out/element.json').read_text(encoding='utf-8'))
            self.assertEqual(model['geometry']['type'],'open_path')
            self.assertIn('fill="none"',(root/'out/element.svg').read_text())
            self.assertTrue(Path(result['diagnostics']['context']['full_render']).is_file())

    def test_user_bezier_path_roundtrip_keeps_control_points(self):
        controls=[[0,0],[10,25],[35,25],[50,0]]
        path=ct._decode_revision_path([{'type':'cubic','control':controls},
                                     {'type':'line','start':[50,0],'end':[0,0]}])
        np.testing.assert_array_equal(path[0]['control'],controls)
        self.assertIn('C10.000,25.000',ct._path_data(path))

    def test_open_edge_trace_follows_connected_pixels_and_refuses_gaps(self):
        edges=np.zeros((20,20),bool)
        edges[8,2:17]=True
        points=geo.trace_edge_path(edges,(2,8),(16,8))
        self.assertAlmostEqual(points[0,0],2.5)
        self.assertAlmostEqual(points[-1,0],16.5)
        edges[:,9]=False
        with self.assertRaises(geo.GeometryError):
            geo.trace_edge_path(edges,(2,8),(16,8))

    def test_unknown_mask_roundtrip_preserves_exact_pixels(self):
        import contour_diagnostics as cd
        mask = np.zeros((12, 15), bool)
        mask[2:6, 3:8] = True
        np.testing.assert_array_equal(cd.decode_mask(cd.encode_mask(mask), mask.shape), mask)

    def test_context_preserves_original_and_excludes_hidden_pixels(self):
        import contour_diagnostics as cd
        from PIL import Image
        with tempfile.TemporaryDirectory() as work:
            root = Path(work)
            source = root/'source.png'
            original = np.full((20, 20, 3), 30, dtype=np.uint8)
            Image.fromarray(original).save(source)
            before = source.read_bytes()
            output = root/'result'
            output.mkdir()
            (output/'diagnostics').mkdir()
            polygon = np.array([[2,2],[10,2],[10,10],[2,10]],float)
            rgba = geo.render_layers((12,12), [{'kind':'fill','polygon':polygon,'fill':[100,100,100]}])
            unknown = np.zeros((12,12),bool)
            unknown[4:7,4:7] = True
            result = cd.write_context(output, source, original.astype(float), (4,4,12,12), rgba, unknown, polygon)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(Path(result['original']).read_bytes(), before)
            full = np.array(Image.open(result['full_render']))
            np.testing.assert_array_equal(full[8:11,8:11],original[8:11,8:11])
            self.assertEqual(result['metrics']['unknown_pixels_excluded'],9)
            self.assertTrue(Path(result['sdf']).is_file())

    def test_sdf_measures_segments_independently_of_sample_spacing(self):
        polygon = np.array([[2.2, 2.2], [12.2, 2.2], [12.2, 12.2], [2.2, 12.2]])
        field = geo.signed_distance(polygon, (16, 16), spacing=20)
        self.assertAlmostEqual(field[7, 1], 0.7, places=7)
        self.assertAlmostEqual(field[7, 2], -0.3, places=7)

    def test_unknown_pixels_never_enter_appearance_metrics(self):
        source = np.zeros((20, 20, 3))
        rendered = source.copy()
        rendered[7:13, 7:13] = 255
        unknown = np.zeros((20, 20), dtype=bool)
        unknown[7:13, 7:13] = True
        result = ct._metrics(source, rendered, np.ones((20, 20)), np.ones((20, 20), bool),
                             np.ones((20, 20), bool), 0, [], None, unknown)
        self.assertEqual(result['appearance']['interior']['mae_rgb'], 0)
        self.assertEqual(result['appearance']['interior']['pixels'], 364)

    def test_real_saturated_ui_is_not_automatically_removed(self):
        self.assertFalse(inspect.signature(ct.analyze_element).parameters['markup_filter'].default)

    def test_outside_exclusion_does_not_wrap_negative_slices(self):
        mask = ct._exclusion_mask((10, 10), [{'x': -5, 'y': 0, 'width': 3, 'height': 5}], (0, 0))
        self.assertFalse(mask.any())

    def test_compound_shape_keeps_hole_transparent(self):
        outer = np.array([[1, 1], [15, 1], [15, 15], [1, 15]], float)
        hole = np.array([[5, 5], [11, 5], [11, 11], [5, 11]], float)
        rendered = geo.render_layers((17, 17), [{'kind': 'fill', 'polygon': outer,
                                     'holes': [hole], 'fill': [200, 100, 50]}])
        self.assertEqual(rendered[8, 8, 3], 0)
        self.assertEqual(rendered[3, 3, 3], 255)

    def test_open_quadratic_is_editable_without_artificial_closing_segment(self):
        t = np.linspace(0, 1, 100)[:, None]
        controls = np.array([[0, 0], [20, 35], [50, 5]], float)
        samples = (1-t)**2*controls[0] + 2*(1-t)*t*controls[1] + t*t*controls[2]
        primitives = geo.fit_open_primitives(samples, tolerance=0.2)
        self.assertEqual(len(primitives), 1)
        self.assertEqual(primitives[0]['type'], 'quadratic')
        path = ct._path_data(primitives, closed=False)
        self.assertIn('Q', path)
        self.assertFalse(path.endswith('Z'))


if __name__ == '__main__':
    unittest.main()
