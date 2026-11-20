"""Analytical structure checks and native Ptera geometry/load regression checks."""
import unittest
import numpy as np
import elastic
from spanwise_elastic import Structure, beam_element_stiffness, deformed_sections


class SpanStructureTests(unittest.TestCase):
    def make(self,n=8,rod=None):
        cfg=elastic.ElasticConfig(spanwise_bending=True,rod=rod or elastic.Rod())
        return Structure(np.linspace(0,.3,n+1),np.full(n+1,.2),cfg,998.,1.)

    def test_tip_load_matches_cantilever_exactly(self):
        for n in (1,4,16):
            s=self.make(n)
            f=np.zeros(3*n); f[2*n-2]=.01
            q=np.linalg.solve(s.K,f)
            w,beta,theta=s.fields(q)
            self.assertAlmostEqual(w[-1],.01*.3**3/(3*s.ei[0]),places=10)
            self.assertAlmostEqual(beta[-1],.01*.3**2/(2*s.ei[0]),places=10)
            self.assertEqual((w[0],beta[0],theta[0]),(0,0,0))

    def test_uniform_load_matches_cantilever(self):
        s=self.make(); f=np.zeros_like(s.q)
        xs,ws=np.polynomial.legendre.leggauss(4)
        for j,h in enumerate(np.diff(s.y)):
            for x,v in zip((xs+1)/2,ws*h/2):
                f+=v*s.interpolation(j,x)[0]
        w,_,_=s.fields(np.linalg.solve(s.K,f))
        self.assertAlmostEqual(w[-1],.3**4/(8*s.ei[0]),places=10)

    def test_positive_energy_and_heave_pitch_coupling(self):
        s=self.make()
        for matrix in (s.K,s.M,s.A):
            np.testing.assert_allclose(matrix,matrix.T,atol=1e-12)
            self.assertGreater(np.linalg.eigvalsh(matrix).min(),0)
        self.assertTrue(np.any(s.M[:16,16:]!=0))
        self.assertTrue(np.any(s.A[:16,16:]!=0))

    def test_rod_bends_but_does_not_lock_sheet(self):
        s=self.make(rod=elastic.Rod(diameter_m=.005,hollow_inner_diameter_m=.003))
        bare=self.make()
        self.assertGreater(s.ei[0],bare.ei[0]*10)
        self.assertTrue(all(k>0 for k in s.chord_k))
        # Rod's shear modulus must not stiffen sheet-pitch when rotation is fixed.
        other=self.make(rod=elastic.Rod(diameter_m=.005,hollow_inner_diameter_m=.003,shear_modulus_pa=1e18))
        np.testing.assert_allclose(s.K,other.K)
        f=np.zeros_like(s.q); f[-1]=.001
        self.assertGreater(s.fields(np.linalg.solve(s.K,f))[2][-1],0)

    def test_zero_forcing_stays_zero(self):
        s=self.make()
        for _ in range(20): s.advance(np.zeros_like(s.q),.01)
        np.testing.assert_array_equal(s.q,0)

    def test_static_equilibrium_has_no_stabilization_force(self):
        s=self.make(); f=np.zeros_like(s.q); f[14]=.001
        s.q=np.linalg.solve(s.K,f); s.q1=s.q.copy(); s.q2=s.q.copy()
        expected=s.q.copy()
        s.advance(f,.01)
        np.testing.assert_allclose(s.q,expected,atol=1e-12)

    def test_first_bending_frequency(self):
        from scipy.linalg import eigvalsh
        s=self.make(16); nb=2*s.n
        omega=np.sqrt(eigvalsh(s.K[:nb,:nb],s.M[:nb,:nb])[0])
        mu=s.cfg.areal_density*.2
        exact=1.875104068711961**2*np.sqrt(s.ei[0]/(mu*.3**4))
        self.assertLess(abs(omega/exact-1),1e-4)

    def test_invalid_geometry_and_material(self):
        for cfg in (elastic.ElasticConfig(thickness_m=0),elastic.ElasticConfig(rod=elastic.Rod(diameter_m=.002,hollow_inner_diameter_m=.003))):
            with self.assertRaises(ValueError): Structure([0,.2],[.2,.1],cfg,998,1)


class PteraGeometryTests(unittest.TestCase):
    def test_sheet_pitch_does_not_displace_leading_edge(self):
        import pterasoftware as ps
        secs=[ps.WingCrossSection(airfoil=ps.Airfoil(name='naca0012'),chord=.2,
            num_spanwise_panels=1 if i<3 else None,spanwise_spacing='uniform' if i<3 else None,
            Lp_Wcsp_Lpp=(0,.1 if i else 0,0)) for i in range(4)]
        y=np.arange(4)*.1; w=np.array([0,.001,.003,.006]); beta=np.array([0,.02,.04,.06])
        for theta in (np.zeros(4),np.array([0,.2,.3,.4])):
            wing=ps.Wing(wing_cross_sections=deformed_sections(secs,y,w,beta,theta),num_chordwise_panels=2)
            ps.Airplane(wings=[wing])
            le=np.array([wing.panels[0,0].Flpp_G_Cg]+[p.Frpp_G_Cg for p in wing.panels[0]])
            np.testing.assert_allclose(le,np.column_stack((np.zeros(4),y,w)),atol=1e-12)


class CampaignIdentityTests(unittest.TestCase):
    def test_model_and_material_changes_never_reuse_old_keys(self):
        from elastic_campaign import design_key,default_plan
        args=('t0.50',1.,[.2,.1],.3)
        legacy=design_key(*args)
        new=design_key(*args,context={'model':'span-v1','E':50e9})
        changed=design_key(*args,context={'model':'span-v1','E':100e9})
        self.assertEqual(len({legacy,new,changed}),3)
        self.assertNotIn('elastic_options',default_plan(smoke=True))
        self.assertTrue(default_plan(smoke=True,spanwise_bending=True)['elastic_options']['spanwise_bending'])


if __name__=='__main__': unittest.main()
