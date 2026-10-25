import copy
import unittest
import numpy as np
import model
from wing_curves import fit_profile,smooth_wing


class CurveChecks(unittest.TestCase):
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
        self.assertEqual(result['design']['sections'],wing['sections'])

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
        self.assertEqual(result['design']['sections'][::2],wing['sections'])
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
        self.assertEqual(result['design']['sections'][::3],wing['sections'])
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


if __name__=='__main__':unittest.main()
