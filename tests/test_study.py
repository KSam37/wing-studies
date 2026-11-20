"""Engineering checks: input constraints, geometry, motion, and summary arithmetic."""
import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import math
import csv
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from unittest.mock import patch
import unittest
import numpy as np
from wingstudy import model


class StudyChecks(unittest.TestCase):
    def landscape_rows(self,span=.6):
        c=copy.deepcopy(model.DEFAULT);c['shape_sweep']['span_m']=span
        p=model.plan(c)
        return [{**r,**r['geometry'],'area_m2':r['geometry']['area_m2']/2,'aspect_ratio':((span-p['settings']['gap_m'])/2)**2/(r['geometry']['area_m2']/2),'status':'ok','cycle_repeatable':True,'shape_ratio_valid':True,
                 model.OBJECTIVE:1+i*.1,'single_wing_mean_thrust_N':.5,'single_wing_peak_abs_roll_moment_Nm':.5/(1+i*.1)} for i,r in enumerate(p['cases'])]

    def test_landscape_collinear_thrust_curve_duplicates_and_thumbnails(self):
        rows=self.landscape_rows()
        rows.append({**copy.deepcopy(rows[0]),'id':'case_duplicate',model.OBJECTIVE:10.})
        d=model.shape_landscape_data(rows,model.DEFAULT['settings'])
        self.assertEqual(len(d['points']),len(rows));self.assertTrue(d['duplicate_locations']>0)
        self.assertEqual(d['interpolation_kind'],'smooth_sampled_curve');self.assertFalse(d['triangles'])
        curve=np.array(d['curve']);np.testing.assert_allclose(curve[:,1],.5)
        self.assertEqual(d['axes'][1],'single_wing_mean_thrust_N')
        self.assertIn('case_duplicate',d['vertex_case_ids'])
        self.assertTrue(all(len(p['thumbnail'])==1 for p in d['points']))
        for p in d['points']:
            v=np.concatenate(p['thumbnail']);self.assertLessEqual(abs(v).max(),.50000001)
        one=model.shape_landscape_data(rows[:1],model.DEFAULT['settings'])
        self.assertEqual(one['interpolation_kind'],'points');self.assertFalse(one['curve'])
        with self.assertRaises(ValueError):model.shape_landscape_data([],model.DEFAULT['settings'])

    def test_landscape_varying_span_mesh_and_measured_only_export(self):
        rows=self.landscape_rows(.45)+self.landscape_rows(.6)
        for i,r in enumerate(rows):r['id']=f'case_{i:04d}';r['single_wing_mean_thrust_N']=.1+i*.01;r[model.OBJECTIVE]=2+3*r['area_m2']+.2*r['single_wing_mean_thrust_N']
        d=model.shape_landscape_data(rows,model.DEFAULT['settings'])
        self.assertEqual(d['interpolation_kind'],'bounded_cubic_surface');self.assertTrue(d['triangles']);self.assertFalse(d['curve'])
        vertices=np.array(d['vertices'])
        for triangle in d['triangles']:
            p=vertices[triangle].mean(axis=0)
            self.assertAlmostEqual(p[2],2+3*p[0]+.2*p[1])
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);model.write_json(path/'manifest.json',{'settings':model.DEFAULT['settings']});model.write_json(path/'results.json',rows)
            exported=model.shape_landscape(path)
            self.assertTrue((path/'comparisons/wing_shape_landscape_repeatable.png').is_file())
            with (path/'comparisons/wing_shape_landscape_repeatable.csv').open(newline='') as f:records=list(csv.DictReader(f))
            self.assertEqual(len(records),len(rows));self.assertIn('used_for_interpolation',records[0]);self.assertIn('sections',records[0])
            for record,row in zip(records,rows):
                self.assertAlmostEqual(float(record['aspect_ratio']),row['aspect_ratio'])
                self.assertAlmostEqual(float(record['single_wing_mean_thrust_N']),row['single_wing_mean_thrust_N'])
        bad=[{**r,'cycle_repeatable':False} for r in rows]
        with self.assertRaises(ValueError):model.shape_landscape_data(bad,model.DEFAULT['settings'])
        self.assertEqual(len(model.shape_landscape_data(bad,model.DEFAULT['settings'],False)['points']),len(rows))

    def test_landscape_cubic_curvature_and_hull(self):
        from scipy.spatial import Delaunay
        rows=self.landscape_rows()
        for r in rows:r[model.OBJECTIVE]=1+1000*r['area_m2']**2
        d=model.shape_landscape_data(rows,model.DEFAULT['settings']);curve=np.array(d['curve'])
        original=np.array([p['coords'] for p in d['points']]);order=np.argsort(original[:,0]);original=original[order]
        linear=np.interp(curve[:,0],original[:,0],original[:,2])
        self.assertGreater(np.max(np.abs(curve[:,2]-linear)),1e-5)
        self.assertGreaterEqual(curve[:,2].min(),original[:,2].min());self.assertLessEqual(curve[:,2].max(),original[:,2].max()+1e-10)
        for v in original:self.assertLess(np.linalg.norm(curve-v,axis=1).min(),1e-9)
        rows+=self.landscape_rows(.45)
        for i,r in enumerate(rows):r['id']=f'nonlinear_{i}';r['single_wing_mean_thrust_N']=.1+i*.01;r[model.OBJECTIVE]=1+500*r['area_m2']**2+.4*r['single_wing_mean_thrust_N']**2
        d=model.shape_landscape_data(rows,model.DEFAULT['settings']);vertices=np.array(d['vertices']);original=np.array([p['coords'] for p in d['points']])
        self.assertEqual(d['interpolation_kind'],'bounded_cubic_surface');self.assertGreater(len(vertices),len(original))
        self.assertTrue(np.isfinite(vertices).all())
        origin=original[:,:2].min(axis=0);extent=np.ptp(original[:,:2],axis=0)
        base=Delaunay((original[:,:2]-origin)/extent);simplices=base.find_simplex((vertices[:,:2]-origin)/extent,tol=1e-9)
        self.assertTrue((simplices>=0).all())
        for value,simplex in zip(vertices[:,2],simplices):
            limits=original[base.simplices[simplex],2]
            self.assertGreaterEqual(value,limits.min()-1e-9);self.assertLessEqual(value,limits.max()+1e-9)
        for v in original:self.assertLess(np.linalg.norm(vertices-v,axis=1).min(),1e-8)

    def test_json_write_retries_transient_windows_lock(self):
        original=model.os.replace;attempts=[]
        def briefly_locked(src,dst):
            attempts.append(1)
            if len(attempts)==1:raise PermissionError('Transient Windows sharing lock')
            return original(src,dst)
        with tempfile.TemporaryDirectory(dir=model.HERE) as td,patch.object(model.os,'replace',side_effect=briefly_locked),patch.object(model.time,'sleep'):
            path=Path(td)/'status.json';model.write_json(path,{'complete':True})
            self.assertEqual(model.read_json(path),{'complete':True});self.assertEqual(len(attempts),2)

    def test_eta_excludes_suspended_validation_and_reused_outputs(self):
        settings=model.plan(copy.deepcopy(model.DEFAULT))['settings'];settings['aeroelastic_enabled']=True
        with tempfile.TemporaryDirectory(dir=model.HERE) as td,patch.object(model,'OUTPUTS',Path(td)),patch.dict(model._TIMING_CACHE,{'at':0.,'samples':[]},clear=True):
            for name,elapsed,extra,row_extra in [('actual',200.,{},{}),('suspended',30000.,{'exclude_timing_from_eta':True},{}),('cache',1.,{},{'reused_from':{'case':'cached'}})]:
                folder=Path(td)/name;folder.mkdir()
                model.write_json(folder/'manifest.json',{'settings':settings,'panels_per_case':32,**extra})
                model.write_json(folder/'results.json',[{'status':'ok','steps':200,'elapsed_s':elapsed,**row_extra}])
            estimate=model.estimated_case_seconds(settings,32,200)
            self.assertEqual(estimate['timing_samples'],1);self.assertEqual(estimate['case_seconds'],200.)
            changed={**settings,'damping_constant_rad':999.}
            self.assertEqual(model.estimated_case_seconds(changed,32,200)['timing_samples'],0)
        self.assertIsNone(model.runtime_status({'exclude_timing_from_eta':True},{'state':'running'},[])['eta_remaining_s'])

    def test_native_aeroelastic_settings_and_shared_spring(self):
        import pterasoftware as ps
        c=copy.deepcopy(model.DEFAULT);self.assertFalse(model.plan(c)['settings']['aeroelastic_enabled'])
        c['settings'].update(aeroelastic_enabled=True,span_panels=4,chord_panels=2,dt_s=.025,cycles=3,wake_cycles=2)
        p=model.plan(c);solver=model.build_solver(p['cases'][0],p['settings']);problem=solver.unsteady_problem
        self.assertIsInstance(problem,ps.AeroelasticUnsteadyProblem)
        self.assertAlmostEqual(problem.spring_constant_rad,34e9*math.pi*.004**4/64/.1)
        self.assertAlmostEqual(problem.wing_density,.5);self.assertAlmostEqual(problem.damping_constant_rad,2.0);self.assertEqual(problem.step_discards,5)
        self.assertEqual(solver.num_steps,120);self.assertEqual(problem.max_wake_rows,80)
        wing=problem.movement.airplane_movements[0].base_airplane.wings[0]
        self.assertEqual(len(wing.wing_cross_sections),5);self.assertFalse(wing.symmetric)
        c['settings']['aeroelastic_enabled']='false'
        with self.assertRaises(ValueError):model.plan(c)
        c['settings']['aeroelastic_enabled']=True
        for key,bad in [('spring_constant_rad',0),('wing_density',0),('damping_constant_rad',-1),('step_discards',120)]:
            invalid=copy.deepcopy(c);invalid['settings'][key]=bad
            with self.assertRaises(ValueError):model.plan(invalid)

    def test_native_aeroelastic_custom_wave_acceleration(self):
        c=copy.deepcopy(model.DEFAULT);c['settings']['aeroelastic_enabled']=True
        c['waveform']={'mode':'custom','points':model.DEFAULT['waveform']['points']}
        p=model.plan(c);wave=model.FlapWave(p['settings']['waveform']);acc=model.FlapAcceleration(p['settings']['waveform'])
        h=1e-4
        for phase in (.3,1.1,2.2,4.4):self.assertAlmostEqual(acc(phase),(wave(phase+h)-2*wave(phase)+wave(phase-h))/h**2,places=6)
        solver=model.build_solver(p['cases'][0],p['settings'])
        movement=solver.unsteady_problem.movement.airplane_movements[0].wing_movements[0]
        self.assertTrue(callable(movement.spacingAnglesSecondDerivative_Gs_to_Wn_ixyz[0]))

    def test_custom_wing_sweep_preserves_geometry_and_cache_identity(self):
        from wingstudy import catalog
        wing={'name':'Uneven gull','sections':[
            {'y_m':0.,'x_m':0.,'chord_m':.16,'pitch_deg':4.,'roll_deg':12.},
            {'y_m':.08,'x_m':.015,'chord_m':.12,'pitch_deg':2.,'roll_deg':-8.},
            {'y_m':.3,'x_m':.07,'chord_m':.07,'pitch_deg':-1.,'roll_deg':0.}]}
        c=copy.deepcopy(model.DEFAULT);c.update(mode='custom',designs=[wing])
        original=model.plan(c);original_wing=copy.deepcopy(wing)
        c['mode']='shape_sweep'
        c['shape_sweep'].update(chord_count=3,baseline=wing,span_m=.64,
            ranges=[{'min_m':s['chord_m'],'max_m':s['chord_m'],'count':1} for s in wing['sections']])
        baseline=model.plan(c)
        self.assertEqual(baseline['case_count'],1)
        self.assertEqual(baseline['cases'][0]['sections'],original['cases'][0]['sections'])
        self.assertEqual(catalog.signature(model,baseline['cases'][0],baseline['settings']),
                         catalog.signature(model,original['cases'][0],original['settings']))
        c['shape_sweep']['ranges'][1]={'min_m':.10,'max_m':.14,'count':3}
        swept=model.plan(c);self.assertEqual(swept['case_count'],3)
        for case in swept['cases']:
            for i,section in enumerate(case['sections']):
                for key in ('y_m','x_m','pitch_deg','roll_deg'):
                    self.assertEqual(section[key],wing['sections'][i][key])
        self.assertEqual(wing,original_wing)
        c['shape_sweep']['baseline']['sections']=wing['sections'][:-1]
        with self.assertRaisesRegex(ValueError,'one section'):
            model.plan(c)

    def test_custom_sweep_zero_suffix_keeps_original_station_positions(self):
        c=copy.deepcopy(model.DEFAULT)
        c['shape_sweep'].update(chord_count=3,decreasing=True,baseline={'name':'Shortenable','sections':[
            {'y_m':0,'chord_m':.2},{'y_m':.1,'chord_m':.1},{'y_m':.4,'chord_m':.05}]},
            ranges=[{'min_m':.2,'max_m':.2,'count':1},{'min_m':.1,'max_m':.1,'count':1},
                    {'min_m':0,'max_m':.05,'count':2}])
        p=model.plan(c);self.assertEqual(p['case_count'],2)
        short=next(r for r in p['cases'] if r['chord_3_m']==0)
        self.assertEqual([s['y_m'] for s in short['sections']],[0.,.1])
        self.assertAlmostEqual(short['single_wing_span_m'],.1)

    def test_chord_node_cartesian_grid_and_pruned_taper(self):
        c=copy.deepcopy(model.DEFAULT);c['shape_sweep']['decreasing']=False
        p=model.plan(c);self.assertEqual(p['case_count'],81)
        self.assertTrue(all(len(r['sections'])==4 for r in p['cases']))
        self.assertEqual({r['span_m'] for r in p['cases']},{.6})
        self.assertEqual({r['incidence_deg'] for r in p['cases']},{0})
        self.assertFalse(p['settings']['tail']['enabled'])
        for i in range(1,5):np.testing.assert_allclose(sorted({r[f'chord_{i}_m'] for r in p['cases']}),[.06,.1,.14])
        c['shape_sweep']['decreasing']=True;p=model.plan(c)
        self.assertEqual(p['case_count'],15);self.assertEqual(p['shape_grid']['pruned_count'],66)
        for r in p['cases']:
            chords=[s['chord_m'] for s in r['sections']]
            self.assertTrue(all(b<=a+1e-12 for a,b in zip(chords,chords[1:])))
        c['shape_sweep'].update(chord_count=12,ranges=[{'min_m':.06,'max_m':.14,'count':3} for _ in range(12)])
        c['settings']['span_panels']=12
        with patch.object(model.itertools,'product',side_effect=AssertionError('Cartesian materialization forbidden')):
            p=model.plan(c)
        self.assertEqual(p['case_count'],91)
        self.assertEqual(p['shape_grid']['unconstrained_count'],3**12)

    def test_zero_suffix_grid_count_and_shortened_geometry(self):
        import itertools
        c=copy.deepcopy(model.DEFAULT)
        c['shape_sweep'].update(chord_count=4,ranges=[{'min_m':0,'max_m':.2,'count':3} for _ in range(4)])
        for decreasing in (False,True):
            c['shape_sweep']['decreasing']=decreasing
            expected=[v for v in itertools.product([0,.1,.2],repeat=4)
                      if v[0]>0 and v[1]>0 and all(not (v[i]==0 and any(x>0 for x in v[i+1:])) for i in range(4))
                      and (not decreasing or all(b<=a for a,b in zip(v,v[1:])))]
            p=model.plan(c)
            self.assertEqual(p['shape_grid']['count'],len(expected))
            self.assertEqual(p['case_count'],len(expected))
            self.assertEqual(set(model.shape_combinations(model.shape_grid(c['shape_sweep'],p['settings'],10000))),set(expected))
            keys=[]
            for case in p['cases']:
                active=case['sections'];self.assertTrue(all(s['chord_m']>0 for s in active))
                self.assertEqual(len(active)+case['omitted_zero_chord_count'],4)
                self.assertAlmostEqual(case['single_wing_span_m'],(.6-p['settings']['gap_m'])/2*(len(active)-1)/3)
                keys.append(tuple(s['chord_m'] for s in active))
            self.assertEqual(len(keys),len(set(keys)))
        c['shape_sweep']['ranges']=[{'min_m':v,'max_m':v,'count':1} for v in (.1,.1,0,0)]
        p=model.plan(c);case=p['cases'][0];solver=model.build_solver(case,p['settings'])
        self.assertEqual(len(solver.steady_problems[0].airplanes[0].wings),1)
        self.assertEqual(solver.num_panels,p['panels_per_case'])
        panels=solver.steady_problems[0].airplanes[0].wings[0].panels.flat
        self.assertTrue(all(panel.area>0 for panel in panels))
        with tempfile.TemporaryDirectory(dir=model.HERE) as td:
            model.save_wing_profiles(case,p['settings'],td)
            self.assertTrue((Path(td)/'wing_right.svg').is_file())

    def test_zero_custom_validation_and_deduplication(self):
        c=self.custom_config();d=c['designs'][0]
        d['sections'][-1]['chord_m']=0
        d['sections'].append({**d['sections'][-1],'y_m':.5,'x_m':.1})
        c['designs'].append(copy.deepcopy(d));c['designs'][1]['name']='Same active wing'
        c['designs'][1]['sections'][-1]['x_m']=.2
        p=model.plan(c)
        self.assertEqual(p['case_count'],1);self.assertEqual(p['duplicate_geometry_count'],1)
        self.assertEqual(len(p['cases'][0]['input_aliases']),2)
        self.assertEqual(len(p['cases'][0]['sections']),2)
        for widths in ((0,0,0,0),(.1,0,0,0),(.1,0,.1,0),(.1,.1,0,.1),(.1,.1,-.1,0)):
            bad=copy.deepcopy(c)
            for section,width in zip(bad['designs'][0]['sections'],widths):section['chord_m']=width
            with self.assertRaises(ValueError):model.plan(bad)

    def test_chord_grid_validation(self):
        c=copy.deepcopy(model.DEFAULT)
        for edit in ({'count':0},{'min_m':-.01},{'max_m':.01},{'count':1}):
            bad=copy.deepcopy(c);bad['shape_sweep']['ranges'][0].update(edit)
            with self.assertRaises(ValueError):model.plan(bad)
        c['settings']['case_budget']=14
        with self.assertRaisesRegex(ValueError,'15 admissible'):model.plan(c)
        c['settings']['case_budget']=100;c['shape_sweep']['ranges'][0]={'min_m':.03,'max_m':.03,'count':1}
        with self.assertRaisesRegex(ValueError,'No shapes'):model.plan(c)

    def test_single_wing_ratio_peak_denominator_and_scaling(self):
        t=np.linspace(0,3,301);forces=np.tile([2.,0.,2.,0.],(len(t),1));moment=3*np.cos(2*np.pi*t)
        m=model.shape_metrics(t,forces,moment,1,5,.3)
        self.assertAlmostEqual(m[model.OBJECTIVE],2/3)
        self.assertEqual(m["estimated_two_wing_mean_thrust_N"],4.)
        self.assertAlmostEqual(m['dimensionless_thrust_roll_score'],.2)
        self.assertAlmostEqual(m['single_wing_rms_roll_moment_Nm'],3/math.sqrt(2),places=5)
        big=model.shape_metrics(t,forces*4,moment*8,1,5,.6)
        self.assertAlmostEqual(big[model.OBJECTIVE],m[model.OBJECTIVE]/2)
        self.assertAlmostEqual(big['dimensionless_thrust_roll_score'],m['dimensionless_thrust_roll_score'])
        self.assertIsNone(model.shape_metrics(t,forces,np.zeros(len(t)),1,5,.3)[model.OBJECTIVE])
        self.assertIsNone(model.shape_metrics(t,-forces,moment,1,5,.3)[model.OBJECTIVE])

    def test_ratio_ranking_export_chord_heatmap_and_runtime_eta(self):
        c=copy.deepcopy(model.DEFAULT);p=model.plan(c);rows=[]
        for case,thrust,roll in zip(p['cases'][:2],[10.,5.],[10.,1.]):
            rows.append({**case,'status':'ok','cycle_repeatable':True,'shape_ratio_valid':True,model.OBJECTIVE:thrust/roll,
                'dimensionless_thrust_roll_score':.28*thrust/roll,'reference_half_span_m':.28,
                'single_wing_mean_thrust_N':thrust,'single_wing_peak_abs_roll_moment_Nm':roll})
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);model.write_json(path/'results.json',rows);model.write_summary(path,rows)
            result=model.shape_comparison(path,export=True)
            self.assertEqual(result['winner']['id'],rows[1]['id'])
            self.assertTrue((path/'comparisons/shape_comparison.png').is_file())
            with (path/'comparisons/top_performers.csv').open(newline='') as f:ranked=list(csv.DictReader(f))
            self.assertEqual(ranked[0]['id'],rows[1]['id'])
            with patch.object(model,'OUTPUTS',path):spec=model.design_plot(path,['chord_1_m','chord_4_m'],model.OBJECTIVE,{})
            self.assertEqual(max(x['value'] for x in spec['points']),5)
            with (path/Path(spec['file']).with_suffix('.csv')).open(newline='') as f:exported=list(csv.DictReader(f))
            self.assertIn('winner_chord_4_m',exported[0])
        import time
        status={'state':'running','total':5,'current_case_started':time.time()-10}
        eta=model.runtime_status({},status,[{'elapsed_s':20}])
        self.assertAlmostEqual(eta['eta_remaining_s'],70,delta=.1)
        self.assertEqual(model.runtime_status({},dict(status,state='complete'),[])['eta_remaining_s'],0)

    def test_custom_waveform_periodicity_and_extrema(self):
        spec=model.validate_waveform({'mode':'custom','points':'0,0\n.15,1\n.35,0\n.65,-1\n1,0'})
        wave=model.FlapWave(spec)
        phase=np.linspace(0,2*np.pi,1001)
        np.testing.assert_allclose([wave(p) for p in phase],[wave(p+2*np.pi) for p in phase],atol=1e-12)
        self.assertAlmostEqual((wave.maximum-wave.minimum)/2,1)
        self.assertAlmostEqual(wave(0),0)
        self.assertAlmostEqual(float(wave.derivative(0)),float(wave.derivative(2*np.pi)))

    def test_waveform_validation_and_comparison_isolation(self):
        for points in ('0,0\n.5,0\n1,0','0,0\n.3,0\n.6,0\n1,0',
                       '0,1\n.3,1\n.6,-1\n1,0','0,0\n.6,1\n.3,-1\n1,0',
                       '0,0\n.3,nan\n.6,-1\n1,0'):
            with self.assertRaises(ValueError):model.validate_waveform({'mode':'custom','points':points})
        c=self.config();p=model.plan(c)
        self.assertEqual(p['cases'][0]['waveform_signature'],'sine')
        self.assertAlmostEqual(p['motion_preview']['maximum_deg'],c['settings']['amplitude_deg'])
        c['waveform']={'mode':'custom','points':'0,0\n.15,1\n.35,0\n.65,-1\n1,0'}
        other=model.plan(c)
        self.assertNotEqual(other['cases'][0]['waveform_signature'],'sine')
        rows=self.rows()
        rows[0].update(waveform_signature=other['cases'][0]['waveform_signature'])
        with self.assertRaisesRegex(ValueError,'Flapping waveform'):
            model.comparison_data(rows,['span_m','incidence_deg'],'mean_thrust_N',{},'max')
        filtered=model.comparison_data(rows,['span_m','incidence_deg'],'mean_thrust_N',{'waveform_signature':'sine'},'max')
        self.assertEqual(filtered['source_case_count'],len(rows)-1)

    def test_native_custom_motion_mirrors_wings_and_keeps_tail_static(self):
        c=self.tail_config()
        c['waveform']={'mode':'custom','points':'0,0\n.15,1\n.35,0\n.65,-1\n1,0'}
        p=model.plan(c);solver=model.build_solver(p['cases'][0],p['settings'])
        wave=model.FlapWave(p['settings']['waveform'])
        # Check actual native generated geometry, not just the stored motion inputs.
        for step in (0,7,13,27):
            a=solver.steady_problems[step].airplanes[0]
            for w in a.wings:
                roll=float(w.angles_Gs_to_Wn_ixyz[0])
                if 'Static Tail' in w.name:self.assertAlmostEqual(roll,0,places=8)
                else:
                    expected=c['settings']['amplitude_deg']*wave(2*math.pi*c['settings']['frequency_hz']*step*c['settings']['dt_s'])
                    self.assertAlmostEqual(roll,expected,places=8)
                    root=w.children_T_pas_Wcs_Lp_to_G_Cg[0][:3,3]
                    tip=w.children_T_pas_Wcs_Lp_to_G_Cg[-1][:3,3]
                    # Reflected Wing keeps the source movement coordinates. Use
                    # the transformed physical hinge to identify left/right.
                    sign=1
                    actual=math.degrees(math.atan2(sign*(tip-root)[2],sign*(tip-root)[1]))
                    self.assertAlmostEqual(actual,sign*expected,places=8)

    def test_root_torque_reference_translation(self):
        from types import SimpleNamespace as Obj
        wings=[]
        for sign in (1,-1):
            root=np.array([0.,sign*.2,0.]);point=np.array([.1,sign*.7,.3]);force=np.array([0.,0.,-4.])
            transform=np.eye(4);transform[:3,3]=root
            panel=Obj(forces_GP1=force,moments_GP1_CgP1=np.cross(point,force))
            wings.append(Obj(name='Study Wing',children_T_pas_Wcs_Lp_to_G_Cg=[transform],panels=np.array([[panel]],dtype=object)))
        wings.append(Obj(name='Static Tail',panels=None))
        airplane=Obj(T_pas_G_Cg_to_GP1_CgP1=np.eye(4),wings=wings)
        airplane.wings=wings[:1]
        self.assertAlmostEqual(model.wing_root_roll_moment(airplane),-2.)
        t=np.linspace(0,.5,101);freq=2.;amp=20.;ratio=5.

    def tail_config(self):
        c=self.config();c["tail"]["enabled"]=False;c["tail"]["pitch_deg"]=8
        c["tail"].update(span_panels=2,chord_panels=2)
        c["settings"].update(span_panels=4,chord_panels=2,cycles=3,wake_model="prescribed",wake_cycles=1)
        c["sweep"]={k:str(v) for k,v in dict(span_m=.6,root_chord_m=.14,tip_ratio=.5,mid_ratio=.85,sweep_deg=0,incidence_deg=0).items()}
        return c

    def test_isolated_native_geometry_and_loads(self):
        p=model.plan(self.tail_config());solver=model.build_solver(p["cases"][0],p["settings"])
        self.assertEqual(solver.num_panels,p["panels_per_case"])
        self.assertEqual(solver.num_panels,8)
        solver.run(prescribed_wake=True,calculate_streamlines=False,show_progress=False)
        moments=[]
        for problem in solver.steady_problems:
            a=problem.airplanes[0]
            self.assertEqual(len(a.wings),1)
            np.testing.assert_allclose(a.wings[0].children_T_pas_Wcs_Lp_to_G_Cg[0][:3,3],0,atol=1e-12)
            thrust,lift=model.single_wing_forces(a)
            self.assertAlmostEqual(thrust,-a.inducedDrag_W,places=10)
            self.assertAlmostEqual(lift,a.lift_W,places=10)
            moment=model.wing_root_roll_moment(a)
            self.assertAlmostEqual(-moment,a.rollingMoment_W_Cg,places=10)
            moments.append(moment)
        self.assertGreater(np.max(np.abs(moments)),.01)

    def test_isolated_rejects_tail_and_mixed_comparison(self):
        c=self.tail_config();c['tail']['enabled']=True
        with self.assertRaisesRegex(ValueError,'tail'):model.plan(c)
        rows=self.rows();rows[0]['simulation_mode']='legacy_paired'
        with self.assertRaises(ValueError):model.comparison_data(rows,['span_m','incidence_deg'],'mean_thrust_N',{})

    def test_wake_controls_and_legacy_defaults(self):
        c=self.config();c["settings"].pop("wake_model");c["settings"].pop("wake_cycles")
        p=model.plan(c);self.assertEqual(p["settings"]["wake_model"],"free");self.assertEqual(p["settings"]["wake_cycles"],0)
        c["settings"].update(wake_model="prescribed",wake_cycles=1)
        p=model.plan(c);solver=model.build_solver(p["cases"][0],p["settings"])
        self.assertEqual(solver.unsteady_problem.max_wake_rows,math.ceil(1/p["settings"]["frequency_hz"]/p["settings"]["dt_s"]))
        for key,value in (("wake_cycles",-1),("wake_cycles",1.5),("wake_model","other")):
            bad=copy.deepcopy(c);bad["settings"][key]=value
            with self.assertRaises(ValueError):model.plan(bad)
        rows=self.rows();rows[0]["wake_model"]="prescribed"
        with self.assertRaisesRegex(ValueError,"Wake model"):
            model.comparison_data(rows,["span_m","incidence_deg"],"mean_thrust_N",{})

    def test_unfolded_gull_pattern_and_separate_sides(self):
        c=self.custom_config()
        for s in c["designs"][0]["sections"]:s["pitch_deg"]=0
        p=model.plan(c);case=p["cases"][0]
        le,te=model.flat_pattern(case,p["settings"]);st=case["geometry"]["stations"]
        for i,s in enumerate(st):self.assertAlmostEqual(np.linalg.norm(te[i]-le[i]),s["chord_m"],places=12)
        for i in range(len(st)-1):
            for flat,key in ((le,"le"),(te,"te")):
                self.assertAlmostEqual(np.linalg.norm(flat[i+1]-flat[i]),np.linalg.norm(np.array(st[i+1][key])-st[i][key]),places=12)
        self.assertGreater(le[-1][1],st[-1]["y_m"])
        with tempfile.TemporaryDirectory() as td:
            meta=model.save_wing_profiles(case,p["settings"],td)
            self.assertTrue(meta["profile_is_cutting_pattern"])
            self.assertEqual({f.name for f in Path(td).iterdir()},{"wing_left.svg","wing_right.svg"})
            import json
            ns={"s":"http://www.w3.org/2000/svg"};polys=[]
            for side in ("left","right"):
                root=ET.parse(Path(td)/f"wing_{side}.svg").getroot()
                self.assertEqual(json.loads(root.find("s:metadata",ns).text)["side"],side)
                polys.append(np.array([[float(v) for v in p.split(',')] for p in root.find("s:polygon",ns).get("points").split()]))
            np.testing.assert_allclose(polys[0][:,1],polys[1][:,1])
            np.testing.assert_allclose(polys[0][:,0]+polys[1][:,0],polys[0][0,0]+polys[1][0,0])
        twisted=model.plan(self.custom_config())
        with self.assertRaisesRegex(ValueError,"nonplanar"):model.flat_pattern(twisted["cases"][0],twisted["settings"])
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(model.save_wing_profiles(twisted["cases"][0],twisted["settings"],td)["profile_is_cutting_pattern"])

    def custom_config(self):
        c=self.config(); c["mode"]="custom"
        c["designs"]=[{"name":"Gull with twist","sections":[
            {"y_m":0,"x_m":0,"chord_m":.15,"pitch_deg":5,"roll_deg":20},
            {"y_m":.15,"x_m":.02,"chord_m":.13,"pitch_deg":3,"roll_deg":-15},
            {"y_m":.3,"x_m":.05,"chord_m":.07,"pitch_deg":0,"roll_deg":0}]}]
        return c

    def test_custom_native_geometry_and_mirror(self):
        p=model.plan(self.custom_config()); case=p["cases"][0]
        self.assertEqual(p["case_count"],1)
        self.assertGreater(case["geometry"]["stations"][1]["z_m"],case["geometry"]["stations"][2]["z_m"])
        solver=model.build_solver(case,p["settings"])
        wings=solver.steady_problems[0].airplanes[0].wings
        positions,frames=model.custom_frames(case)
        for w in wings:
            # Check the native section transforms against all intended endpoints.
            actual=[]
            for i,t in enumerate(w.children_T_pas_Wcs_Lp_to_G_Cg):
                a=t@np.array([0,0,0,1]);b=t@np.array([case["sections"][i]["chord_m"],0,0,1])
                actual.extend([a[:3],b[:3]])
            expected=[]
            for s in case["geometry"]["stations"]:
                expected.extend([np.array(s[k]) for k in ("le","te")])
            if actual[0][1]<0:expected=[v*np.array([1,-1,1]) for v in expected]
            np.testing.assert_allclose(actual,expected,atol=1e-10)
        for step in (0,7,15):
            ws=solver.steady_problems[step].airplanes[0].wings
            def verts(w):return np.array([getattr(v,k) for v in w.panels.flat for k in ("Frpp_G_Cg","Flpp_G_Cg","Blpp_G_Cg","Brpp_G_Cg")])
            self.assertEqual(len(ws),1)
            self.assertTrue(np.isfinite(verts(ws[0])).all())
            self.assertTrue(all(v.area>0 for w in ws for v in w.panels.flat))
        self.assertEqual(solver.num_panels,p["panels_per_case"])

    def test_custom_queue_and_constraints(self):
        c=self.custom_config(); c["designs"].append(copy.deepcopy(c["designs"][0]));c["designs"][1]["name"]="Second"
        self.assertEqual(model.plan(c)["case_count"],1)
        self.assertEqual(model.plan(c)["duplicate_geometry_count"],1)
        c["designs"][0]["sections"][1]["y_m"]=0
        with self.assertRaisesRegex(ValueError,"increase"):model.plan(c)
        c=self.custom_config();c["designs"][0]["sections"][1]["chord_m"]=0
        with self.assertRaisesRegex(ValueError,"subsequent"):model.plan(c)
        c=self.custom_config();c["designs"]=[]
        with self.assertRaisesRegex(ValueError,"at least one"):model.plan(c)
        c=self.custom_config();c["designs"][0]["sections"]*=4
        with self.assertRaisesRegex(ValueError,"span panels"):model.plan(c)

    def test_custom_svg_projection_and_csv(self):
        p=model.plan(self.custom_config());c=p["cases"][0]
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"wing.svg";model.save_wing_profile(c,p["settings"],path)
            root=ET.parse(path).getroot();ns={"s":"http://www.w3.org/2000/svg"}
            import json
            meta=json.loads(root.find("s:metadata",ns).text)
            self.assertFalse(meta["flat_cutting_pattern"])
            self.assertEqual(meta["sections"],c["sections"])
            self.assertEqual(json.loads(model.csv_row(c)["sections"]),c["sections"])

    def config(self):
        c=copy.deepcopy(model.DEFAULT);c["mode"]="sweep";return c

    def test_range_and_zero_speed(self):
        self.assertEqual(model.values("0.4:0.8:0.1", "test"), [.4,.5,.6,.7,.8])
        config = self.config(); config["settings"]["speed_mps"] = 0
        with self.assertRaisesRegex(ValueError, "stationary"):
            model.plan(config)
        config = self.config(); config["sweep"]["span_m"] = "1.0, 2.0, 12.0"
        config["sweep"]["root_chord_m"] = "4.0"
        planned = model.plan(config)
        self.assertEqual({c["span_m"] for c in planned["cases"]},{1.,2.,12.})
        self.assertTrue(all(c["root_chord_m"]==4. for c in planned["cases"]))
        config["sweep"]["span_m"] = str(config["settings"]["gap_m"])
        with self.assertRaisesRegex(ValueError,"hinge gap"):
            model.plan(config)

    def test_optional_chord_limits(self):
        config = self.config(); config["limits"]["min_chord_m"] = .1
        planned = model.plan(config)
        self.assertEqual(planned["skipped"],4)
        for c in planned["cases"]:
            self.assertGreaterEqual(min(s["chord_m"] for s in c["geometry"]["stations"]), .1)

    def test_every_geometry_axis_is_cartesian(self):
        config=self.config()
        config["sweep"]={"span_m":".6, 1.2", "root_chord_m":".1,.2", "tip_ratio":".5,1",
                         "mid_ratio":".75,1", "sweep_deg":"0,15", "incidence_deg":"0,8"}
        p=model.plan(config)
        self.assertEqual(p["case_count"],64)
        for key, text in config["sweep"].items():
            self.assertEqual({c[key] for c in p["cases"]},set(model.values(text,key)))
        for key in model.MOTION_KEYS:
            self.assertEqual({c[key] for c in p["cases"]},{config["settings"][key]})

    def test_fixed_inputs_reject_lists(self):
        for key in (*model.MOTION_KEYS,"rho","dt_s","cycles","span_panels"):
            config=self.config(); config["settings"][key]="1, 2"
            with self.assertRaisesRegex(ValueError,"constant across"):
                model.plan(config)

    def test_large_design_space_and_editable_budget(self):
        config=self.config()
        for key,text in {"span_m":".6,.8,1,1.2", "root_chord_m":".1,.15,.2,.25",
                         "tip_ratio":".4,.6,.8,1", "mid_ratio":".5,.7,.9,1",
                         "sweep_deg":"0,10", "incidence_deg":"0,8"}.items():
            config["sweep"][key]=text
        self.assertEqual(model.plan(config)["case_count"],1024)
        config["settings"]["case_budget"]=500
        with self.assertRaisesRegex(ValueError,"case budget"):
            model.plan(config)

    def test_time_resolution(self):
        config=self.config(); config["settings"]["dt_s"]=.1
        with self.assertRaisesRegex(ValueError,"30 steps"):
            model.plan(config)

    def test_cycle_mean_sign_and_settling(self):
        t=np.linspace(0,4,401)
        thrust=2+np.sin(2*np.pi*t)
        lift=-3+.5*np.cos(2*np.pi*t)
        r=model.cycle_metrics(t,thrust,lift,1,5)
        self.assertAlmostEqual(r["mean_thrust_N"],2,places=10)
        self.assertAlmostEqual(r["mean_lift_N"],-3,places=10)
        self.assertTrue(r["cycle_repeatable"])
        self.assertAlmostEqual(r["peak_thrust_N"],3,places=10)
        r=model.cycle_metrics(t,thrust+t,lift,1,5)
        self.assertFalse(r["cycle_repeatable"])
        r=model.cycle_metrics(t,np.zeros_like(t),np.zeros_like(t),1,5)
        self.assertTrue(r["cycle_repeatable"])

    def test_geometry_symmetry_and_water(self):
        config=self.config(); config["sweep"]["sweep_deg"]="12"
        config["sweep"]["incidence_deg"]="7"
        p=model.plan(config); case=p["cases"][0]
        solver=model.build_solver(case,p["settings"])
        first=solver.steady_problems[0]
        op=first.operating_point
        self.assertEqual(op.rho,998.2); self.assertEqual(op.nu,1.004e-6)
        self.assertEqual(op.vCg__E,.5)
        # A stock OperatingPoint is used, without an adapter or modified implementation.
        self.assertEqual(type(op).__name__,"OperatingPoint")
        for step in (0,7,15):
            wings=solver.steady_problems[step].airplanes[0].wings
            self.assertEqual(len(wings),1)
            def vertices(wing):
                return np.array([getattr(panel,name) for panel in wing.panels.flat
                                 for name in ("Frpp_G_Cg","Flpp_G_Cg","Blpp_G_Cg","Brpp_G_Cg")])
            self.assertGreaterEqual(vertices(wings[0])[:,1].min(),-1e-12)
        self.assertEqual(solver.num_panels,p["settings"]["span_panels"]*p["settings"]["chord_panels"])
        # The side preview uses the same root-pitch convention as the actual mesh.
        neutral=vertices(first.airplanes[0].wings[0])
        np.testing.assert_allclose(neutral[:,2],-neutral[:,0]*math.tan(math.radians(7)),atol=1e-10)
        # Check the actual neutral unpitched outline against the intended stations.
        flat=self.config(); flat["sweep"]["incidence_deg"]="0"; flat["sweep"]["sweep_deg"]="12"
        fp=model.plan(flat); fc=fp["cases"][0]; fs=model.build_solver(fc,fp["settings"])
        v=vertices(fs.steady_problems[0].airplanes[0].wings[0])
        self.assertAlmostEqual(np.max(v[:,1]),(fc["span_m"]-fp["settings"]["gap_m"])/2)
        area=sum(p.area for w in fs.steady_problems[0].airplanes[0].wings for p in w.panels.flat)
        self.assertAlmostEqual(area,fc["geometry"]["area_m2"]/2,places=9)

    def rows(self):
        config=self.config()
        config["sweep"]["span_m"]=".6,1.2"
        config["sweep"]["incidence_deg"]="0,8"
        p=model.plan(config)
        return [{**c,**{k:p["settings"][k] for k in ("rho","nu","dt_s","cycles","span_panels","chord_panels")},
                 "status":"ok", "cycle_repeatable":True,
                 "mean_thrust_N":10*c["span_m"]+c["tip_ratio"]+c["incidence_deg"]*.1} for c in p["cases"]]

    def test_max_projection_retains_winning_geometry(self):
        d=model.comparison_data(self.rows(),["span_m","incidence_deg"],"mean_thrust_N",{},"max")
        self.assertEqual(len(d["points"]),4)
        self.assertEqual(d["source_case_count"],8)
        self.assertEqual(d["reduced_over"],["tip_ratio"])
        for p in d["points"]:
            self.assertEqual(p["count"],2); self.assertEqual(p["inputs"]["tip_ratio"],.8)
            self.assertAlmostEqual(p["value"],10*p["coords"][0]+.8+p["coords"][1]*.1)

    def test_three_axes_exact_points_and_slice_filters(self):
        rows=self.rows()
        d=model.comparison_data(rows,["span_m","incidence_deg","tip_ratio"],"mean_thrust_N",{},"slice")
        self.assertEqual(len(d["points"]),8)
        self.assertTrue(all(p["count"]==1 for p in d["points"]))
        with self.assertRaisesRegex(ValueError,"More than one case"):
            model.comparison_data(rows,["span_m","incidence_deg"],"mean_thrust_N",{},"slice")
        d=model.comparison_data(rows,["span_m","incidence_deg"],"mean_thrust_N",{"tip_ratio":"0.5"},"slice")
        self.assertEqual(len(d["points"]),4)

    def test_never_reduce_over_dynamics(self):
        rows=self.rows(); rows[0]["frequency_hz"]=2
        with self.assertRaisesRegex(ValueError,"Flapping frequency"):
            model.comparison_data(rows,["span_m","incidence_deg"],"mean_thrust_N",{})

    def test_repeatability_filter_before_selecting_winner(self):
        rows=self.rows()
        for r in rows:
            if r["tip_ratio"]==.8: r["cycle_repeatable"]=False
        d=model.comparison_data(rows,["span_m","incidence_deg"],"mean_thrust_N",{},repeat_only=True)
        self.assertTrue(all(p["inputs"]["tip_ratio"]==.5 for p in d["points"]))

    def test_shared_history_and_legacy_readback(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            study=Path(tmp); rows=self.rows()
            model.write_json(study/"manifest.json", {"cases":rows,"settings":{}})
            model.write_summary(study, rows)
            data=[[0,1,2,3,4,5,6,7,8],[.02,2,3,4,5,6,7,8,9]]
            with (study/"comparisons"/"time_histories.csv").open("w",newline="") as f:
                writer=csv.writer(f); writer.writerow(["case",*model.HISTORY_COLUMNS])
                writer.writerows(["case_0001",*r] for r in data)
                writer.writerow(["case_0002",*([99]*len(model.HISTORY_COLUMNS))])
            self.assertEqual(model.case_data(study,"case_0001")["history"],data)
            legacy=study/"case_0001"; legacy.mkdir()
            np.savetxt(legacy/"forces.csv",np.array(data),delimiter=",",header=",".join(model.HISTORY_COLUMNS),comments="")
            self.assertEqual(model.case_data(study,"case_0001")["history"],data)

    def test_svg_physical_scale_symmetry_and_chords(self):
        config=self.config()
        config["sweep"].update(span_m="1.2",sweep_deg="-20",incidence_deg="35")
        spec=model.plan(config); case=spec["cases"][0]
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            path=Path(tmp)/"wing_profile.svg"
            model.save_wing_profile(case,spec["settings"],path)
            svg=ET.parse(path).getroot(); ns={"s":"http://www.w3.org/2000/svg"}
            view=list(map(float,svg.attrib["viewBox"].split()))
            self.assertEqual(float(svg.attrib["width"][:-2]),view[2])
            self.assertEqual(float(svg.attrib["height"][:-2]),view[3])
            self.assertTrue(svg.attrib["width"].endswith("mm"))
            def vertices(name):
                poly=svg.find(f".//s:polygon[@id='{name}']",ns)
                return np.array([list(map(float,p.split(','))) for p in poly.attrib["points"].split()])
            left,right=vertices("left-wing"),vertices("right-wing")
            self.assertAlmostEqual(np.max(right[:,0])-np.min(left[:,0]),1200.,places=6)
            np.testing.assert_allclose(left[:,0]+right[:,0],view[2],atol=1e-6)
            np.testing.assert_allclose(left[:,1],right[:,1],atol=1e-6)
            self.assertAlmostEqual(right[0,0]-left[0,0],40.,places=6)
            for i,ratio in enumerate((1,case["mid_ratio"],case["tip_ratio"])):
                self.assertAlmostEqual(right[5-i,1]-right[i,1],1000*case["root_chord_m"]*ratio,places=5)
            self.assertAlmostEqual((right[2,1]-right[0,1])/(right[2,0]-right[0,0]),math.tan(math.radians(-20)),places=8)
            bar=svg.find("s:line[@id='scale-check']",ns)
            self.assertEqual(float(bar.attrib["x2"])-float(bar.attrib["x1"]),100.)
            self.assertTrue(np.all(right>=0) and np.all(right[:,0]<=view[2]) and np.all(right[:,1]<=view[3]))

    def test_svg_is_flat_not_pitch_projected(self):
        spec=model.plan(self.config()); case=spec["cases"][0]
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            path=Path(tmp)/"profile.svg"; outlines=[]
            for pitch in (0.,45.):
                model.save_wing_profile({**case,"incidence_deg":pitch},spec["settings"],path)
                svg=ET.parse(path).getroot()
                outlines.append([p.attrib["points"] for p in svg.iter("{http://www.w3.org/2000/svg}polygon")])
            self.assertEqual(*outlines)

    def test_comparison_export_and_top_performers(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            study=Path(tmp); rows=self.rows()
            for r in rows:r.update(shape_ratio_valid=True,single_wing_thrust_roll_ratio_1pm=r["mean_thrust_N"],single_wing_mean_thrust_N=r["mean_thrust_N"],single_wing_peak_abs_roll_moment_Nm=1.)
            rows.append({"id":"case_9999","status":"failed"})
            model.write_summary(study,rows)
            with (study/"comparisons"/"top_performers.csv").open(newline="") as f:
                ranked=list(csv.DictReader(f))
            self.assertEqual(len(ranked),8)
            self.assertEqual(ranked[0]["shape_rank"],"1")
            self.assertEqual(float(ranked[0]["mean_thrust_N"]),max(r["mean_thrust_N"] for r in rows[:-1]))
            with patch.object(model,"OUTPUTS",study):
                spec=model.design_plot(study,["span_m","tip_ratio"],"mean_thrust_N",{})
            stem=study/Path(spec["file"]).with_suffix("")
            self.assertEqual({p.suffix for p in stem.parent.glob(stem.name+".*")},{".png",".csv"})
            with stem.with_suffix(".csv").open(newline="") as f:
                records=list(csv.DictReader(f))
            self.assertEqual(len(records),4)
            self.assertIn("mean_lift_N",records[0])
            self.assertIn("cycle_repeatable",records[0])


if __name__ == "__main__":
    unittest.main()
