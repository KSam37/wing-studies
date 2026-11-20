import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wingstudy import adaptive
from wingstudy import model
from wingstudy import torque_search as search
from wingstudy import torque_frontier
import test_adaptive
from test_torque_study import row


class TorqueSearchChecks(unittest.TestCase):
    def config(self):
        c=test_adaptive.AdaptiveChecks().config()
        c['adaptive_search'].update(acceptance_rule='torque_curve',budget_only=True,
            seed_families=['triangle','square','narrow'],simulation_budget=60,
            curve_torque_min_nm=1.,curve_torque_max_nm=7.,curve_torque_samples=4)
        return c

    def test_shared_best_crosses_family_and_parent_torque(self):
        rectangle={'span':.8,'row':row('rectangle',11.6,14.4),'chords':[.2]*3}
        convex={'span':.8,'row':row('convex',11.0,9.15),'chords':[.2,.15,.01]}
        candidate={'span':.8,'row':row('candidate',12.98,12.21),'chords':[.2,.19,.01]}
        pool=[rectangle,convex,candidate]
        self.assertEqual(search.best(pool,.8,14.4)['row']['id'],'candidate')
        self.assertEqual(search.best(pool,.8,10)['row']['id'],'convex')
        self.assertIsNone(search.best(pool,.4,100))
        self.assertIsNone(search.best(pool,.8,1))

    def test_grid_validation_and_automatic_bounds(self):
        c=self.config();r=adaptive.options(model,c)
        spec=adaptive.plan(model,c)
        self.assertEqual(spec['search_job_count'],4)
        self.assertEqual(spec['config']['optimization']['constraint'],'peak_root_torque_le_available_target')
        sample={'row':row('seed',1,2),'span':.6,'chords':[.1]*3}
        self.assertEqual(search.target_levels(r,[sample]),[1,3,5,7])
        r.update(curve_torque_min_nm=None,curve_torque_max_nm=None,curve_torque_samples=3)
        self.assertEqual(search.target_levels(r,[sample]),[1,1.75,2.5])
        c['adaptive_search'].update(curve_torque_min_nm=3,curve_torque_max_nm=2)
        with self.assertRaises(ValueError):adaptive.options(model,c)

    def test_redistribution_always_present_and_feasible(self):
        r=adaptive.options(model,self.config());s={'span':.6,'chords':[.15,.1,.05],'row':row('s',1,1)}
        r['coordinated_moves']=False
        basis=search.poll_directions(s,[s],r,[.01]*3)
        self.assertTrue(any(min(v)<0<max(v) for v,k in basis))
        from wingstudy.pareto_poll import candidate
        proposals=[candidate(s['chords'],v,[.01]*3,r,adaptive.valid) for v,k in basis]
        self.assertTrue(all(adaptive.valid(p,r) for p in proposals if p))

    def test_full_search_saves_feasible_monotone_curve_with_strict_budget(self):
        r=adaptive.options(model,self.config())
        class Pipeline:
            stop_reason=None
            def __init__(self,study):self.model=model;self.study=study;self.lookup={};self.rows=[];self.events=[]
            def evaluate_many(self,inputs):
                output=[]
                for chords,meta in inputs:
                    key=(meta['span_m'],tuple(chords))
                    if key not in self.lookup:
                        if len(self.rows)>=r['simulation_budget']:self.stop_reason='New-simulation budget reached';break
                        value=10*sum(chords);result=row(f'case_{len(self.rows)+1:04d}',value,value)
                        result.update(seed_family=meta['seed_family'],adaptive_trial=meta)
                        self.lookup[key]=result;self.rows.append(result)
                    output.append(self.lookup[key])
                return output
            def accept(self,event):self.events.append(copy.deepcopy(event))
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            p=Pipeline(Path(temp))
            try:search.run(r,p)
            except adaptive.BudgetReached:pass
            self.assertLessEqual(len(p.rows),60)
            data=model.read_json(p.study/'torque_targets.json')['targets']
            valid=[d for d in data if d['case_id']]
            self.assertTrue(valid)
            for d in valid:
                self.assertLessEqual(d['peak_root_torque_Nm'],d['available_root_torque_Nm'])
                feasible=[x['single_wing_mean_thrust_N'] for x in p.rows if x['single_wing_peak_abs_roll_moment_Nm']<=d['available_root_torque_Nm']]
                self.assertEqual(d['mean_thrust_N'],max(feasible))
            self.assertEqual([d['mean_thrust_N'] for d in valid],sorted(d['mean_thrust_N'] for d in valid))
            lookup={x['id']:x for x in p.rows}
            self.assertTrue(any(e.get('parent_case') and e['case']['single_wing_peak_abs_roll_moment_Nm']>lookup[e['parent_case']]['single_wing_peak_abs_roll_moment_Nm'] for e in p.events))
            self.assertTrue((p.study/'comparisons/torque_curve.csv').exists())
            adjustments={max(x['adaptive_trial']['poll_steps_m']) for x in p.rows if x['adaptive_trial'].get('poll_steps_m')}
            self.assertIn(.02,adjustments)
            self.assertIn(.01,adjustments)

    def test_zero_outboard_is_default_but_two_positive_sections_remain(self):
        c=self.config();c['adaptive_search'].update(node_count=5)
        r=adaptive.options(model,c)
        self.assertEqual([b['min_m'] for b in r['bounds']],[.01,.01,0,0,0])
        self.assertTrue(adaptive.valid([.2,.1,0,0,0],r))
        self.assertFalse(adaptive.valid([.2,0,0,0,0],r))
        self.assertFalse(adaptive.valid([.2,.1,0,.01,0],r))

    def test_primary_view_uses_current_target_winners_not_superseded_events(self):
        old=row('case_0001',1,1);new=row('case_0002',2,2);trial=row('case_0003',3,4)
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp,patch.object(model,'OUTPUTS',Path(temp)):
            study=Path(temp)/'saved';study.mkdir()
            model.write_json(study/'evolution.json',[{'case':old,'parent_case':None,'kind':'seed'},
                {'case':new,'parent_case':old['id'],'kind':'winner'},{'case':trial,'parent_case':None,'kind':'winner'}])
            model.write_json(study/'torque_targets.json',{'targets':[{'case_id':new['id'],'available_root_torque_Nm':3}]})
            rows=[{**x,'_study':'saved'} for x in (old,new,trial)]
            chosen=torque_frontier.evolution_rows(model,rows,False)
            self.assertEqual([x['id'] for x in chosen],[new['id']])
            self.assertEqual(chosen[0]['available_torque_targets_Nm'],[3])


if __name__=='__main__':unittest.main()
