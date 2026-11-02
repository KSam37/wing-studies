import copy
import tempfile
import unittest
from pathlib import Path
import numpy as np
import adaptive
import coordinate_search
import model
import refinement
from test_adaptive import AdaptiveChecks
from test_torque_study import row


class SelectedWingRefinementChecks(unittest.TestCase):
    def config(self):
        c=AdaptiveChecks().config()
        c['adaptive_search'].update(acceptance_rule='coordinate',seed_design={'name':'Saved wing','sections':[
            {'y_m':y,'x_m':x,'chord_m':w,'pitch_deg':0.,'roll_deg':0.} for y,x,w in [(0,0,.16),(.07,.01,.12),(.28,.04,.02)]]},
            node_count=9,bounds=[],minimum_chord_m=.01,initial_step_m=.005,maximum_root_chord_m=.2,
            reference_scales={'thrust_scale_N':12.,'torque_scale_Nm':14.},decreasing=True)
        return c

    def test_one_seed_same_outline_more_chords_smaller_steps_and_roundtrip(self):
        c=self.config();before=copy.deepcopy(c);p=adaptive.plan(model,c);r=p['adaptive_search']
        self.assertEqual(c,before);self.assertEqual(p['search_job_count'],1);self.assertEqual(len(p['cases']),1)
        self.assertEqual(len(p['cases'][0]['sections']),9)
        self.assertTrue(all(b['step_m']==.005 for b in r['bounds']))
        original=c['adaptive_search']['seed_design']['sections'];dense=r['seed_sections']
        self.assertTrue(all(s in dense for s in original))
        ys=[s['y_m'] for s in original]
        for s in dense:
            self.assertAlmostEqual(s['chord_m'],np.interp(s['y_m'],ys,[v['chord_m'] for v in original]))
        self.assertEqual(p['cases'],adaptive.plan(model,p['config'])['cases'])
        widths=adaptive.seed(r);widths[3]-=.001
        new=adaptive.design(r,r['span_min_m'],.04,widths)
        self.assertEqual([s['y_m'] for s in new['sections']],[s['y_m'] for s in dense])
        self.assertEqual([s['x_m'] for s in new['sections']],[s['x_m'] for s in dense])
        self.assertIsNotNone(model.build_solver(p['cases'][0],p['settings']))

    def test_rejects_out_of_bounds_seed_instead_of_silently_changing_it(self):
        c=self.config();c['adaptive_search']['maximum_root_chord_m']=.1
        with self.assertRaisesRegex(ValueError,'outside'):adaptive.plan(model,c)

    def test_inherits_source_weight_references_and_halves_step(self):
        c=self.config();c['adaptive_search'].pop('seed_design');c['adaptive_search'].update(node_count=3,initial_step_m=.02,bounds=[])
        sections=self.config()['adaptive_search']['seed_design']['sections']
        with tempfile.TemporaryDirectory(dir=model.HERE) as tmp:
            study=Path(tmp)
            model.write_json(study/'manifest.json',{'config':c,'settings':c['settings']})
            model.write_json(study/'results.json',[{'id':'case_0001','status':'ok','sections':sections}])
            model.write_json(study/'coordinate_objective.json',{'tradeoff_lambda':1.25,'thrust_scale_N':12.,'torque_scale_Nm':14.})
            cfg=refinement.coordinate_config(model,study,'case_0001');r=adaptive.plan(model,cfg)['adaptive_search']
            self.assertEqual(r['node_count'],16);self.assertEqual(r['initial_step_m'],.01)
            self.assertEqual(r['tradeoff_lambda'],1.25);self.assertEqual(r['reference_scales'],{'thrust_scale_N':12.,'torque_scale_Nm':14.})
            class Pipeline:
                stop_reason=None
                def __init__(self):self.model=model;self.study=study;self.events=[]
                def evaluate_many(self,inputs):return [row('case_0001',3,2) for _ in inputs]
                def accept(self,event):self.events.append(event)
            pipeline=Pipeline();coordinate_search.run(r,pipeline)
            saved=model.read_json(study/'coordinate_objective.json')
            self.assertEqual(saved['thrust_scale_N'],12.);self.assertEqual(saved['torque_scale_Nm'],14.)
            self.assertEqual(len(pipeline.events),1)
            self.assertAlmostEqual(pipeline.events[0]['weighted_score'],3/12-1.25*2/14)


if __name__=='__main__':unittest.main()
