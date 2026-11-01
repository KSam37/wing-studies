import unittest
from lambda_review import selection,THRUST,TORQUE


class SelectionChecks(unittest.TestCase):
    def setUp(self):
        def row(case,study,thrust,torque,final=False,accepted=False,sim=None):
            return {'id':case,'study':study,'_study':study,THRUST:thrust,TORQUE:torque,
                'is_final':final,'is_accepted':accepted,'simulation_id':sim or study+case}
        self.b={'studies':[{'id':'a'},{'id':'b'}],'rows':[
            row('seed','a',1,.25,accepted=True,sim='shared'),row('trial','a',4,.4),
            row('final','a',3,.35,True,True),row('seed','b',1,.25,accepted=True,sim='shared'),
            row('best','b',4,.38,True,True),row('edge','b',5,.5)]}
    def test_bands_choose_thrust_then_lower_torque_and_exact_edges(self):
        rows,w,*_=selection(self.b,{'maximum':.75,'band_width':.25})
        self.assertEqual([r['id'] for r in w],['best','edge'])
        self.assertEqual(w[0]['torque_band_count'],4)  # shared seed counted once
        self.assertEqual(w[1]['torque_band_min_nm'],.5)
    def test_scope_and_study_filters(self):
        r,w,*_=selection(self.b,{'studies':['a'],'scope':'final'})
        self.assertEqual([x['id'] for x in r],['final'])
        r,w,*_=selection(self.b,{'scope':'accepted'})
        self.assertNotIn('trial',[x['id'] for x in r])
    def test_reject_invalid_inputs(self):
        for p in ({'studies':[]},{'studies':['missing']},{'maximum':0},{'band_width':0},{'minimum':float('nan')},{'scope':'bogus'}):
            with self.assertRaises(ValueError):selection(self.b,p)


if __name__=='__main__':unittest.main()
