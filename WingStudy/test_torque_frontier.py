import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import model
import torque_frontier as frontier
from test_torque_study import row

class FrontierChecks(unittest.TestCase):
    def test_band_winner_is_highest_thrust_not_highest_ratio(self):
        rows=[row('ratio',2,.1),row('thrust',3,.8),row('boundary',4,1),row('final',5,2)]
        chosen=frontier.band_winners(rows,0,2,1)
        self.assertEqual([r['id'] for r in chosen],['thrust','final'])
        self.assertEqual([r['torque_band_count'] for r in chosen],[2,2])
        self.assertEqual(chosen[0]['torque_band_min_nm'],0)
        self.assertEqual(chosen[-1]['torque_band_max_nm'],2)
        self.assertTrue(chosen[-1]['torque_band_includes_upper'])
        self.assertEqual(frontier.band_winners(rows,0,5,1)[-1]['id'],'final')
        self.assertEqual(len(frontier.band_winners(rows,0,5,1)),3) # Empty bands not invented.
        self.assertEqual(frontier.band_winners([row('b',3,.8),row('a',3,.7)],0,1,1)[0]['id'],'a')
        decimal=frontier.band_winners([row('edge',1,.3),row('below',.5,.2999999999999)],0,.5,.1)
        self.assertEqual([r['torque_band_min_nm'] for r in decimal],[.2,.3])
        for width in (0,-1,float('nan')):
            with self.assertRaises(ValueError):frontier.band_winners(rows,0,2,width)

    def test_background_sampling_excludes_frontier_and_preserves_vertical_variety(self):
        rows=[row('top',10,1),row('mid',5,1),row('near',5.01,1.001),row('bottom',1,1)]
        sampled=frontier.sample_background(rows,[rows[0]],[rows[0]],.1,0,2)
        self.assertEqual({r['id'] for r in sampled},{'near','bottom'})
        self.assertEqual(len(frontier.sample_background(rows,[rows[0]],[rows[0]],0,0,2)),3)

    def test_native_results_require_explicit_selection_and_are_not_mixed(self):
        import torque_study
        rows=[row('rigid',2,.1),row('native',4,.2,aeroelastic_enabled=True)]
        self.assertEqual([r['id'] for r in torque_study.select_model(rows,'rigid')],['rigid'])
        selected=torque_study.select_model(rows,'aeroelastic')
        self.assertEqual([r['id'] for r in frontier.envelope(selected,allow_aeroelastic=True)[1]],['native'])
        self.assertEqual(frontier.envelope(selected)[1],[])
        with self.assertRaises(ValueError):torque_study.select_model(rows,'mixed')

    def test_spacing_preserves_best_end_and_full_frontier(self):
        rows=[row(str(i),i+1,t) for i,t in enumerate([.1,.11,.15,.2,.25,.31])]
        original=list(rows);shown=frontier.spaced_points(rows,.1)
        self.assertEqual(shown[-1],rows[-1])
        self.assertTrue(all(b[frontier.TORQUE]-a[frontier.TORQUE]>=.1-1e-12 for a,b in zip(shown,shown[1:])))
        self.assertEqual(frontier.spaced_points(rows,0),rows)
        self.assertEqual(rows,original)

    def test_best_at_or_below_each_torque_and_equal_torque_ties(self):
        rows=[row('low',2,.1),row('dominated',1,.2),row('high',5,.4),row('tie',4,.4),row('same_thrust',5,.8),row('final',8,1.2)]
        eligible,points=frontier.envelope(list(reversed(rows)))
        self.assertEqual([r['id'] for r in points],['low','high','final'])
        for cap in (.1,.15,.2,.4,.6,.8,1.2):
            chosen=[r for r in points if r[frontier.TORQUE]<=cap][-1]
            self.assertEqual(chosen[frontier.THRUST],max(r[frontier.THRUST] for r in eligible if r[frontier.TORQUE]<=cap))
        self.assertEqual(frontier.envelope(rows)[1],points)

    def test_excludes_invalid_unsettled_flexible_and_paired(self):
        rows=[row('good',1,0),row('over_old_limit',4,10),row('unsettled',9,.1),row('flexible',9,.1),row('paired',9,.1),row('nan',float('nan'),.1),row('negative',-1,.1)]
        rows[2]['cycle_repeatable']=False;rows[3]['aeroelastic_enabled']=True;rows[4]['simulation_mode']='paired'
        self.assertEqual([r['id'] for r in frontier.envelope(rows)[1]],['good','over_old_limit'])
        self.assertEqual(frontier.envelope([]),([],[]))

    def test_native_study_frontier_exports_model_and_material_parameters(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'native';study.mkdir()
            settings={'aeroelastic_enabled':True,'damping_constant_rad':10.,'spring_constant_rad':4.27,'wing_density':.5}
            model.write_json(study/'manifest.json',{'settings':settings})
            sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':0,'chord_m':.2},{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':.3,'chord_m':.1}]
            model.write_json(study/'results.json',[row('native',2,.3,aeroelastic_enabled=True,sections=sections,peak_abs_native_twist_deg=3.)])
            with patch.object(model,'OUTPUTS',root):
                result=frontier.generate(model,{'study':'native'})
                self.assertEqual(result['model_mode'],'aeroelastic')
                self.assertEqual(len(result['points']),1)
                with (root/result['files'][1]).open() as f:
                    data=list(csv.DictReader(f))[0]
                    self.assertEqual(data['model_mode'],'aeroelastic')
                    self.assertEqual(float(data['damping_constant_rad']),10.)
                    self.assertEqual(float(data['peak_abs_native_twist_deg']),3.)

    def test_exports_full_study_without_torque_cap_and_keeps_source_files(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'saved';study.mkdir()
            model.write_json(study/'manifest.json',{'settings':{'frequency_hz':1,'speed_mps':.5}})
            model.write_json(study/'results.json',[row('a',2,.1,sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':0,'chord_m':.2},{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':.3,'chord_m':.1}]),row('b',3,2,sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':0,'chord_m':.2},{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':.4,'chord_m':.05}])])
            before=(study/'results.json').read_bytes()
            with patch.object(model,'OUTPUTS',root):
                result=frontier.generate(model,{'study':'saved','maximum_root_moment_nm':.2})
                self.assertEqual(len(result['points']),2)
                self.assertEqual(len(result['displayed']),2)
                widths=[max(p[0] for p in r['outline_m'])-min(p[0] for p in r['outline_m']) for r in result['displayed']]
                self.assertEqual(widths,[.3,.4])
                self.assertEqual(result['maximum_torque_nm'],2)
                self.assertTrue((root/result['files'][0]).is_file())
                with (root/result['files'][1]).open() as f:
                    values=list(csv.DictReader(f))
                    self.assertEqual([r['case'] for r in values],['a','b'])
                    self.assertEqual(values[-1]['frequency_hz'],'1')
                bands=frontier.generate(model,{'study':'saved','comparison_mode':'bands','torque_band_width_nm':3,'minimum_spacing_nm':100})
                self.assertEqual([r['id'] for r in bands['points']],['b'])
                self.assertEqual(bands['background_count'],0)
                self.assertEqual(bands['points'][0]['torque_band_count'],2)
                with (root/bands['files'][1]).open() as f:
                    band_csv=list(csv.DictReader(f))
                    self.assertEqual([r['case'] for r in band_csv if r['is_band_winner']=='True'],['b'])
                    self.assertEqual(len(band_csv),2)
                zoom=frontier.generate(model,{'study':'saved','torque_min_nm':.2,'torque_max_nm':3})
                self.assertEqual(zoom['plotted_count'],1)
                self.assertEqual(len(zoom['points']),2) # Lower-torque winner remains available to slider.
                self.assertEqual(zoom['minimum_torque_nm'],.2)
                self.assertEqual(zoom['slider_maximum_torque_nm'],2)
                self.assertNotEqual(zoom['files'],result['files'])
                with (root/zoom['files'][1]).open() as f:self.assertEqual([r['case'] for r in csv.DictReader(f)],['b'])
                for lo,hi in [(-1,2),(2,1),(1,1),(3,4),(0,float('nan'))]:
                    with self.assertRaises(ValueError):frontier.generate(model,{'study':'saved','torque_min_nm':lo,'torque_max_nm':hi})
            self.assertEqual(before,(study/'results.json').read_bytes())

if __name__=='__main__':unittest.main()
