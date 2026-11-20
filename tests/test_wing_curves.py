import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import unittest
import numpy as np
from wingstudy import model
from wingstudy.wing_curves import fit_profile,smooth_wing
from wingstudy.wing_curves import function_wing,polynomial_expression,unpack_curve
import tempfile
import xml.etree.ElementTree as ET
import json
import re
from pathlib import Path
from unittest.mock import patch


class CurveChecks(unittest.TestCase):
    def test_export_only_smoothing_preserves_simulation_and_original_files(self):
        from wingstudy.wing_curves import export_smooth_profiles
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            study=Path(temp)/'study';folder=study/'case_0001';folder.mkdir(parents=True)
            case={'id':'case_0001',**self.wing([.2,.15,.11,.06])}
            case['design_name']=case.pop('name')
            model.write_json(study/'manifest.json',{'cases':[case]})
            model.write_json(study/'results.json',[{'id':'case_0001','single_wing_mean_thrust_N':2.}])
            (folder/'wing_left.svg').write_text('Original left')
            (folder/'wing_right.svg').write_text('Original right')
            originals={p:p.read_bytes() for p in study.rglob('*') if p.is_file()}
            with patch.object(model,'build_solver',side_effect=AssertionError('No meshing')),patch.object(model,'run_case',side_effect=AssertionError('No solve')),patch.object(model,'plan',side_effect=AssertionError('No study planning')):
                result=export_smooth_profiles(model,study,'case_0001')
            for path,data in originals.items():self.assertEqual(path.read_bytes(),data)
            self.assertEqual(sorted(p.name for p in folder.iterdir()),['wing_left.svg','wing_right.svg','wing_smooth_left.svg','wing_smooth_right.svg'])
            ns={'s':'http://www.w3.org/2000/svg'}
            for name in ('wing_smooth_left.svg','wing_smooth_right.svg'):
                root=ET.parse(folder/name).getroot()
                self.assertTrue(root.get('width').endswith('mm'))
                self.assertIn('C',root.find('s:path',ns).get('d'))
                meta=json.loads(root.find('s:metadata',ns).text)
                self.assertTrue(meta['export_only_smoothing']);self.assertFalse(meta['simulated'])
                self.assertEqual(meta['source_sections'][-1]['chord_m'],.06)
                curve=unpack_curve(meta['function']['chord'])
                self.assertAlmostEqual(float(curve(1)),0)
                for s in case['sections'][:-1]:self.assertAlmostEqual(float(curve(s['y_m']/.3)),s['chord_m'])
            self.assertEqual(len(result['files']),2)
            # Repeat conversion replaces the same two exports without new folders.
            export_smooth_profiles(model,study,'case_0001')
            self.assertEqual(len(list(folder.iterdir())),4)

    def wing(self,chords):
        return {'name':'Test wing','sections':[{'y_m':.3*i/(len(chords)-1),'x_m':0.,
            'chord_m':c,'pitch_deg':0.,'roll_deg':0.} for i,c in enumerate(chords)]}

    def test_lowest_degree_and_no_need_to_subdivide_straight_edges(self):
        for degree,values in [(0,[.1,.1,.1]),(1,[.2,.15,.1]),(2,[.2,.175,.1]),(3,[.2,.1875,.1])]:
            t=np.array([0.,.5,1.]) if degree<3 else np.linspace(0,1,5)
            if degree==3:values=.2-.1*t**3
            curve,info=fit_profile(t,values)
            self.assertEqual(info['degree'],degree);self.assertEqual(info['method'],'polynomial')
            np.testing.assert_allclose(curve(t),values,atol=1e-12)
        wing=self.wing([.2,.15,.1]);result=smooth_wing(model,wing,model.DEFAULT['settings'],4)
        self.assertEqual(result['design']['sections'][-1]['chord_m'],0.)
        self.assertEqual(result['design']['sections'][0],wing['sections'][0])

    def test_piecewise_curve_passes_anchors_without_chord_overshoot(self):
        t=np.linspace(0,1,5);v=np.array([.3,.1,.05,.03,.03]);curve,info=fit_profile(t,v)
        self.assertEqual(info['method'],'shape-preserving piecewise cubic')
        np.testing.assert_allclose(curve(t),v,atol=1e-14)
        for i in range(4):
            sampled=curve(np.linspace(t[i],t[i+1],101))
            self.assertGreaterEqual(sampled.min(),v[i+1]-1e-14)
            self.assertLessEqual(sampled.max(),v[i]+1e-14)
        wing=self.wing(v.tolist());original=copy.deepcopy(wing)
        result=smooth_wing(model,wing,model.DEFAULT['settings'],2)
        expected=copy.deepcopy(wing['sections']);expected[-1]['chord_m']=0.
        self.assertEqual(result['design']['sections'][::2],expected)
        self.assertEqual(wing,original)
        self.assertEqual(result['required_span_panels'],8)
        settings={**model.DEFAULT['settings'],'span_panels':8}
        c=copy.deepcopy(model.DEFAULT);c.update(mode='custom',designs=[result['design']],settings=settings)
        p=model.plan(c);self.assertIsNotNone(model.build_solver(p['cases'][0],p['settings']))

    def test_quadratic_bent_wing_preserves_original_angles_and_leading_edge_heights(self):
        wing=self.wing([.2,.175,.1])
        for s,roll,pitch in zip(wing['sections'],[15.,-10.,0.],[5.,2.,-2.]):
            s['roll_deg']=roll;s['pitch_deg']=pitch;s['x_m']=.1*s['y_m']**2
        result=smooth_wing(model,wing,model.DEFAULT['settings'],3)
        expected=copy.deepcopy(wing['sections']);expected[-1]['chord_m']=0.
        self.assertEqual(result['design']['sections'][::3],expected)
        old=model.custom_frames(wing)[0];new=model.custom_frames(result['design'])[0][::3]
        np.testing.assert_allclose(old,new,atol=1e-14)

    def test_trailing_absent_sections_are_not_used_as_curve_tip(self):
        wing=self.wing([.2,.15,.1,0.]);result=smooth_wing(model,wing,model.DEFAULT['settings'])
        self.assertEqual(result['design']['sections'][-1]['y_m'],wing['sections'][2]['y_m'])
        self.assertEqual(result['fit']['omitted_zero_sections'],1)

    def test_invalid_subdivisions_and_zero_prefix_are_rejected(self):
        for value in [0,17,2.5]:
            with self.assertRaises(ValueError):smooth_wing(model,self.wing([.2,.1]),model.DEFAULT['settings'],value)
        with self.assertRaises(ValueError):smooth_wing(model,self.wing([.2,0.,.1]),model.DEFAULT['settings'])

    def test_duplicate_stations_are_rejected(self):
        wing=self.wing([.2,.15,.1]);wing['sections'][1]['y_m']=0
        with self.assertRaises(ValueError):smooth_wing(model,wing,model.DEFAULT['settings'])

    def test_function_parser_and_zero_tip_constraints(self):
        poly=polynomial_expression('.3*(1-s**2)')
        np.testing.assert_allclose(poly([0,.5,1]),[.3,.225,0])
        for text in ['__import__("os")','s.__class__','s**4','1/s','sin(s)','[s]']:
            with self.assertRaises(ValueError):polynomial_expression(text)
        for expression in ['.3','.3*(1-s)*(.5-s)']:
            with self.assertRaises(ValueError):function_wing(model,'Bad',.3,'0',expression,8,model.DEFAULT['settings'])

    def test_svg_contains_exact_function_paths_to_tip_and_mirrored_scale(self):
        r=function_wing(model,'Quadratic',.4,'.05*s**2','.3*(1-s**2)',8,model.DEFAULT['settings'])
        c=copy.deepcopy(model.DEFAULT);c.update(mode='custom',designs=[r['design']])
        c['settings']['span_panels']=r['required_span_panels'];p=model.plan(c);case=p['cases'][0]
        self.assertLess(case['sections'][-1]['y_m'],.4)
        self.assertIn('outline_function',case)
        with tempfile.TemporaryDirectory() as td:
            meta=model.save_wing_profiles(case,p['settings'],td);self.assertTrue(meta['profile_is_cutting_pattern'])
            ns={'s':'http://www.w3.org/2000/svg'}
            roots=[ET.parse(Path(td)/f'wing_{side}.svg').getroot() for side in ('left','right')]
            self.assertEqual(roots[0].get('width'),roots[1].get('width'))
            for root in roots:
                path=root.find('s:path',ns);self.assertIn('C',path.get('d'));self.assertTrue(path.get('d').endswith('Z'))
                self.assertIsNone(root.find('s:polygon',ns))
                stored=json.loads(root.find('s:metadata',ns).text)['function']
                self.assertAlmostEqual(float(unpack_curve(stored['chord'])(1)),0.)
                self.assertEqual(stored['span_m'],.4)
                scale=root.find("s:line[@id='scale-check']",ns)
                self.assertEqual(float(scale.get('x2'))-float(scale.get('x1')),100.)
            # The SVG's actual Bezier paths, not just its metadata, reproduce
            # the analytic curves at the midpoint (in millimeters).
            path=roots[1].find('s:path',ns).get('d')
            groups=re.findall(r'C([^MLCZ]+)',path)
            controls=[np.array([float(v) for v in group.split()]).reshape(3,2) for group in groups]
            first=np.vstack(([15.,25.],controls[0]))
            second=np.vstack((controls[0][-1],controls[1]))
            weights=np.array([1,3,3,1])/8
            np.testing.assert_allclose(weights@first,[215.,37.5],atol=1e-8)
            np.testing.assert_allclose(weights@second,[215.,262.5],atol=1e-8)

    def test_curve_metadata_is_detached_after_manual_edits(self):
        r=function_wing(model,'Curve',.3,'0','.2*(1-s**2)',8,model.DEFAULT['settings'])
        design=r['design'];design['sections'][1]['chord_m']*=.9
        case=model.custom_case(design,model.DEFAULT['settings'])
        self.assertNotIn('outline_function',case)

    def test_bent_function_svg_and_twisted_projection_label(self):
        wing=self.wing([.2,.175,.1]);wing['sections'][0]['roll_deg']=20
        r=smooth_wing(model,wing,model.DEFAULT['settings']);p=model.plan({**copy.deepcopy(model.DEFAULT),'mode':'custom','designs':[r['design']]})
        with tempfile.TemporaryDirectory() as td:
            self.assertTrue(model.save_wing_profiles(p['cases'][0],p['settings'],td)['profile_is_cutting_pattern'])
        wing['sections'][1]['pitch_deg']=5
        r=smooth_wing(model,wing,model.DEFAULT['settings']);p=model.plan({**copy.deepcopy(model.DEFAULT),'mode':'custom','designs':[r['design']]})
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(model.save_wing_profiles(p['cases'][0],p['settings'],td)['profile_is_cutting_pattern'])


if __name__=='__main__':unittest.main()
