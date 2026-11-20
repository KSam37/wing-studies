"""Behavioral checks for seed diversity, guaranteed refinement and safe reuse."""
import _paths  # noqa: F401  (repo root on sys.path)
import copy
import unittest
from wingstudy import adaptive
from wingstudy import catalog
from wingstudy.case_identity import geometry_id
from wingstudy import model
import test_adaptive
from test_torque_study import row


class SearchReviewChecks(unittest.TestCase):
    def test_five_distinct_seeds_and_positive_default_bounds(self):
        c=test_adaptive.AdaptiveChecks().config()
        c['adaptive_search'].update(node_count=8,decreasing=True,seed_families=list(adaptive.SEED_FAMILIES))
        p=adaptive.plan(model,c);r=p['adaptive_search']
        shapes=[adaptive.seed(r,f) for f in adaptive.SEED_FAMILIES]
        self.assertEqual(len({tuple(x) for x in shapes}),5)
        self.assertEqual(p['search_job_count'],5)
        self.assertTrue(all(b['min_m']==.01 for b in r['bounds']))
        self.assertTrue(all(adaptive.valid(x,r) for x in shapes))
        self.assertLess(shapes[2][3],shapes[0][3])
        self.assertGreater(shapes[3][3],shapes[0][3])
        self.assertLess(shapes[4][0],shapes[0][0])
        self.assertEqual(shapes[4],[.1]*8)
        c['adaptive_search']['seed_families']=['unknown']
        with self.assertRaises(ValueError):adaptive.plan(model,c)

    def test_archive_growth_cannot_starve_fine_polls(self):
        c=test_adaptive.AdaptiveChecks().config();c['adaptive_search'].update(max_passes=4,initial_step_m=.04,minimum_step_m=.01)
        r=adaptive.options(model,c);seen=[]
        def evaluate(chords,meta):
            seen.append(meta)
            # Every geometry trades more thrust for more torque, growing archive.
            area=sum(chords)
            return row(str(len(seen)),area,area*area)
        adaptive.run_search(r,evaluate)
        steps={tuple(m['poll_steps_m']) for m in seen if m['pass']}
        self.assertIn((.04,)*3,steps)
        self.assertIn((.02,)*3,steps)
        self.assertIn((.01,)*3,steps)
        second=[m for m in seen if m['pass']==2]
        self.assertEqual(len({m['parent_case'] for m in second}),1)

    def test_geometry_reference_ignores_extra_stations_but_reuse_does_not(self):
        c=test_adaptive.AdaptiveChecks().config();c['adaptive_search'].update(node_count=3)
        a=adaptive.plan(model,c);c['adaptive_search']['node_count']=5;b=adaptive.plan(model,c)
        self.assertEqual(geometry_id(a['cases'][0]),geometry_id(b['cases'][0]))
        self.assertNotEqual(catalog.signature(model,a['cases'][0],a['settings']),catalog.signature(model,b['cases'][0],b['settings']))
        changed=copy.deepcopy(a['settings']);changed['dt_s']*=.75
        self.assertNotEqual(catalog.signature(model,a['cases'][0],a['settings']),catalog.signature(model,a['cases'][0],changed))
        wider=copy.deepcopy(a['cases'][0]);wider['geometry']['stations'][0]['te'][0]+=.001
        self.assertNotEqual(geometry_id(a['cases'][0]),geometry_id(wider))

    def test_bounded_polls_reach_finer_steps_under_shared_budget(self):
        c=test_adaptive.AdaptiveChecks().config()
        c['adaptive_search'].update(node_count=8,poll_candidates=8,max_passes=3,initial_step_m=.04)
        r=adaptive.options(model,c);seen=[]
        def evaluate(chords,meta):
            seen.append(meta)
            return row(str(len(seen)),sum(chords),sum(chords)**2)
        adaptive.run_search(r,evaluate)
        self.assertLessEqual(len(seen),25)
        self.assertEqual({max(m['poll_steps_m']) for m in seen if m['pass']},{.04,.02,.01})

    def test_single_budget_ignores_old_pass_and_request_limits(self):
        c=test_adaptive.AdaptiveChecks().config()
        c['adaptive_search'].update(budget_only=True,max_passes=1,evaluation_budget=1,simulation_budget=1,
            seed_families=list(adaptive.SEED_FAMILIES))
        r=adaptive.options(model,c)
        self.assertIsNone(r['max_passes'])
        self.assertIsNone(r['evaluation_budget'])
        self.assertEqual(r['simulation_budget'],1)
        seen=[]
        def evaluate(chords,meta):
            if meta['pass']>=2:raise adaptive.BudgetReached('test stop')
            seen.append(meta)
            return row(str(len(seen)),sum(chords),sum(chords)**2)
        with self.assertRaises(adaptive.BudgetReached):adaptive.run_search(r,evaluate)
        self.assertGreater(len(seen),1)


if __name__=='__main__':unittest.main()
