import copy
import csv
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
import model
import adaptive
import parallel_cases
import test_adaptive
from test_torque_study import row


class ParallelChecks(unittest.TestCase):
    def test_native_outputs_stage_outside_long_study_paths_and_are_cleaned(self):
        import catalog
        locations=[]
        def fake(case,settings,directory):
            locations.append(directory)
            self.assertLess(len(str(directory/'water_wing_force_coefficients.png')),260)
            for name in catalog.CASE_FILES:(directory/name).write_bytes(b'verified output'*8)
            history=directory.parent/'comparisons';history.mkdir()
            (history/'time_histories.csv').write_text('case,time_s\ncase_0001,0\n')
            return {'single_wing_mean_thrust_N':1.}
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp,patch.object(model,'run_case',side_effect=fake):
            study=Path(temp)/'study-with-a-long-descriptive-name';study.mkdir()
            result=parallel_cases.run_isolated({'id':'case_0001'},{},study)
            self.assertNotIn('error',result)
            self.assertFalse(locations[0].is_relative_to(study))
            self.assertFalse(locations[0].parent.exists())
            self.assertTrue(all((study/'case_0001'/name).exists() for name in catalog.CASE_FILES))

    def test_parallel_dedup_budget_single_writer_and_partial_poll_history(self):
        c=test_adaptive.AdaptiveChecks().config();c['adaptive_search'].update(parallel_workers=2,simulation_budget=3,budget_only=True,evaluation_budget=1,max_passes=1)
        spec=adaptive.plan(model,c);calls=[];active=0;peak=0;lock=threading.Lock();coordinator=threading.get_ident();both_ready=threading.Event()
        def fake(case,settings,study):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active);calls.append(case['id'])
                if active>=2:both_ready.set()
            if not both_ready.wait(10):raise AssertionError('Two cases never overlapped')
            time.sleep(.02)
            with lock:active-=1
            return {'metrics':{k:v for k,v in row(case['id'],1,.5).items() if k!='id'},
                'history_header':['case','time_s'],'history':[[case['id'],0],[case['id'],1]]}
        def record(m,manifest,name,result):
            self.assertEqual(threading.get_ident(),coordinator);result['global_case_no']=int(result['id'].split('_')[1])
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            study=Path(temp);spec['cases']=[];model.write_json(study/'manifest.json',spec)
            with patch.object(parallel_cases,'ProcessPoolExecutor',lambda **kw:ThreadPoolExecutor(max_workers=kw['max_workers'])),patch.object(parallel_cases,'run_isolated',side_effect=fake),patch('catalog.cache_entries',return_value={}),patch('catalog.record',side_effect=record):
                with parallel_cases.CasePipeline(model,study,spec) as pipeline:
                    r=spec['adaptive_search'];seed=adaptive.seed(r)
                    meta={'job':1,'span_m':.6,'pass':0,'node':None,'step_m':0,'parent_case':None}
                    inputs=[(seed,meta),(seed,meta),([.19,.1,.02],meta),([.18,.1,.03],meta),([.17,.1,.04],meta)]
                    responses=pipeline.evaluate_many(inputs)
                    self.assertEqual(pipeline.simulations,3)
                    self.assertEqual(pipeline.finished,3)
                    self.assertEqual(len(responses),4)
                    self.assertEqual(responses[0]['id'],responses[1]['id'])
                    self.assertEqual(len(pipeline.rows),3)
                    self.assertIn('budget',pipeline.stop_reason)
                    self.assertEqual(peak,2)
                    self.assertEqual(len(set(calls)),3)
            with (study/'comparisons/time_histories.csv').open() as f:
                histories=list(csv.DictReader(f));self.assertEqual(len(histories),6)
                self.assertEqual({r['case'] for r in histories},set(calls))

    def test_single_span_parallel_poll_keeps_partial_budget_results_in_archive(self):
        c=test_adaptive.AdaptiveChecks().config();c['adaptive_search'].update(parallel_workers=2,simulation_budget=4,evaluation_budget=40)
        spec=adaptive.plan(model,c);events=[]
        class Pipeline:
            stop_reason=None
            count=0
            def accept(self,event):events.append(event)
            def evaluate_many(self,inputs):
                available=4-self.count;chosen=inputs[:available]
                if len(inputs)>available:self.stop_reason='budget'
                out=[]
                for chords,meta in chosen:
                    self.count+=1;out.append(row(str(self.count),sum(chords),sum(chords)**2))
                return out
        pipeline=Pipeline()
        with self.assertRaises(adaptive.BudgetReached):parallel_cases.parallel_search(spec['adaptive_search'],pipeline)
        self.assertEqual(pipeline.count,4)
        self.assertGreater(len(events),1)
        self.assertTrue(all(e['case']['id'] in ('1','2','3','4') for e in events))

    def test_parallel_worker_count_is_validated_and_not_a_physics_setting(self):
        c=test_adaptive.AdaptiveChecks().config();serial=adaptive.plan(model,c)
        c['adaptive_search']['parallel_workers']=4;parallel=adaptive.plan(model,c)
        import catalog
        self.assertEqual(catalog.signature(model,serial['cases'][0],serial['settings']),catalog.signature(model,parallel['cases'][0],parallel['settings']))
        for workers in (0,1.5,65):
            c['adaptive_search']['parallel_workers']=workers
            with self.assertRaises(ValueError):adaptive.plan(model,c)


if __name__=='__main__':unittest.main()
