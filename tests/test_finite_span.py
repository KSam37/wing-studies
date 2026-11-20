import _paths  # noqa: F401  (repo root + legacy/ on sys.path)
import unittest
import numpy as np
from wingstudy import elastic
from wingstudy.finite_span import FiniteStructure


class FiniteSpanTests(unittest.TestCase):
    def make(self,n=8):
        return FiniteStructure(np.linspace(0,.28,n+1),np.full(n+1,.15),
            elastic.ElasticConfig(spanwise_bending=True,large_deflection=True,max_bend_deg=75,max_tip_deflection_fraction=.95),998.,1.)

    def test_span_length_preserved_at_large_deflection(self):
        s=self.make(); s.q[:s.n]=np.radians(np.linspace(5,70,s.n))
        p=s.centerline()
        np.testing.assert_allclose(np.linalg.norm(np.diff(p,axis=0),axis=1),s.widths,atol=1e-14)
        self.assertGreater(p[-1,2],.1)
        self.assertEqual(s.fields()[1][0],0)

    def test_point_jacobian_and_virtual_work(self):
        s=self.make(4); s.q[:4]=[.1,.2,.4,.8]; s.q[4:]=[.1,-.2,.2,.3]
        p,J,_,_=s.point(2,.4,.07)
        eps=1e-7; finite=np.zeros_like(J)
        for i in range(len(s.q)):
            delta=np.zeros_like(s.q); delta[i]=eps
            finite[:,i]=(s.point(2,.4,.07,s.q+delta)[0]-s.point(2,.4,.07,s.q-delta)[0])/(2*eps)
        np.testing.assert_allclose(J,finite,atol=1e-9)
        direction=np.arange(1,9)*.01; F=np.array([2.,-3.,5.])
        self.assertAlmostEqual(float(F@(finite@direction)),float((J.T@F)@direction),places=8)

    def test_sheet_rotation_keeps_centerline_fixed(self):
        s=self.make(); s.q[:8]=np.linspace(.1,1.,8)
        original=s.centerline(); s.q[8:]=np.linspace(.1,.9,8)
        np.testing.assert_array_equal(s.centerline(),original)

    def test_mass_and_added_inertia_positive_at_high_bend(self):
        s=self.make(); s.q[:8]=np.linspace(.1,1.,8); s.q[8:]=np.linspace(.01,.3,8)
        M,b=s.mass_and_bias()
        for a in (M,s.added_mass(),s.K):
            np.testing.assert_allclose(a,a.T,atol=1e-12)
            self.assertGreater(np.linalg.eigvalsh(a).min(),0.)
        np.testing.assert_allclose(b,0.,atol=1e-14)

    def test_small_tip_load_converges_to_linear_cantilever(self):
        errors=[]
        for n in (4,8,16):
            s=self.make(n); J,_=s.load_map(n-1)
            # Tip position Jacobian rather than last strip midpoint.
            J=s.point(n-1,1.,0.)[1]
            F=1e-5; s.q=np.linalg.solve(s.K,J.T@np.array([0,0,F]))
            exact=F*.28**3/(3*s.ei[0])
            errors.append(abs(s.centerline()[-1,2]/exact-1))
        self.assertLess(errors[-1],.002)
        self.assertLess(errors[1],errors[0]/3)
        self.assertLess(errors[2],errors[1]/3)

    def test_large_static_deflection_matches_elastica(self):
        from scipy.integrate import solve_bvp
        from scipy.optimize import root
        s=self.make(32); n=s.n; F=3.; L=s.y[-1]; ei=s.ei[0]
        def equations(y,v): return np.vstack((v[1],-F/ei*np.cos(v[0])))
        ref=solve_bvp(equations,lambda a,b:np.array([a[0],b[1]]),
                      np.linspace(0,L,100),np.zeros((2,100)),tol=1e-9)
        self.assertTrue(ref.success)
        def residual(beta):
            q=np.r_[beta,np.zeros(n)]
            J=s.point(n-1,1.,0.,q)[1]
            return s.K[:n,:n]@beta-F*J[2,:n]
        result=root(residual,ref.sol(s.y[1:])[0])
        self.assertTrue(result.success)
        s.q[:n]=result.x
        yy=np.linspace(0,L,2001)
        exact_z=np.trapezoid(np.sin(ref.sol(yy)[0]),yy)
        self.assertAlmostEqual(s.centerline()[-1,2],exact_z,delta=1e-4)
        self.assertAlmostEqual(s.q[n-1],ref.sol(L)[0],delta=1e-3)

    def test_configuration_inertia_obeys_energy_identity(self):
        s=self.make(4);s.q=np.linspace(.05,.7,8);s.v=np.linspace(-.2,.3,8)
        q=s.q.copy();eps=1e-5
        _,bias=s.mass_and_bias()
        s.q=q+eps*s.v;Mp=s.mass_and_bias()[0]
        s.q=q-eps*s.v;Mm=s.mass_and_bias()[0]
        self.assertAlmostEqual(float(s.v@bias),float(.5*s.v@((Mp-Mm)/(2*eps))@s.v),places=10)


if __name__=='__main__': unittest.main()
