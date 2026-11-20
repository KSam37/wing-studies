import _paths  # noqa: F401  (repo root on sys.path)
import unittest
from wingstudy.wing_atlas import conditions,select,sample


class AtlasChecks(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(key=str(i),load_scope='single',cohort='a',generations=['current','old'] if i==0 else ['old'],studies=['one','two'] if i==0 else ['two'],span=.2+i*.01,root=.1,torque=i+.1,thrust=i*2,area=.02) for i in range(30)]
        self.b={'rows':self.rows+[dict(self.rows[0],key='paired',load_scope='paired',cohort='b',torque=None)],'cohorts':[{'id':'a'},{'id':'b'}]}
    def test_all_points_remain_while_silhouettes_are_sampled(self):
        rows,x,y,c=select(self.b,{})
        self.assertEqual(len(rows),30)
        chosen=sample(rows,x,y,5)
        self.assertEqual(len(chosen),5)
        self.assertEqual(chosen,sample(rows,x,y,5))
        self.assertTrue(all(r in rows for r in chosen))
        self.assertEqual(len(rows),30)
    def test_aliases_keep_reused_cases_in_each_source_filter(self):
        self.assertEqual(len(select(self.b,{'generations':['current'],'study':'two'})[0]),1)
        self.assertEqual(len(select(self.b,{'generations':['old'],'study':'one'})[0]),1)
    def test_paired_moment_is_never_substituted_for_single_root_torque(self):
        self.assertEqual(select(self.b,{'cohort':'b'})[0],[])
        self.assertEqual(len(select(self.b,{'cohort':'b','x':'span'})[0]),1)
    def test_filters_and_invalid_ranges(self):
        self.assertEqual(len(select(self.b,{'xmin':10,'xmax':12})[0]),2)
        for p in ({'span_min':.4,'span_max':.1},{'xmin':'nan'},{'cohort':'unknown'}):
            with self.assertRaises(ValueError):select(self.b,p)
    def test_conditions_use_effective_case_values(self):
        r={'_settings':{'frequency_hz':1,'dt_s':.02},'_study':'one','frequency_hz':2,'simulation_mode':'isolated_single_wing_v1','_verified':True}
        a=conditions(r);b=conditions(dict(r,dt_s=.03))
        self.assertEqual(a['frequency_hz'],2)
        self.assertNotEqual(a,b)


if __name__=='__main__':unittest.main()
