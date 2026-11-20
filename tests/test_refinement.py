import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import csv
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from wingstudy import model
from wingstudy import catalog
from wingstudy import refinement
from wingstudy import torque_study
import test_catalog


class RefinementChecks(unittest.TestCase):
    saved=test_catalog.CatalogChecks.saved
    setUp=test_catalog.CatalogChecks.setUp
    tearDown=test_catalog.CatalogChecks.tearDown

    def test_span_search_grid_preserves_chords_and_round_trips(self):
        c=self.configuration(n=7)
        c['span_search']={'enabled':True,'min_m':.4,'max_m':.8,'count':5}
        before=copy.deepcopy(c);result=model.plan(c)
        self.assertEqual(c,before)
        self.assertEqual(result['case_count'],5)
        self.assertEqual(result['cases'],model.plan(result['config'])['cases'])
        original=c['shape_sweep']['baseline']['sections']
        for total,case in zip(np.linspace(.4,.8,5),result['cases']):
            self.assertAlmostEqual(2*case['sections'][-1]['y_m']+c['settings']['gap_m'],total)
            for a,b in zip(original,case['sections']):
                for key in ('chord_m','x_m','pitch_deg','roll_deg'):self.assertEqual(a[key],b[key])
        self.assertEqual(len({catalog.signature(model,x,result['settings']) for x in result['cases']}),5)
        self.assertIsNotNone(model.build_solver(result['cases'][0],result['settings']))

    def test_span_search_bounds_budget_and_equal_endpoint_dedup(self):
        c=self.configuration(n=4)
        for lo,hi,count,message in [(0,.8,5,'Minimum'),(.8,.4,5,'Maximum'),(.4,.8,1,'two'),(.4,.8,1.5,'integer'),(.4,.8,10001,'budget')]:
            c['span_search']={'enabled':True,'min_m':lo,'max_m':hi,'count':count}
            with self.assertRaises(ValueError):model.plan(c)
        c['span_search']={'enabled':True,'min_m':.6,'max_m':.6,'count':5}
        self.assertEqual(model.plan(c)['case_count'],1)

    def test_resize_span_preserves_chords_offsets_and_angles_and_changes_identity(self):
        case=self.spec['cases'][0];settings=self.spec['settings']
        design={'name':'Saved wing','sections':copy.deepcopy(case['sections'])}
        design['sections'][1].update(x_m=.01,pitch_deg=3.,roll_deg=5.)
        original=copy.deepcopy(design);target=2*design['sections'][-1]['y_m']*1.5+settings['gap_m']
        r=refinement.resize_span(model,design,target,settings)
        self.assertEqual(design,original)
        self.assertAlmostEqual(r['span_scale_factor'],1.5)
        for old,new in zip(design['sections'],r['baseline']['sections']):
            self.assertAlmostEqual(new['y_m'],old['y_m']*1.5)
            for key in ('chord_m','x_m','pitch_deg','roll_deg'):self.assertEqual(new[key],old[key])
        old=model.custom_case(design,settings);new=model.custom_case(r['baseline'],settings)
        self.assertNotEqual(catalog.signature(model,old,settings),catalog.signature(model,new,settings))
        self.assertEqual([s['chord_m'] for s in old['sections']],[s['chord_m'] for s in new['sections']])
        self.assertIsNotNone(model.build_solver({**new,'id':'resized'},settings))

    def test_resize_span_uses_active_tip_and_rejects_span_smaller_than_gap(self):
        settings=self.spec['settings'];design={'name':'Shortened','sections':[{'y_m':0,'chord_m':.2},{'y_m':.1,'chord_m':.1},{'y_m':.2,'chord_m':0}]}
        result=refinement.resize_span(model,design,.44,settings)
        self.assertEqual(len(result['baseline']['sections']),2)
        self.assertAlmostEqual(result['single_wing_span_m'],(.44-settings['gap_m'])/2)
        self.assertAlmostEqual(result['baseline']['sections'][-1]['y_m'],result['single_wing_span_m'])
        for value in [0,settings['gap_m'],float('nan')]:
            with self.assertRaises(ValueError):refinement.resize_span(model,design,value,settings)

    def test_linspace_refines_only_selected_chords_and_matches_original_grid(self):
        c=self.configuration(16,41);baseline=c['shape_sweep']['baseline']['sections']
        c['mode']='shape_sweep';c['refinement']['search_method']='linspace'
        c['shape_sweep'].update(decreasing=False,ranges=[{'min_m':s['chord_m'],'max_m':s['chord_m'],'count':1} for s in baseline])
        for i,count in [(7,3),(8,5)]:
            chord=baseline[i]['chord_m'];c['shape_sweep']['ranges'][i]={'min_m':chord*.95,'max_m':chord*1.05,'count':count}
        result=model.plan(c)
        self.assertEqual(result['case_count'],15)
        self.assertEqual(result['shape_grid']['unconstrained_count'],15)
        for case in result['cases']:
            for i,s in enumerate(case['sections']):
                if i not in (7,8):self.assertEqual(s,baseline[i])
        for i,count in [(7,3),(8,5)]:
            actual={case['sections'][i]['chord_m'] for case in result['cases']};bounds=c['shape_sweep']['ranges'][i]
            self.assertEqual(actual,set(np.linspace(bounds['min_m'],bounds['max_m'],count)))
        direct=copy.deepcopy(c);direct.pop('refinement')
        self.assertEqual(result['cases'],model.plan(direct)['cases'])
        self.assertEqual(result['cases'],model.plan(result['config'])['cases'])
        c['settings']['case_budget']=14
        with self.assertRaisesRegex(ValueError,'budget'):model.plan(c)

    def test_new_linspace_nodes_start_fixed_and_bounds_can_exclude_baseline(self):
        c=self.configuration();source=c['refinement']['source']
        nodes=refinement.resample(model,source,32,5,c['settings'],linspace=True)
        self.assertTrue(all(r['count']==1 and r['min_m']==r['max_m']==s['chord_m'] for r,s in zip(nodes['ranges'],nodes['baseline']['sections'])))
        c['refinement']['search_method']='linspace';c['shape_sweep'].update(baseline=nodes['baseline'],ranges=nodes['ranges'],chord_count=32,decreasing=False)
        c['settings']['span_panels']=nodes['required_span_panels']
        self.assertEqual(model.plan(c)['case_count'],1)
        chord=nodes['baseline']['sections'][10]['chord_m']
        c['shape_sweep']['ranges'][10]={'min_m':chord*1.1,'max_m':chord*1.2,'count':4}
        self.assertEqual(model.plan(c)['case_count'],4)

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
