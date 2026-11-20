import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from shapely.geometry import Polygon,Point
from shapely.ops import unary_union
from wingstudy import model
import wing_template as template


class TemplateChecks(unittest.TestCase):
    def fake(self,span=380,chords=(200,180,160,140,120,100,80,60)):
        xs=np.linspace(0,span,len(chords));le=[np.array([0.,x/1000]) for x in xs];te=[np.array([c/1000,x/1000]) for c,x in zip(chords,xs)]
        return SimpleNamespace(flat_pattern=lambda c,s:(le,te)),{'id':'case_0001'},{}
    def test_frame_reconstructs_exact_outline_and_all_chord_ribs(self):
        fake,c,s=self.fake();b=template.build(fake,c,s)
        self.assertEqual(len(b['parts']),2)
        self.assertTrue(b['outer'].covers(b['frame']))
        self.assertLess(unary_union([p['polygon'] for p in b['parts']]).symmetric_difference(b['frame']).area,1e-7)
        for a,z in b['chords'][1:-1]:
            center=np.mean([a,z],axis=0)
            self.assertTrue(b['frame'].covers(Point(center)))
            self.assertTrue(b['frame'].covers(Point(center+[.99,0])))
            self.assertFalse(b['frame'].covers(Point(center+[1.01,0])))
        self.assertLess(b['reconstruction_error_mm2'],1e-7)
        # Matching teeth partition the same rib without enlarging the frame.
        from shapely.geometry import LineString
        joint=b['joints'][0];self.assertTrue(joint['active'])
        seam=LineString(joint['points']);shared=b['parts'][0]['polygon'].boundary.intersection(b['parts'][1]['polygon'].boundary)
        self.assertLess(shared.hausdorff_distance(seam),1e-7)
        chord=b['chords'][joint['chord']-1]
        self.assertGreater(seam.length,LineString(chord).length)
        self.assertAlmostEqual(joint['minimum_nominal_half_rib_mm'],.65)
        self.assertEqual(joint['points'][0],list(chord[0]));self.assertEqual(joint['points'][-1],list(chord[1]))
    def test_small_wing_is_not_split_unnecessarily_and_can_rotate(self):
        fake,c,s=self.fake(span=180);self.assertEqual(len(template.build(fake,c,s)['parts']),1)
        layout=template.bed_layout(Polygon([(0,0),(300,0),(300,10),(0,10)]))
        self.assertIsNotNone(layout);self.assertNotEqual(layout[1],0)
        self.assertIsNone(template.bed_layout(Polygon([(0,0),(400,0),(400,400),(0,400)])))
    def test_reject_unprintable_bay_and_nonflattenable_wing(self):
        fake,c,s=self.fake(span=500,chords=(500,500))
        with self.assertRaisesRegex(ValueError,'cannot fit'):template.build(fake,c,s)
        with patch.object(model,'flat_pattern',side_effect=ValueError('Twisted surface')):
            with self.assertRaisesRegex(ValueError,'Twisted'):template.build(model,{'id':'case_0001'},s)
    def test_saved_smooth_zero_tip_is_preserved_with_curve_error_bound(self):
        from wingstudy.wing_curves import pack_curve
        from scipy.interpolate import PchipInterpolator
        anchors=[{'y_m':y,'x_m':0.,'chord_m':c,'pitch_deg':0.,'roll_deg':0.} for y,c in ((0,.2),(.2,.12),(.38,0))]
        c={'id':'case_0001','outline_function':{'span_m':.38,'anchors':anchors,'sample_sections':anchors,
            'leading':pack_curve(PchipInterpolator([0,1],[0,0])),
            'chord':pack_curve(PchipInterpolator([0,.2/.38,1],[.2,.12,0]))}}
        b=template.build(None,c,{})
        self.assertAlmostEqual(b['outer'].bounds[2],380,places=8)
        self.assertTrue(b['outer'].covers(Point(380,0)))
        self.assertEqual(len(b['chords']),3)
        self.assertEqual(b['chords'][-1][0],b['chords'][-1][1])
    def test_actual_stl_archive_reload_and_cache_do_not_mutate_sources(self):
        import trimesh,zipfile
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            root=Path(tmp);study=root/'study';study.mkdir();(study/'case_0001').mkdir()
            case={'id':'case_0001','geometry':{'stations':[
                {'le':[0,y,0],'te':[.2-y/3,y,0],'chord_m':.2-y/3} for y in np.linspace(0,.38,8)]},
                'sections':[{'y_m':y,'x_m':0,'chord_m':.2-y/3,'pitch_deg':0,'roll_deg':0} for y in np.linspace(0,.38,8)]}
            manifest={'cases':[case],'settings':{'gap_m':.04}};model.write_json(study/'manifest.json',manifest)
            original=(study/'manifest.json').read_bytes()
            with patch.object(model,'OUTPUTS',root):
                out=template.export(model,study,'case_0001')
                self.assertEqual(out['part_count'],2)
                with zipfile.ZipFile(root/out['file']) as archive:
                    names=[n for n in archive.namelist() if n.endswith('.stl')];self.assertEqual(len(names),2)
                    for name in names:
                        with archive.open(name) as stream:mesh=trimesh.load_mesh(stream,file_type='stl',process=True)
                        self.assertTrue(mesh.is_watertight and mesh.is_volume)
                        self.assertAlmostEqual(mesh.extents[2],3)
                        self.assertLessEqual(max(mesh.extents[:2]),248.001)
                with patch.object(template,'build',side_effect=AssertionError('Cached export must not rebuild')):
                    self.assertEqual(template.export(model,study,'case_0001')['file'],out['file'])
            self.assertEqual((study/'manifest.json').read_bytes(),original)

    def test_smooth_bent_function_exports_full_zero_tip_as_closed_parts(self):
        from scipy.interpolate import PchipInterpolator
        from wingstudy.wing_curves import pack_curve
        import math,zipfile,trimesh
        anchors=[{'y_m':y,'x_m':0.,'chord_m':c,'pitch_deg':0.,'roll_deg':20.} for y,c in ((0,.2),(.2,.12),(.38,0))]
        case={'id':'case_0001','outline_function':{'span_m':.38,'anchors':anchors,'sample_sections':anchors,
            'leading':pack_curve(PchipInterpolator([0,1],[0,0])),
            'chord':pack_curve(PchipInterpolator([0,.2/.38,1],[.2,.12,0]))}}
        built=template.build(model,case,{})
        self.assertAlmostEqual(built['outer'].bounds[2],380/math.cos(math.radians(20)),places=7)
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            root=Path(tmp);study=root/'study';(study/'case_0001').mkdir(parents=True)
            model.write_json(study/'manifest.json',{'cases':[case],'settings':{'gap_m':.04}})
            with patch.object(model,'OUTPUTS',root):
                result=template.export(model,study,'case_0001')
                self.assertEqual(result['part_count'],2)
                with zipfile.ZipFile(root/result['file']) as archive:
                    for name in (n for n in archive.namelist() if n.endswith('.stl')):
                        with archive.open(name) as stream:mesh=trimesh.load_mesh(stream,file_type='stl',process=True)
                        self.assertTrue(mesh.is_watertight and mesh.is_volume)


if __name__=='__main__':unittest.main()
