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
        c['adaptive_search']={**adaptive.DEFAULT,'enabled':True,'span_min_m':.6,'span_max_m':.6,'span_count':1,'node_count':3,'decreasing':False,'acceptance_rule':'pareto'}
        return c

    def test_requested_defaults_match_ui_and_form_four_unconstrained_searches(self):
        import re
        c=torque_study.default_config(model);c['adaptive_search']={'enabled':True}
        p=adaptive.plan(model,c)
        r=p['adaptive_search']
        self.assertEqual((r['span_min_m'],r['span_max_m'],r['span_count'],r['node_count']),(.4,.8,4,8))
        self.assertEqual((r['initial_step_m'],r['minimum_step_m']),(.04,.01))
        self.assertNotIn('torque_max_nm',r)
        self.assertEqual(p['config']['optimization']['constraint'],'peak_root_torque_le_available_target')
        self.assertNotIn('max_root_moment_nm',p['config']['optimization'])
        self.assertEqual((r['simulation_budget'],r['evaluation_budget']),(500,None))
        self.assertEqual(p['search_job_count'],48)
        html=(model.HERE/'workflow.html').read_text(encoding='utf-8')
        for field,key in {'adaptiveSpanMin':'span_min_m','adaptiveSpanMax':'span_max_m','adaptiveSpanCount':'span_count','adaptiveNodes':'node_count','adaptiveStep':'initial_step_m','adaptiveMinStep':'minimum_step_m','adaptiveBudget':'simulation_budget'}.items():
            value=re.search('id="'+field+'"[^>]*value="([^"]+)"',html)[1]
            self.assertEqual(float(value),r[key])

    def test_endpoints_are_search_coordinates_and_root_max_is_not_a_fixed_width(self):
        c=self.config();c['adaptive_search'].update(root_chord_m=.12,tip_chord_m=.04,maximum_root_chord_m=.2,initial_step_m=.04,minimum_step_m=.01,max_passes=1,paired_moves=False)
        r=adaptive.options(model,c);seen=[]
        def evaluate(chords,meta):
            seen.append(chords[:]);return row(str(len(seen)),1,1)
        adaptive.run_search(r,evaluate)
        seed=adaptive.seed(r)
        self.assertTrue(any(v[0]<seed[0] for v in seen))
        self.assertTrue(any(v[0]>seed[0] for v in seen))
        self.assertTrue(any(v[-1]<seed[-1] for v in seen))
        self.assertTrue(any(v[-1]>seed[-1] for v in seen))
        self.assertTrue(all(.01<=v[0]<=.2 for v in seen))
        c['adaptive_search'].update(root_chord_m=.2,decreasing=True,tip_chord_m=.19)
        r=adaptive.options(model,c);seen.clear();adaptive.run_search(r,evaluate)
        self.assertTrue(any(.19<=v[0]<.2 for v in seen))
        self.assertTrue(any(v[-1]>.19 for v in seen))
        self.assertIsNone(r['maximum_chord_m'])

    def test_plan_roundtrip_fixed_span_chord_floor_and_native_mesh(self):
        c=self.config();before=copy.deepcopy(c);p=adaptive.plan(model,c)
        self.assertEqual(c,before)
        self.assertEqual(p['cases'],adaptive.plan(model,p['config'])['cases'])
        self.assertEqual(p['simulation_budget'],500)
        case=p['cases'][0]
        self.assertAlmostEqual(case['span_m'],.6)
        self.assertTrue(all(s['chord_m']>=.01 for s in case['sections']))
        self.assertIsNotNone(model.build_solver(case,p['settings']))
        for key,value in [('minimum_chord_m',.001),('tip_chord_m',-1),('minimum_step_m',.1),('span_max_m',.4),('shrink_factor',1)]:
            invalid=copy.deepcopy(c);invalid['adaptive_search'][key]=value
            with self.assertRaises(ValueError):adaptive.plan(model,invalid)

    def test_minimum_tip_rounding_does_not_remove_a_valid_seed_tip(self):
        for count in (3,4,5,8,16):
            c=self.config();c['adaptive_search']['node_count']=count
            r=adaptive.options(model,c)
            self.assertEqual(adaptive.seed(r)[-1],.01)
            p=adaptive.plan(model,c)
            self.assertEqual(p['cases'][0]['omitted_zero_chord_count'],0)
            self.assertAlmostEqual(p['cases'][0]['span_m'],.6)

    def test_zero_suffix_can_shorten_any_outboard_node_without_disconnection(self):
        c=self.config();c['adaptive_search'].update(node_count=5,tip_chord_m=0,
            bounds=[{'min_m':.01 if i<2 else 0} for i in range(5)])
        r=adaptive.options(model,c)
        self.assertTrue(adaptive.valid([.2,.1,.03,0,0],r))
        self.assertFalse(adaptive.valid([.2,.1,0,.02,0],r))
        self.assertFalse(adaptive.valid([.2,0,0,0,0],r))
        self.assertFalse(adaptive.valid([.2,.1,.005,0,0],r))
        for decreasing in (False,True):
            r['decreasing']=decreasing
            proposal=adaptive.neighbor([.2,.1,.03,.02,.01],(2,),-1,[.04]*5,r)
            self.assertEqual(proposal,[.2,.1,0.,0.,0.])
        case=model.custom_case(adaptive.design(r,.6,.04,proposal),adaptive.plan(model,c)['settings'])
        self.assertEqual(case['active_chord_count'],2)
        self.assertEqual(case['omitted_zero_chord_count'],3)
        self.assertLess(case['span_m'],.6)
        self.assertIsNotNone(model.build_solver(case,adaptive.plan(model,c)['settings']))

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

    def test_pareto_archive_preserves_tradeoffs_instead_of_maximizing_ratio(self):
        archive=[]
        def add(name,t,m):return adaptive.offer(archive,{'case':row(name,t,m),'chords':[t]})
        self.assertTrue(add('seed',2,1))
        self.assertTrue(add('higher_thrust_lower_ratio',10,10))
        self.assertTrue(add('lower_torque',1,.2))
        self.assertFalse(add('dominated',1,2))
        self.assertFalse(add('duplicate_metrics',2,1))
        self.assertEqual(len(archive),3)
        self.assertTrue(add('improved_seed',3,1))
        self.assertEqual({e['case']['id'] for e in archive},{'higher_thrust_lower_ratio','lower_torque','improved_seed'})
        bad=row('unsettled',100,.1);bad['cycle_repeatable']=False
        self.assertFalse(adaptive.offer(archive,{'case':bad}))
        c=self.config();c['adaptive_search'].update(torque_min_nm=-100,torque_max_nm=-1,torque_count=0)
        p=adaptive.plan(model,c)
        self.assertNotIn('torque_max_nm',p['adaptive_search'])
        self.assertNotIn('max_root_moment_nm',p['config']['optimization'])
        self.assertEqual(p['config']['optimization']['objective'],'pareto_mean_thrust_peak_root_torque_v1')

    def test_branch_search_retains_high_thrust_and_low_torque_with_true_parentage(self):
        c=self.config();c['adaptive_search'].update(root_chord_m=.12,tip_chord_m=.04,max_passes=3,paired_moves=False)
        r=adaptive.options(model,c);events=[];seen={};seed=adaptive.seed(r)
        def evaluate(chords,meta):
            key=tuple(chords)
            self.assertNotIn(key,seen)
            t=sum(chords);m=t*t
            result=row(str(len(seen)),t,m);result['adaptive_trial']=meta
            seen[key]=result
            return result
        adaptive.run_search(r,evaluate,events.append)
        self.assertEqual(events[0]['chords'],seed)
        self.assertTrue(any(e['case']['single_wing_mean_thrust_N']>sum(seed) for e in events))
        self.assertTrue(any(e['case']['single_wing_mean_thrust_N']<sum(seed) for e in events))
        self.assertGreater(events[-1]['frontier_size'],2)
        for event in events[1:]:self.assertIn(event['parent_case'],[v['id'] for v in seen.values()])
        parents=adaptive.frontier_parents([{'case':row(str(i),i+1,i+1),'chords':[i]} for i in range(10)],{},2,0)
        self.assertEqual({p['case']['id'] for p in parents},{'0','9'})

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
