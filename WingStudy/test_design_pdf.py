import unittest
from design_pdf import band_series,frontier
from lambda_review import THRUST,TORQUE


class ReportSelectionChecks(unittest.TestCase):
    def test_band_report_preserves_each_lambda_instead_of_picking_one_global_winner(self):
        studies=[{'id':s} for s in ('a','b','c')]
        rows=[{'id':s+str(i),'study':s,'_study':s,THRUST:t,TORQUE:m}
            for s,loads in [('a',[(1,.1),(3,.6)]),('b',[(2,.2),(2.5,.7)]),('c',[(1.5,.15),(2.8,.8)])]
            for i,(t,m) in enumerate(loads)]
        chosen=band_series(rows,studies,0,1,.5)
        self.assertEqual(len(chosen),6)
        self.assertEqual({r['study'] for r in chosen},{'a','b','c'})
        self.assertEqual([r[THRUST] for r in chosen if r['torque_band_min_nm']==0],[1,2,1.5])
    def test_envelope_keeps_lower_torque_design_and_rejects_dominated_points(self):
        rows=[{TORQUE:.2,THRUST:2,'study':'a','id':'low'},
            {TORQUE:1.1,THRUST:1.8,'study':'a','id':'dominated'},
            {TORQUE:1.5,THRUST:3,'study':'a','id':'high'}]
        self.assertEqual([r['id'] for r in frontier(rows)],['low','high'])


if __name__=='__main__':unittest.main()
