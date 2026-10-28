import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import model
import torque_frontier as frontier
from test_torque_study import row

class FrontierChecks(unittest.TestCase):
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

    def test_exports_full_study_without_torque_cap_and_keeps_source_files(self):
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            root=Path(temp);study=root/'saved';study.mkdir()
            model.write_json(study/'manifest.json',{'settings':{'frequency_hz':1,'speed_mps':.5}})
            model.write_json(study/'results.json',[row('a',2,.1,sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':0,'chord_m':.2},{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':.3,'chord_m':.1}]),row('b',3,2,sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':0,'chord_m':.2},{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':.4,'chord_m':.05}])])
            before=(study/'results.json').read_bytes()
            with patch.object(model,'OUTPUTS',root):
                result=frontier.generate(model,{'study':'saved','maximum_root_moment_nm':.2})
                self.assertEqual(len(result['points']),2)
                self.assertEqual(result['maximum_torque_nm'],2)
                self.assertTrue((root/result['files'][0]).is_file())
                with (root/result['files'][1]).open() as f:
                    values=list(csv.DictReader(f))
                    self.assertEqual([r['case'] for r in values],['a','b'])
                    self.assertEqual(values[-1]['frequency_hz'],'1')
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
