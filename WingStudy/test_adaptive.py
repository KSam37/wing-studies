import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import model
import adaptive
import torque_study
from test_torque_study import row

class AdaptiveChecks(unittest.TestCase):
    def config(self):
        c=torque_study.default_config(model)
        c['adaptive_search']={**adaptive.DEFAULT,'enabled':True,'span_min_m':.6,'span_max_m':.6,'span_count':1,'node_count':3,'decreasing':False}
        return c

    def test_requested_defaults_match_ui_and_form_four_unconstrained_searches(self):
        import re
        c=torque_study.default_config(model);c['adaptive_search']={'enabled':True}
        p=adaptive.plan(model,c)
        r=p['adaptive_search']
        self.assertEqual((r['span_min_m'],r['span_max_m'],r['span_count'],r['node_count']),(.4,.8,4,8))
        self.assertEqual((r['initial_step_m'],r['minimum_step_m']),(.04,.01))
        self.assertNotIn('torque_max_nm',r)
        self.assertEqual(p['config']['optimization']['constraint'],'none')
        self.assertNotIn('max_root_moment_nm',p['config']['optimization'])
        self.assertEqual((r['simulation_budget'],r['evaluation_budget']),(500,1000))
        self.assertEqual(p['search_job_count'],4)
        html=(model.HERE/'workflow.html').read_text(encoding='utf-8')
        for field,key in {'adaptiveSpanMin':'span_min_m','adaptiveSpanMax':'span_max_m','adaptiveSpanCount':'span_count','adaptiveNodes':'node_count','adaptiveStep':'initial_step_m','adaptiveMinStep':'minimum_step_m','adaptiveBudget':'simulation_budget','adaptiveEvaluations':'evaluation_budget'}.items():
            value=re.search('id="'+field+'"[^>]*value="([^"]+)"',html)[1]
            self.assertEqual(float(value),r[key])

    def test_plan_roundtrip_fixed_span_chord_floor_and_native_mesh(self):
        c=self.config();before=copy.deepcopy(c);p=adaptive.plan(model,c)
        self.assertEqual(c,before)
        self.assertEqual(p['cases'],adaptive.plan(model,p['config'])['cases'])
        self.assertEqual(p['simulation_budget'],500)
        case=p['cases'][0]
        self.assertAlmostEqual(case['span_m'],.6)
        self.assertTrue(all(s['chord_m']>=.01 for s in case['sections']))
        self.assertIsNotNone(model.build_solver(case,p['settings']))
        for key,value in [('minimum_chord_m',.001),('tip_chord_m',0),('minimum_step_m',.1),('span_max_m',.4),('shrink_factor',1)]:
            invalid=copy.deepcopy(c);invalid['adaptive_search'][key]=value
            with self.assertRaises(ValueError):adaptive.plan(model,invalid)

    def test_native_aeroelastic_opt_in_preserves_material_inputs_and_cache_identity(self):
        import catalog
        import pterasoftware as ps
        c=self.config();rigid=adaptive.plan(model,c)
        c['settings'].update(aeroelastic_enabled=True,spring_constant_rad=4.27,damping_constant_rad=10.,wing_density=.5,step_discards=5)
        p=adaptive.plan(model,c)
        self.assertTrue(p['settings']['aeroelastic_enabled'])
        self.assertEqual(p['settings']['damping_constant_rad'],10)
        solver=model.build_solver(p['cases'][0],p['settings'])
        self.assertIsInstance(solver.unsteady_problem,ps.AeroelasticUnsteadyProblem)
        self.assertTrue(all(case['aeroelastic_enabled'] for case in p['cases']))
        self.assertNotEqual(catalog.signature(model,p['cases'][0],p['settings']),catalog.signature(model,rigid['cases'][0],rigid['settings']))
        native=row('native',2,.3,aeroelastic_enabled=True)
        self.assertEqual(adaptive.score(native),2/.3)
        self.assertEqual(torque_study.classify(native,.5),'Aeroelastic result excluded')
        self.assertEqual(torque_study.rank([native],.5,allow_aeroelastic=True)['winner']['id'],'native')
        for key,value in [('damping_constant_rad',-1),('spring_constant_rad',0),('wing_density',0),('step_discards',100000)]:
            bad=copy.deepcopy(c);bad['settings'][key]=value
            with self.assertRaises(ValueError):adaptive.plan(model,bad)

    def test_ascent_converges_and_enforces_each_chord_bound(self):
        r=adaptive.options(model,self.config());r['improvement_pct']=.001;accepted=[];evaluations=[]
        target=[.15,.1,.05]
        def evaluate(chords,meta):
            self.assertTrue(adaptive.valid(chords,r));evaluations.append(chords)
            return row(str(len(evaluations)),10-100*sum((c-t)**2 for c,t in zip(chords,target)),1.)
        adaptive.run_search(r,evaluate,accepted.append)
        self.assertGreater(len(accepted),2)
        self.assertGreater(accepted[-1]['case']['single_wing_mean_thrust_N'],9.99)
        self.assertLess(len(evaluations),500)
        thrust=[e['case']['single_wing_mean_thrust_N'] for e in accepted]
        self.assertEqual(thrust,sorted(thrust))

    def test_ratio_acceptance_has_no_torque_ceiling_or_thrust_only_preference(self):
        # Higher absolute torque must be accepted when its ratio is better.
        self.assertTrue(adaptive.better(row('new',20,4),row('old',4,1),.001))
        # Higher thrust alone must not win when its ratio is lower.
        self.assertFalse(adaptive.better(row('new',10,10),row('old',2,.5),.001))
        self.assertTrue(adaptive.better(row('new',2,.4),row('old',4,1),.001))
        bad=row('bad',100,.1);bad['cycle_repeatable']=False
        self.assertFalse(adaptive.better(bad,row('old',1,.4),0))
        for torque in (0,-1,float('nan')):self.assertIsNone(adaptive.score(row('bad',1,torque)))
        c=self.config();c['adaptive_search'].update(torque_min_nm=-100,torque_max_nm=-1,torque_count=0)
        p=adaptive.plan(model,c)
        self.assertNotIn('torque_max_nm',p['adaptive_search'])
        self.assertNotIn('max_root_moment_nm',p['config']['optimization'])

    def test_jobs_are_interleaved_and_decreasing_shapes_stay_valid(self):
        c=self.config();c['adaptive_search'].update(span_min_m=.5,span_max_m=.7,span_count=2,decreasing=True,max_passes=1)
        r=adaptive.options(model,c);jobs=[]
        def evaluate(chords,meta):
            self.assertTrue(adaptive.valid(chords,r));jobs.append(meta['job'])
            return row(str(len(jobs)),sum(chords),sum(chords))
        adaptive.run_search(r,evaluate)
        self.assertEqual(jobs[:2],[1,2])

    def test_app_launch_writes_adaptive_manifest_and_budget_for_worker(self):
        import app
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            out=Path(temp)/'studies';out.mkdir()
            process=SimpleNamespace(pid=123,poll=lambda:None)
            with patch.object(model,'OUTPUTS',out),patch.object(app,'PROCESS',None),patch.object(app,'ACTIVE',None),patch.object(app,'SERVER',SimpleNamespace(server_port=8766)),patch.object(app,'studies',return_value=[]),patch.object(app.subprocess,'check_output',return_value='verification'),patch.object(app.subprocess,'Popen',return_value=process) as launch:
                result=app.start(self.config())
                manifest=model.read_json(out/result['id']/'manifest.json')
                self.assertIn('adaptive_search',manifest)
                import catalog
                self.assertTrue(catalog.verified_import(model,manifest))
                self.assertEqual(manifest['simulation_budget'],500)
                self.assertEqual(manifest['worker_pid'],123)
                self.assertEqual(model.read_json(out/result['id']/'status.json')['total'],500)
                self.assertIn('--worker',launch.call_args.args[0])
                self.assertEqual(str(out/result['id']),launch.call_args.args[0][-1])

    def test_worker_strict_new_solve_budget_and_geometry_dedup(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'studies'/'adaptive';study.mkdir(parents=True)
            c=self.config();c['adaptive_search'].update(simulation_budget=3,evaluation_budget=40)
            spec=adaptive.plan(model,c);spec.update(created='test',ptera_version='test',browser_url='http://localhost')
            model.write_json(study/'manifest.json',spec)
            calls=[]
            def solve(case,settings,directory):
                calls.append(case);return {k:v for k,v in row(case['id'],sum(s['chord_m'] for s in case['sections']),.1).items() if k!='id'}
            def record(m,manifest,name,r):r['global_case_no']=len(calls)
            def summary(path,rows):model.write_json(path/'results.json',rows)
            with patch.object(model,'OUTPUTS',study.parent),patch.object(model,'run_case',side_effect=solve),patch.object(model,'write_summary',side_effect=summary),patch('catalog.cache_entries',return_value={}),patch('catalog.record',side_effect=record),patch.object(adaptive,'artifacts'),patch.object(adaptive,'export_master'),patch('torque_frontier.generate',side_effect=ValueError('skip')):
                adaptive.worker(model,study)
            self.assertEqual(len(calls),3)
            keys=[tuple(s['chord_m'] for s in x['sections']) for x in calls]
            self.assertEqual(len(set(keys)),3)
            summary=model.read_json(study/'adaptive_summary.json')
            self.assertEqual(summary['new_simulations'],3)
            self.assertIn('budget',summary['stop_reason'])
            self.assertEqual(model.read_json(study/'status.json')['state'],'complete')

if __name__=='__main__':unittest.main()
