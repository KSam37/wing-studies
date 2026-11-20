import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from wingstudy import adaptive
from wingstudy import coordinate_search as search
from wingstudy import model
from wingstudy import torque_frontier
from test_adaptive import AdaptiveChecks
from test_torque_study import row


class CoordinateChecks(unittest.TestCase):
    def test_zero_global_minimum_plans_and_builds_native_connected_wing(self):
        c=AdaptiveChecks().config()
        c['adaptive_search'].update(acceptance_rule='coordinate',minimum_chord_m=0,
            node_count=4,bounds=[{'min_m':0} for _ in range(4)])
        spec=adaptive.plan(model,c);r=spec['adaptive_search']
        self.assertEqual(r['minimum_chord_m'],0)
        self.assertTrue(adaptive.valid([.2,.001,0,0],r))
        self.assertFalse(adaptive.valid([.2,0,.01,0],r))
        self.assertFalse(adaptive.valid([.2,0,0,0],r))
        self.assertFalse(adaptive.valid([.2,-1e-13,0,0],r))
        case=model.custom_case(adaptive.design(r,.6,spec['settings']['gap_m'],[.2,.001,0,0]),spec['settings'])
        self.assertEqual(case['active_chord_count'],2)
        self.assertIsNotNone(model.build_solver(case,spec['settings']))

    def options(self,**kwargs):
        c=AdaptiveChecks().config()
        c['adaptive_search'].update(acceptance_rule='coordinate',initial_step_m=.02,
            root_chord_m=.1,maximum_root_chord_m=.2,tip_chord_m=.04,seed_families=['triangle'],**kwargs)
        return adaptive.options(model,c)

    def drive(self, r, thrust):
        start=adaptive.seed(r);requests=[];events=[];counter=0
        def evaluate(chords,meta):
            nonlocal counter
            counter+=1;result=row(f'case_{counter:04d}',thrust(chords),1)
            result.update(adaptive_trial=copy.deepcopy(meta),seed_family='triangle')
            return result
        initial=evaluate(start,{'kind':'seed'})
        g=search.climb(r,.6,1,'triangle',(start,initial),{'thrust_scale_N':1.,'torque_scale_Nm':1.})
        try:
            pending=next(g)
            while True:
                if pending[0]=='accepted':events.append(pending[1]);pending=next(g)
                else:
                    batch=pending[1];requests.extend(copy.deepcopy(batch))
                    pending=g.send([evaluate(c,m) for c,m in batch])
        except StopIteration as done:return requests,events,done.value

    def test_cyclic_order_remembered_sign_and_single_half_step(self):
        r=self.options()
        requests,events,status=self.drive(r,lambda c:2-(c[0]-.15)**2-10*(c[1]-.07)**2-10*(c[2]-.04)**2)
        first=[m['node'] for c,m in requests if m['pass']==1 and m['kind']=='coordinate']
        self.assertEqual(first,[0,0,1,1,2,2])
        self.assertEqual([e['node'] for e in events[1:]],[0,0,0])
        self.assertEqual([e['chords'][0] for e in events],[.1,.12,.14,.15])
        root=[m for c,m in requests if m['node']==0]
        self.assertEqual([m['direction'] for m in root if m['pass']>1],[1,1,1])
        self.assertEqual(sum(m['refinement'] for m in root),1)
        self.assertEqual(status['status'],'one_refinement_per_chord_complete')
        self.assertTrue(all(b['weighted_score']>a['weighted_score'] for a,b in zip(events,events[1:])))

    def test_flat_initial_chord_gets_only_one_two_sided_refinement(self):
        r=self.options();requests,events,status=self.drive(r,lambda c:1.)
        self.assertEqual(len(events),1)
        for i in range(3):
            trials=[m for c,m in requests if m['node']==i]
            self.assertEqual([m['step_m'] for m in trials],[.02,.02,.01,.01])

    def test_width_zero_removes_tip_without_touching_other_widths(self):
        r=self.options(node_count=5,decreasing=True)
        self.assertEqual(search.move([.2,.1,.03,.01,0],3,-.02,r),[.2,.1,.03,0,0])
        self.assertEqual(search.move([.2,.1,.01,0,0],2,-.02,r),[.2,.1,0,0,0])
        proposed=search.move([.2,.1,.03,.02,0],2,-.04,r)
        self.assertEqual(proposed,[.2,.1,.02,.02,0])
        self.assertIsNone(search.move([.2,.1,0,0,0],4,.02,r))
        self.assertEqual(search.move([.2,.1,0,0,0],2,.02,r),[.2,.1,.02,0,0])
        self.assertEqual(search.move([.2,.01,0,0,0],1,-.02,r),None)

    def test_score_is_fixed_weighted_difference_and_allows_negative_thrust(self):
        scales={'thrust_scale_N':4,'torque_scale_Nm':2}
        self.assertAlmostEqual(search.score(row('a',4,2),scales,.75),.25)
        self.assertAlmostEqual(search.score(row('b',4.2,2.1),scales,.75),.2625)
        self.assertIsNotNone(search.score(row('c',-.1,1),scales,.75))

    def test_new_tip_can_shrink_after_its_previous_neighbor_is_removed(self):
        r=self.options(node_count=5,decreasing=True)
        r.update(root_chord_m=.01,tip_chord_m=.01)
        requests,events,status=self.drive(r,lambda c:2-sum(c))
        self.assertEqual(events[-1]['chords'],[.01,.01,0,0,0])
        self.assertEqual([e['node'] for e in events[1:]],[4,3,2])

    def test_independent_parent_chains_and_fixed_scales_despite_cache_reuse(self):
        r=self.options();r['seed_families']=['triangle','narrow'];r['simulation_budget']=200
        class Pipeline:
            stop_reason=None
            def __init__(self,study):self.model=model;self.study=study;self.rows=[];self.events=[];self.lookup={}
            def evaluate_many(self,inputs):
                result=[]
                for chords,meta in inputs:
                    key=(meta['span_m'],tuple(chords))
                    if key not in self.lookup:
                        value=2-sum((c-.08)**2 for c in chords)
                        x=row(f'case_{len(self.rows)+1:04d}',value,1)
                        x.update(adaptive_trial=copy.deepcopy(meta),seed_family=meta['seed_family'])
                        self.lookup[key]=x;self.rows.append(x)
                    result.append(self.lookup[key])
                return result
            def accept(self,event):self.events.append(copy.deepcopy(event))
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp:
            pipeline=Pipeline(Path(temp));search.run(r,pipeline)
            self.assertEqual(len({e['job'] for e in pipeline.events}),2)
            for job in (1,2):
                path=[e for e in pipeline.events if e['job']==job]
                self.assertIsNone(path[0]['parent_case'])
                self.assertTrue(all(e['parent_case']==prev['case']['id'] for prev,e in zip(path,path[1:])))
                self.assertEqual(len({e['thrust_scale_N'] for e in path}),1)
            data=model.read_json(Path(temp)/'coordinate_lineages.json')
            self.assertTrue(all(s['status']=='one_refinement_per_chord_complete' for s in data['lineages']))
            model.write_json(Path(temp)/'evolution.json',pipeline.events)
            with patch.object(model,'OUTPUTS',Path(temp).parent):
                selected=torque_frontier.evolution_rows(model,[{**x,'_study':Path(temp).name} for x in pipeline.rows])
            paths=torque_frontier.evolution_paths(selected)
            self.assertEqual(len(paths),2)
            self.assertTrue(all(len(p['points'])>=1 for p in paths))


if __name__=='__main__':unittest.main()
