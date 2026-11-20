import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import unittest
from wingstudy.span_frontier import frontier, band_frontier, allow_nominal_settings

class FrontierSelectionTests(unittest.TestCase):
    def test_dominated_and_equal_torque_points(self):
        c={'T':[2,1,3,3,2],'Q':[1,1,2,3,2]}
        self.assertEqual(frontier(range(5),c),[0,2])
    def test_keeps_tradeoffs_without_torque_ceiling(self):
        c={'T':[1,2,20],'Q':[.1,1,30]}
        self.assertEqual(frontier(range(3),c),[0,1,2])
    def test_nominal_preserves_thickness_and_rod(self):
        cases=[dict(needs_source_settings=True,has_rod=r,thickness_mm=t,chords=[200,100],half_span=300,freq=1.25) for r,t in [(True,.25),(False,1.)]]
        plan=allow_nominal_settings({'cases':cases})
        self.assertEqual(cases[0]['rod']['hollow_inner_diameter_m'],.003)
        self.assertEqual(cases[1]['rod'],{})
        self.assertEqual([w['thickness_mm'] for w in cases],[.25,1.])
        self.assertEqual(cases[0]['numerics']['dt_s'],.016)
        self.assertEqual(cases[0]['numerics']['cycles'],4)
        self.assertNotEqual(cases[0]['key'],cases[1]['key'])
        old=cases[0]['key'];allow_nominal_settings(plan);self.assertEqual(old,cases[0]['key'])
    def test_band_keeps_highest_thrust(self):
        c={'T':[1,2,3,4],'Q':[.001,.009,.011,.02]}
        self.assertEqual(band_frontier(range(4),c,.01),[1,2,3])
    def test_duplicates_and_permutation(self):
        c={'T':[2,2,3],'Q':[1,1,2]}
        self.assertEqual(frontier([2,1,0],c),[0,2])

if __name__=='__main__':unittest.main()
