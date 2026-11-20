"""Inextensible finite-rotation span segments with bending/twist springs.

The angle at the root is prescribed; every other station has elastic span slope
and sheet pitch. Centerline link angles are averages of their endpoint slopes.
Kinetic energy is assembled in the current pose, including heave/pitch coupling,
configuration-dependent inertia and imposed-flap acceleration terms. This is a
reduced rod/strip model, not a geometrically exact laminate shell.
"""
import math
import numpy as np
from . import elastic
from .spanwise_elastic import Structure


class FiniteStructure:
    def __init__(self,y,chords,cfg,rho,period):
        # Share physical-input validation and effective section stiffness definitions.
        linear=Structure(y,chords,cfg,rho,period)
        self.y,self.chords,self.cfg=linear.y,linear.chords,cfg
        self.n=n=linear.n
        self.ei,self.chord_k=linear.ei,linear.chord_k
        self.rho=rho; self.widths=np.diff(y)
        self.B=np.vstack((np.zeros(n),np.eye(n)))
        self.D=np.diff(self.B,axis=0)
        self.K=np.zeros((2*n,2*n))
        self.K[:n,:n]=self.D.T@np.diag(np.array(self.ei)/self.widths)@self.D
        self.K[n:,n:]=linear.K[2*n:,2*n:]
        self.C=2*cfg.damping_ratio/(2*math.pi/period)*self.K
        self.q=np.zeros(2*n); self.v=self.q.copy(); self.a=self.q.copy()
        self.q1=self.q.copy(); self.q2=self.q.copy()
        self._quad=[]
        xs,ws=np.polynomial.legendre.leggauss(3)
        for j,h in enumerate(self.widths):
            for s,wy in zip((xs+1)/2,ws*h/2):
                chord=(1-s)*chords[j]+s*chords[j+1]
                for u,wu in zip((xs+1)/2,ws/2):
                    self._quad.append((j,s,u*chord,wy*wu*cfg.areal_density*chord))
                if cfg.rod.mass_per_length:
                    self._quad.append((j,s,0.,wy*cfg.rod.mass_per_length))

    def centerline(self,q=None):
        q=self.q if q is None else q
        beta=self.B@q[:self.n]
        angle=(beta[:-1]+beta[1:])/2
        segments=np.column_stack((np.zeros(self.n),self.widths*np.cos(angle),self.widths*np.sin(angle)))
        return np.vstack((np.zeros(3),np.cumsum(segments,axis=0)))

    def _kinematics(self,q):
        n=self.n; beta=self.B@q[:n]; theta=self.B@q[n:]
        angle=(beta[:-1]+beta[1:])/2
        avg=(self.B[:-1]+self.B[1:])/2
        dseg=np.zeros((n,3,2*n))
        dseg[:,1,:n]=(-self.widths*np.sin(angle))[:,None]*avg
        dseg[:,2,:n]=(self.widths*np.cos(angle))[:,None]*avg
        Jnode=np.concatenate((np.zeros((1,3,2*n)),np.cumsum(dseg,axis=0)),axis=0)
        return beta,theta,self.centerline(q),Jnode,dseg

    def point(self,j,s,x,q=None,kin=None):
        """Position and analytic Jacobian of a sheet point in the prescribed wing frame."""
        q=self.q if q is None else q
        beta,theta,le,Jnode,dseg=self._kinematics(q) if kin is None else kin
        b=(1-s)*beta[j]+s*beta[j+1]; t=(1-s)*theta[j]+s*theta[j+1]
        sb,cb,st,ct=math.sin(b),math.cos(b),math.sin(t),math.cos(t)
        d=np.array([ct,sb*st,-cb*st])
        db=np.array([0.,cb*st,sb*st]); dtheta=np.array([-st,sb*ct,-cb*ct])
        S=(1-s)*self.B[j]+s*self.B[j+1]
        p=(1-s)*le[j]+s*le[j+1]+x*d
        J=Jnode[j]+s*dseg[j]
        J=J.copy(); J[:,:self.n]+=x*np.outer(db,S); J[:,self.n:]+=x*np.outer(dtheta,S)
        # Instantaneous angular velocity = beta_dot e_x + theta_dot Rx(beta)e_y.
        ang=np.zeros_like(J); ang[0,:self.n]=S
        ang[:,self.n:]=np.outer([0.,cb,sb],S)
        normal=np.array([st,-sb*ct,cb*ct])
        return p,J,ang,normal

    def mass_and_bias(self,omega=0.,alpha=0.):
        q,v=self.q,self.v; kin=self._kinematics(q)
        eps=1e-5/max(1.,float(np.linalg.norm(v)))
        kp=self._kinematics(q+eps*v); km=self._kinematics(q-eps*v)
        M=np.zeros_like(self.K); bias=np.zeros_like(q)
        om=np.array([omega,0.,0.]); al=np.array([alpha,0.,0.])
        for j,s,x,mass in self._quad:
            p,J,_,_=self.point(j,s,x,kin=kin)
            Jp=self.point(j,s,x,q+eps*v,kp)[1]
            Jm=self.point(j,s,x,q-eps*v,km)[1]
            acceleration=(Jp-Jm)@v/(2*eps)+2*np.cross(om,J@v)+np.cross(al,p)+np.cross(om,np.cross(om,p))
            M+=mass*(J.T@J)
            bias+=mass*(J.T@acceleration)
        return M,bias

    def added_mass(self):
        A=np.zeros_like(self.K); kin=self._kinematics(self.q)
        xs,ws=np.polynomial.legendre.leggauss(3)
        for j,h in enumerate(self.widths):
            for s,weight in zip((xs+1)/2,ws*h/2):
                c=(1-s)*self.chords[j]+s*self.chords[j+1]
                _,J,_,normal=self.point(j,s,c/2,kin=kin)
                H=normal@J
                S=np.r_[np.zeros(self.n),(1-s)*self.B[j]+s*self.B[j+1]]
                ma=self.cfg.added_mass_factor*math.pi*self.rho*c*c/4
                ia=self.cfg.added_mass_factor*math.pi*self.rho*c**4/128
                A+=weight*(ma*np.outer(H,H)+ia*np.outer(S,S))
        return A

    def load_map(self,j):
        _,J,ang,_=self.point(j,.5,0.)
        return J,ang

    def fields(self,q=None):
        q=self.q if q is None else q
        return self.centerline(q)[:,2],self.B@q[:self.n],self.B@q[self.n:]

    def advance(self,force,dt,omega=0.,alpha=0.):
        r=self.cfg.rho_inf
        am,af=(2*r-1)/(r+1),r/(r+1)
        g,b=.5-am+af,.25*(1-am+af)**2
        q,v,a=self.q,self.v,self.a
        M,bias=self.mass_and_bias(omega,alpha); A=self.added_mass()
        qp=q+dt*v+dt*dt*(.5-b)*a
        lag=(q-2*self.q1+self.q2)/dt**2
        pred=(qp-2*q+self.q1)/dt**2
        lhs=(1-am)*M+b*A+(1-af)*g*dt*self.C+(1-af)*b*dt**2*self.K
        rhs=(force-bias+A@lag-am*M@a-A@pred
             -self.C@((1-af)*(v+dt*(1-g)*a)+af*v)-self.K@((1-af)*qp+af*q))
        an=np.linalg.solve(lhs,rhs)
        self.q,self.v,self.a=qp+b*dt**2*an,v+dt*((1-g)*a+g*an),an
        self.q2,self.q1=self.q1,q.copy()
        if not np.isfinite(self.q).all():
            raise elastic.ElasticDivergence('Nonfinite finite-rotation state.')
        w,beta,theta=self.fields()
        if np.max(np.abs(np.degrees(beta)))>self.cfg.max_bend_deg or np.max(np.abs(w))>self.cfg.max_tip_deflection_fraction*self.y[-1]:
            raise elastic.ElasticDivergence(f'Finite-rotation span slope {np.max(np.abs(np.degrees(beta))):.2f} deg; tip deflection {w[-1]:.4f} m exceeds configured limit.')
        if np.max(np.abs(np.degrees(theta)))>self.cfg.max_twist_deg:
            raise elastic.ElasticDivergence('Sheet pitch exceeds configured limit.')
        return w,beta,theta
