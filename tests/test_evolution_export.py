import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from wingstudy import model
import evolution_export

class EvolutionExportChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=model.HERE)
        self.root=Path(self.temp.name);self.study=self.root/'study';self.study.mkdir()
        self.rows=[]
        for i,parent in [(1,None),(2,'case_0001'),(3,'case_0002'),(4,'case_0001')]:
            self.rows.append({'id':f'case_{i:04d}','status':'ok','single_wing_mean_thrust_N':i,'single_wing_peak_abs_roll_moment_Nm':1.,
                'adaptive_trial':{'parent_case':parent},'sections':[{'y_m':0.,'x_m':0.,'chord_m':.2-i*.01,'pitch_deg':0.,'roll_deg':0.},{'y_m':.3,'x_m':0.,'chord_m':.02,'pitch_deg':0.,'roll_deg':0.}]})
        model.write_json(self.study/'results.json',self.rows)
        model.write_json(self.study/'evolution.json',[{'job':1,'case':r} for r in self.rows[:3]])
    def tearDown(self):self.temp.cleanup()
    def test_selected_accepted_wing_excludes_later_descendants(self):
        self.assertEqual([r['id'] for r in evolution_export.lineage(model,self.study,'case_0002')],['case_0001','case_0002'])
    def test_rejected_trial_uses_its_own_parent_chain(self):
        self.assertEqual([r['id'] for r in evolution_export.lineage(model,self.study,'case_0004')],['case_0001','case_0004'])
    def test_pareto_gif_follows_parents_not_sibling_discoveries(self):
        for r in self.rows:r['adaptive_trial']['objective']='pareto_mean_thrust_peak_root_torque_v1'
        model.write_json(self.study/'results.json',self.rows)
        model.write_json(self.study/'evolution.json',[{'job':1,'case':r} for r in self.rows])
        self.assertEqual([r['id'] for r in evolution_export.lineage(model,self.study,'case_0004')],['case_0001','case_0004'])

    def test_seed_and_missing_history(self):
        self.assertEqual(len(evolution_export.lineage(model,self.study,'case_0001')),1)
        with self.assertRaises(ValueError):evolution_export.lineage(model,self.study,'../case_0001')
        self.rows[3].pop('adaptive_trial');model.write_json(self.study/'results.json',self.rows)
        with self.assertRaisesRegex(ValueError,'No adaptive'):evolution_export.lineage(model,self.study,'case_0004')
    def test_gif_contains_actual_recorded_frames_and_preserves_history(self):
        before=(self.study/'evolution.json').read_bytes()
        with patch.object(model,'OUTPUTS',self.root):result=evolution_export.export_gif(model,self.study,'case_0002')
        self.assertEqual(result['case_ids'],['case_0001','case_0002'])
        with Image.open(self.root/result['file']) as gif:
            self.assertEqual(gif.format,'GIF');self.assertEqual(gif.n_frames,2)
            self.assertEqual(gif.size,(600,360))
        self.assertEqual((self.study/'evolution.json').read_bytes(),before)

if __name__=='__main__':unittest.main()
