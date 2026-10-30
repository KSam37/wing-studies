import unittest
import convergence_report as report
from test_torque_study import row


class ConvergenceReportChecks(unittest.TestCase):
    def test_budget_plateau_is_not_certified_and_gains_use_correct_baseline(self):
        events=[{'job':-1,'kind':'seed','evaluation':1,'case':row('s',2,1)},
            {'job':1,'kind':'winner','span_m':.4,'torque_target_nm':2,'evaluation':1,'case':row('s',2,1)},
            {'job':1,'kind':'winner','span_m':.4,'torque_target_nm':2,'evaluation':9,'case':row('w',3,1.5)},
            {'job':2,'kind':'winner','span_m':.4,'torque_target_nm':.5,'evaluation':8,'case':row('f',.5,.4)}]
        results=[{'adaptive_trial':{'poll_steps_m':[.04]*3}} for _ in range(10)]
        a=report.analyze(events,results,[{'local_search_exhausted':False,'case_id':'w'}],{'minimum_step_m':.01})
        self.assertEqual(a['fine_trial_cases'],0)
        self.assertEqual(a['exhausted_targets'],0)
        self.assertEqual(a['records'][0]['gain_pct'],50)
        self.assertEqual(a['records'][0]['last_20pct_gain_pct'],50)
        self.assertEqual(a['records'][1]['baseline'],'first_feasible')
        self.assertTrue(a['records'][0]['monotone_thrust'])


if __name__=='__main__':unittest.main()
