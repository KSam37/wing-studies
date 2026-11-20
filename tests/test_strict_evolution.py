import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import tempfile
import csv
import unittest
from pathlib import Path
from unittest.mock import patch
from wingstudy import adaptive
from wingstudy import model
from wingstudy import torque_frontier
import test_adaptive
from test_torque_study import row


class StrictEvolutionChecks(unittest.TestCase):
    def test_rule_rejects_tradeoffs_and_accepts_either_nonworsening_improvement(self):
        parent=row('parent',10,2)
        for t,m in [(11,2.01),(9,1),(10,2)]:
            self.assertFalse(adaptive.improves(row('trial',t,m),parent))
        self.assertTrue(adaptive.improves(row('trial',11,2),parent))
        self.assertTrue(adaptive.improves(row('trial',11,1.9),parent))
        self.assertTrue(adaptive.improves(row('trial',10,1),parent))
        self.assertFalse(adaptive.improves(row('trial',11,2.000000000001),parent))

    def test_only_chosen_dominating_neighbor_becomes_parent(self):
        c=test_adaptive.AdaptiveChecks().config()
        c['adaptive_search'].update(acceptance_rule='strict_thrust_nonincreasing_torque',max_passes=3)
        r=adaptive.options(model,c);seed=adaptive.seed(r);seen={};events=[]
        def evaluate(chords,meta):
            t=10+sum(chords);m=2-sum(chords)
            # A tempting high-thrust/high-torque candidate must be rejected.
            if chords[-1]>seed[-1]:t=100;m=3
            result=row(str(len(seen)+1),t,m);seen[result['id']]=(result,meta)
            return result
        adaptive.run_search(r,evaluate,events.append)
        self.assertGreater(len(events),1)
        self.assertEqual(events[0]['evolution_role'],'seed')
        for before,after in zip(events,events[1:]):
            self.assertTrue(adaptive.improves(after['case'],before['case']))
            self.assertEqual(after['parent_case'],before['case']['id'])
        self.assertTrue(all(e['case']['single_wing_mean_thrust_N']<100 for e in events))
        self.assertLess(len(events),len(seen))

    def test_plot_filters_history_and_preserves_seeds_and_reuse(self):
        seed=row('case_0001',10,2);winner=row('case_0002',11,1.9)
        tradeoff=row('case_0003',12,2.1);trial=row('case_0004',9,2)
        events=[{'case':seed,'kind':'seed','parent_case':None},
            {'case':winner,'parent_case':seed['id']},
            {'case':tradeoff,'parent_case':seed['id']}]
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp,patch.object(model,'OUTPUTS',Path(temp)):
            study=Path(temp)/'saved';study.mkdir();model.write_json(study/'evolution.json',events)
            rows=[{**r,'_study':'saved'} for r in (seed,winner,tradeoff,trial)]
            self.assertEqual([r['id'] for r in torque_frontier.evolution_rows(model,rows)],['case_0001','case_0002'])
            self.assertEqual([r['id'] for r in torque_frontier.evolution_rows(model,rows,False)],['case_0002'])
            reused={**winner,'id':'case_0099','_study':'other','occurrences':[{'study':'saved','local_case':winner['id']}]}
            self.assertEqual(len(torque_frontier.evolution_rows(model,[reused])),1)

    def test_evolution_plot_keeps_dominated_ancestors_without_background_trials(self):
        sections=[{'x_m':0,'pitch_deg':0,'roll_deg':0,'y_m':y,'chord_m':c} for y,c in [(0,.2),(.3,.1)]]
        seed=row('case_0001',10,2,sections=sections)
        winner=row('case_0002',10,1.9,sections=sections)
        trial=row('case_0003',100,3,sections=sections)
        events=[{'case':seed,'kind':'seed','parent_case':None},{'case':winner,'parent_case':seed['id']}]
        with tempfile.TemporaryDirectory(dir=model.HERE) as temp,patch.object(model,'OUTPUTS',Path(temp)):
            study=Path(temp)/'saved';study.mkdir()
            model.write_json(study/'manifest.json',{'settings':{}})
            model.write_json(study/'results.json',[seed,winner,trial]);model.write_json(study/'evolution.json',events)
            for include,count in [(True,2),(False,1)]:
                result=torque_frontier.generate(model,{'study':'saved','comparison_mode':'evolution','include_seeds':include,'minimum_spacing_nm':100})
                self.assertEqual(len(result['points']),count)
                self.assertEqual(len(result['displayed']),count)
                self.assertEqual(result['background_count'],0)
                with (Path(temp)/result['files'][1]).open() as f:
                    exported=list(csv.DictReader(f))
                self.assertEqual(len(exported),count)
                self.assertNotIn('case_0003',[r['case'] for r in exported])


if __name__=='__main__':unittest.main()
