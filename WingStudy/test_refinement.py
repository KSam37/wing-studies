import copy
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import model
import catalog
import refinement
import torque_study
import test_catalog


class RefinementChecks(unittest.TestCase):
    saved=test_catalog.CatalogChecks.saved
    setUp=test_catalog.CatalogChecks.setUp
    tearDown=test_catalog.CatalogChecks.tearDown

    def configuration(self,n=16,count=21):
        c=torque_study.default_config(model);source={'name':'Source','sections':self.spec['cases'][0]['sections']}
        nodes=refinement.resample(model,source,n,5,c['settings'])
        c['settings'].update(span_panels=nodes['required_span_panels'],chord_panels=2)
        c['shape_sweep'].update(baseline=nodes['baseline'],ranges=nodes['ranges'],chord_count=n,decreasing=True)
        c['refinement']={'enabled':True,'candidates':count,'seed':7,'source':source}
        c['mode']='local_refinement'
        return c

    def test_smooth_dense_nodes_bounds_reproducibility_and_native_mesh(self):
        c=self.configuration();before=copy.deepcopy(c)
        a=model.plan(c);b=model.plan(c)
        self.assertEqual(c,before);self.assertEqual(a['cases'],b['cases'])
        self.assertEqual(a['case_count'],21)
        self.assertEqual(len(a['cases'][0]['sections']),16)
        self.assertEqual(a['cases'][0]['sections'],c['shape_sweep']['baseline']['sections'])
        for case in a['cases']:
            values=[s['chord_m'] for s in case['sections']]
            self.assertTrue(all(x>=y-1e-12 for x,y in zip(values,values[1:])))
            for s,r in zip(case['sections'],c['shape_sweep']['ranges']):
                self.assertGreaterEqual(s['chord_m']+1e-12,r['min_m']);self.assertLessEqual(s['chord_m']-1e-12,r['max_m'])
        self.assertEqual(model.plan(a['config'])['cases'],a['cases'])
        self.assertEqual(len({catalog.signature(model,case,a['settings']) for case in a['cases']}),21)
        c['refinement']['seed']=12
        self.assertNotEqual(model.plan(c)['cases'],a['cases'])
        self.assertIsNotNone(model.build_solver(a['cases'][1],a['settings']))

    def test_dense_search_does_not_enumerate_cartesian_grid(self):
        c=self.configuration(40,7);spec=model.plan(c)
        self.assertEqual(spec['case_count'],7)
        self.assertEqual(len(spec['cases'][0]['sections']),40)
        for r in c['shape_sweep']['ranges']:r['min_m']=r['max_m']=(r['min_m']+r['max_m'])/2
        self.assertEqual(model.plan(c)['case_count'],1)
        c['refinement']['candidates']=10001
        with self.assertRaises(ValueError):model.plan(c)

    def test_zero_suffix_does_not_extend_interpolated_wing(self):
        source={'name':'Short','sections':[{'y_m':0,'chord_m':.1},{'y_m':.1,'chord_m':.08},{'y_m':.2,'chord_m':0},{'y_m':.3,'chord_m':0}]}
        result=refinement.resample(model,source,16,5,self.spec['settings'])
        self.assertEqual(result['baseline']['sections'][-1]['y_m'],.1)
        self.assertTrue(all(s['chord_m']>0 for s in result['baseline']['sections']))

    def retention_study(self):
        c=self.configuration(4,3);spec=model.plan(c)
        study=self.out/'local';study.mkdir();(study/'comparisons').mkdir()
        spec.update(created='2026-10-26',ptera_version='5.1.0');catalog.prepare(model,spec,study.name)
        model.write_json(study/'manifest.json',spec)
        model.write_json(study/'status.json',{'state':'complete','total':3,'completed':3})
        rows=[]
        for i,case in enumerate(spec['cases']):
            folder=study/case['id'];folder.mkdir()
            for filename in catalog.CASE_FILES:(folder/filename).write_bytes(b'fixture'*20)
            row={**case,'status':'ok','single_wing_mean_thrust_N':i+1.,'estimated_two_wing_mean_thrust_N':2*(i+1.),
                'single_wing_peak_abs_roll_moment_Nm':.2 if i<2 else 1.,'cycle_repeatable':True}
            catalog.record(model,spec,study.name,row);rows.append(row)
        model.write_summary(study,rows)
        with (study/'comparisons/time_histories.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['case','time_s','force']);writer.writerows([[r['id'],i,1] for r in rows for i in range(3)])
        return study,spec

    def test_keep_only_feasible_best_and_remove_catalog_losers(self):
        self.saved('historic');catalog.start_fresh(model)
        old=self.out.parent/'master_runs_old.sqlite3';old_hash=hashlib.sha256(old.read_bytes()).hexdigest()
        study,spec=self.retention_study();number=spec['cases'][1]['global_case_no']
        trashed=[]
        def fake_recycle(paths,root):
            self.assertTrue(all(p.resolve().is_relative_to(root.resolve()) for p in paths));trashed.extend(paths)
        with patch.object(refinement,'recycle',side_effect=fake_recycle):
            result=refinement.keep_best(model,study,.625,'case_0002')
        self.assertEqual(result['discarded_count'],2)
        self.assertEqual([p.name for p in study.glob('case_*')],['case_0002'])
        self.assertTrue(trashed[0].exists())
        self.assertEqual(len(model.read_json(study/'results.json')),1)
        catalog.sync(model);catalog.sync(model)
        data=catalog.listing(model);self.assertEqual(data['case_count'],1)
        self.assertEqual(data['rows'][0]['global_case_no'],number)
        with (study/'comparisons/time_histories.csv').open() as f:
            self.assertEqual({r['case'] for r in csv.DictReader(f)},{'case_0002'})
        saved=model.read_json(study/'best_wing_settings.json')
        self.assertNotIn('refinement',saved);self.assertEqual(model.plan(saved)['case_count'],1)
        self.assertEqual(hashlib.sha256(old.read_bytes()).hexdigest(),old_hash)

    def test_in_progress_stale_and_no_feasible_cleanup_are_blocked(self):
        study,spec=self.retention_study()
        for limit,expected in [(.1,'case_0002'),(.625,'case_0001')]:
            with self.assertRaises(ValueError):refinement.keep_best(model,study,limit,expected)
        model.write_json(study/'status.json',{'state':'running'})
        with self.assertRaises(ValueError):refinement.keep_best(model,study,.625,'case_0002')
        self.assertEqual(len(list(study.glob('case_*'))),3)

    def test_retention_preserves_a_case_still_used_by_another_study(self):
        study,spec=self.retention_study();other=self.out/'other';other.mkdir();(other/'comparisons').mkdir()
        case=copy.deepcopy(spec['cases'][0]);folder=other/case['id'];folder.mkdir()
        for filename in catalog.CASE_FILES:(folder/filename).write_bytes(b'fixture'*20)
        (other/'comparisons/time_histories.csv').write_text('case,time_s\ncase_0001,0\n')
        manifest={**copy.deepcopy(spec),'cases':[case],'case_count':1};catalog.prepare(model,manifest,'other')
        row=model.read_json(study/'results.json')[0];catalog.record(model,manifest,'other',{**row,'reused_from':{'study':'local'}})
        model.write_json(other/'manifest.json',manifest);model.write_json(other/'results.json',[row])
        with patch.object(refinement,'recycle'):
            refinement.keep_best(model,study,.625,'case_0002')
        data=catalog.listing(model)
        self.assertEqual(data['case_count'],2)
        source=next(r for r in data['rows'] if r['global_case_no']==case['global_case_no'])
        self.assertEqual(source['_study'],'other');self.assertTrue(source['outputs_available'])


if __name__=='__main__':unittest.main()
