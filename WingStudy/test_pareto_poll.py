import unittest
import adaptive
import model
import pareto_poll as poll
from test_torque_study import row


class PollChecks(unittest.TestCase):
    def test_hypervolume_known_area_and_dominated_duplicates(self):
        values=[(2,1),(4,3)]
        self.assertEqual(poll.hypervolume(values,5),12)
        self.assertEqual(poll.hypervolume(values+[(1,4),(4,3)],5),12)
        self.assertAlmostEqual(poll.hypervolume(values,5,5,5),.48)
        self.assertEqual(poll.hypervolume([(8,9)],5),0)

    def test_reference_expansion_recalculates_all_events_consistently(self):
        events=[]
        for i,t,m in [(1,2,1),(2,4,3),(3,7,8)]:
            events.append({'case':row(str(i),t,m),'frontier_case_ids':[str(j) for j in range(1,i+1)]})
        first=poll.refresh_hypervolume(events[:2]);old=events[0]['normalized_hypervolume']
        reference=poll.refresh_hypervolume(events)
        self.assertGreater(reference['reference_torque_Nm'],first['reference_torque_Nm'])
        self.assertNotEqual(old,events[0]['normalized_hypervolume'])
        self.assertEqual(sorted(e['normalized_hypervolume'] for e in events),[e['normalized_hypervolume'] for e in events])
        self.assertAlmostEqual(events[0]['normalized_hypervolume'],2*(8.8-1)/(7.7*8.8))

    def test_coordinated_moves_cross_a_coordinate_plateau_and_steps_are_local(self):
        from test_adaptive import AdaptiveChecks
        c=AdaptiveChecks().config()
        c['adaptive_search'].update(root_chord_m=.12,tip_chord_m=.04,initial_step_m=.02,minimum_step_m=.01,paired_moves=False,max_passes=8,coordinated_moves=True)
        r=adaptive.options(model,c);seed=adaptive.seed(r);seen=[];events=[]
        def evaluate(chords,meta):
            seen.append((chords,meta))
            return row(str(len(seen)),2 if all(x>y for x,y in zip(chords,seed)) else 1,1)
        adaptive.run_search(r,evaluate,events.append)
        improved=[e for e in events if e['case']['single_wing_mean_thrust_N']==2]
        self.assertTrue(improved)
        self.assertEqual(improved[0]['kind'],'whole_wing')
        child=improved[0]['case']['id']
        child_steps={tuple(meta['poll_steps_m']) for chords,meta in seen if meta['parent_case']==child}
        self.assertIn((.02,.02,.02),child_steps)
        self.assertIn((.01,.01,.01),child_steps)
        self.assertEqual(len({tuple(chords) for chords,meta in seen}),len(seen))

    def test_poll_basis_and_coupled_directions_are_bounded_and_unique(self):
        directions=poll.directions(8)
        self.assertEqual(len({weights for weights,kind in directions}),len(directions))
        for i in range(8):
            for sign in (-1,1):self.assertIn(tuple(sign if j==i else 0 for j in range(8)),[w for w,k in directions])
        self.assertTrue(any(kind=='whole_wing' for weights,kind in directions[:4]))
        self.assertTrue(all(max(abs(v) for v in weights)<=1 for weights,kind in directions))


if __name__=='__main__':unittest.main()
