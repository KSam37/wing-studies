import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wingstudy import model
from wingstudy import catalog
from wingstudy import torque_study as torque


def row(name,thrust,moment,**extra):
    return dict(id=name,status='ok',simulation_mode=model.SIMULATION_MODE,
        single_wing_mean_thrust_N=thrust,single_wing_peak_abs_roll_moment_Nm=moment,
        estimated_two_wing_mean_thrust_N=2*thrust,cycle_repeatable=True,**extra)


class TorqueChecks(unittest.TestCase):
    def test_full_range_overview_has_no_cutoff_or_single_winner(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'study';study.mkdir()
            model.write_json(study/'manifest.json',{'settings':{},'config':{'optimization':{'max_root_moment_nm':.1}}})
            model.write_json(study/'results.json',[row('low',1,.1),row('dominated',.9,.3),row('high',5,10)])
            with patch.object(model,'OUTPUTS',root):
                result=torque.overview(model,'study')
            self.assertEqual(result['eligible_count'],3)
            self.assertEqual(result['frontier_count'],2)
            self.assertNotIn('maximum_root_moment_nm',result)
            self.assertNotIn('winner',result)
            self.assertEqual(result['rows'][0]['id'],'low')
            self.assertEqual([r['ratio_rank'] for r in result['rows']],[1,2,3])
            self.assertEqual({r['id'] for r in result['rows'] if r['is_frontier']},{'low','high'})
            self.assertEqual({r['torque_status'] for r in result['rows']},{'Eligible','Frontier'})

    def test_overview_span_tabs_filter_actual_span_and_rank_by_ratio(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'study';study.mkdir()
            model.write_json(study/'manifest.json',{'settings':{'gap_m':.04}})
            model.write_json(study/'results.json',[row('a',1,.5,span_m=.4),row('b',5,5,span_m=.4),row('c',2,.1,span_m=.8)])
            with patch.object(model,'OUTPUTS',root):
                all_rows=torque.overview(model,'study')
                selected=torque.overview(model,'study',span_class='0.4')
            self.assertEqual([r['id'] for r in all_rows['rows']],['c','a','b'])
            self.assertEqual([r['id'] for r in selected['rows']],['a','b'])
            self.assertEqual(selected['span_class'],'0.4')
            self.assertEqual([s['key'] for s in selected['span_classes']],['0.4','0.8'])
            self.assertEqual(selected['rows'][0]['ratio_rank'],1)

    def test_editable_workflow_defaults(self):
        original=copy.deepcopy(model.DEFAULT);c=torque.default_config(model)
        self.assertEqual(c['optimization']['max_root_moment_nm'],.625)
        self.assertEqual(c['shape_sweep']['span_m'],.8)
        self.assertEqual(c['shape_sweep']['ranges'][0],{'min_m':.12,'max_m':.2,'count':3})
        self.assertEqual(c['settings']['frequency_hz'],1)
        self.assertEqual(c['settings']['amplitude_deg'],30)
        self.assertEqual(c['motion_range'],{'minimum_deg':-26,'maximum_deg':34})
        self.assertEqual(model.DEFAULT,original)
        self.assertGreater(model.plan(c)['case_count'],0)

    def config(self,limit=.5):
        c=copy.deepcopy(model.DEFAULT);c.update(workflow='root_torque',optimization={'max_root_moment_nm':limit},
            motion_range={'minimum_deg':-26,'maximum_deg':34})
        return c

    def test_rank_maximizes_thrust_not_ratio_and_accepts_equality(self):
        r=torque.rank([row('a',10,1),row('b',8,.1),row('c',20,1.01)],1)
        self.assertEqual(r['winner']['id'],'a');self.assertEqual(r['feasible_count'],2)
        self.assertEqual(r['rows'][-1]['torque_status'],'Over limit')
        self.assertEqual(r['winner']['root_moment_margin_Nm'],0)

    def test_no_feasible_winner_and_failed_unsettled_or_flexible_excluded(self):
        rows=[row('over',10,2),row('settling',10,.1),row('flexible',10,.1),row('paired',10,.1),row('failed',10,.1)]
        rows[1]['cycle_repeatable']=False;rows[2]['aeroelastic_enabled']=True
        rows[3]['simulation_mode']='legacy_paired';rows[4]['status']='failed'
        r=torque.rank(rows,.5);self.assertIsNone(r['winner']);self.assertEqual(r['feasible_count'],0)

    def test_invalid_loads_and_nonpropulsive_cases_do_not_rank(self):
        for thrust,moment in [(float('nan'),1),(1,float('inf')),(1,-1),(0,0),(-1,.1)]:
            self.assertIsNone(torque.rank([row('bad',thrust,moment)],1)['winner'])
        self.assertEqual(torque.rank([row('zero_moment',1,0)],1)['winner']['id'],'zero_moment')
        for limit in [None,0,-1,float('nan'),True]:
            with self.assertRaises(ValueError):torque.rank([],limit)

    def test_workflow_is_rigid_and_uses_requested_offset_sinusoid(self):
        c=self.config();c['settings']['aeroelastic_enabled']=True;original=copy.deepcopy(c)
        p=model.plan(c)
        self.assertEqual(c,original);self.assertFalse(p['settings']['aeroelastic_enabled'])
        self.assertFalse(p['settings']['tail']['enabled'])
        self.assertEqual(p['objective'],'single_wing_mean_thrust_N')
        self.assertAlmostEqual(p['motion_preview']['minimum_deg'],-26,delta=.02)
        self.assertAlmostEqual(p['motion_preview']['maximum_deg'],34,delta=.02)
        self.assertEqual(p['settings']['frequency_hz'],1)
        self.assertIsNotNone(model.build_solver(p['cases'][0],p['settings']))

    def test_limit_does_not_change_physics_or_prevent_catalog_reuse(self):
        a=model.plan(self.config(.5));b=model.plan(self.config(2))
        self.assertEqual(a['settings'],b['settings']);self.assertEqual(a['cases'],b['cases'])
        self.assertEqual(catalog.signature(model,a['cases'][0],a['settings']),catalog.signature(model,b['cases'][0],b['settings']))
        self.assertEqual(model.plan(a['config'])['settings'],a['settings'])

    def test_exports_and_top_performers_use_constraint_not_old_objective(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            p=Path(temp)/'test';p.mkdir();c=self.config(1);spec=model.plan(c)
            rows=[row('a',10,1),row('b',8,.1),row('over',20,2)]
            # Deliberately set the old ratio to favor the wrong design.
            for i,r in enumerate(rows):r.update(shape_ratio_valid=True,single_wing_thrust_roll_ratio_1pm=100*i)
            model.write_json(p/'manifest.json',spec)
            with patch.object(model,'OUTPUTS',Path(temp)):
                model.write_summary(p,rows);result=torque.results(model,p,export=True)
            self.assertEqual(result['winner']['id'],'a')
            with (p/'comparisons/top_performers.csv').open() as f:
                self.assertEqual([r['id'] for r in csv.DictReader(f)],['a','b'])
            self.assertTrue((p/'comparisons/thrust_under_root_limit.png').is_file())
            with (p/'comparisons/thrust_under_root_limit.csv').open() as f:
                exported=list(csv.DictReader(f));self.assertEqual(len(exported),3)
                self.assertEqual(exported[0]['id'],'a');self.assertEqual(exported[-1]['torque_status'],'Over limit')
            before=(p/'results.json').read_bytes();torque.results(model,p,.05)
            self.assertEqual((p/'results.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
