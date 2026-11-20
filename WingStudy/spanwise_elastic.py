"""Opt-in, reduced span bending + sheet-pitch model using Ptera's native UVLM.

SI units; straight, unswept, initially planar, isolated wings only. Root displacement,
slope and passive pitch are clamped; imposed flapping is applied by Ptera. Euler-
Bernoulli bending uses cubic Hermite elements. Sheet pitch is piecewise linear.
The sheet behind a rotation-fixed rod has an equivalent chord-bending spring; this
does NOT resolve chordwise camber or a laminate shell. See SPANWISE_ELASTICITY.md.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.spatial.transform import Rotation

import elastic

MODEL_VERSION = "span-beam-sheet-pitch-v1"
FINITE_MODEL_VERSION = "finite-span-sheet-pitch-v1"


def hermite(s, h):
    """Displacement and slope interpolation at element coordinate s in [0,1]."""
    return (np.array([1-3*s*s+2*s**3, h*(s-2*s*s+s**3), 3*s*s-2*s**3, h*(-s*s+s**3)]),
            np.array([(-6*s+6*s*s)/h, 1-4*s+3*s*s, (6*s-6*s*s)/h, -2*s+3*s*s]))


def beam_element_stiffness(ei, h):
    return ei/h**3 * np.array([[12,6*h,-12,6*h], [6*h,4*h*h,-6*h,2*h*h],
                               [-12,-6*h,12,-6*h], [6*h,2*h*h,-6*h,4*h*h]])


class Structure:
    """Coupled mass and added-mass matrices; clamped DOFs eliminated exactly."""
    def __init__(self, y, chords, cfg, rho, period):
        self.y, self.chords, self.cfg = np.asarray(y), np.asarray(chords), cfg
        self.n = n = len(y)-1
        h = np.diff(y)
        if n < 1 or np.any(h <= 0) or np.any(np.asarray(chords) <= 0):
            raise ValueError("Need increasing span stations and positive active chords.")
        values = [cfg.thickness_m, cfg.material.youngs_modulus_pa, cfg.material.shear_modulus_pa,
                  cfg.material.density_kg_m3, cfg.rod.youngs_modulus_pa, rho, period]
        if not all(np.isfinite(v) and v > 0 for v in values):
            raise ValueError("Thickness, moduli, densities, fluid density and period must be positive and finite.")
        if not (0 <= cfg.rod.hollow_inner_diameter_m <= cfg.rod.diameter_m) or not np.isfinite(cfg.rod.diameter_m):
            raise ValueError("Rod diameters must satisfy 0 <= inner <= outer.")
        if cfg.rod.diameter_m and cfg.rod.hollow_inner_diameter_m == cfg.rod.diameter_m:
            raise ValueError("A fitted rod needs a nonzero wall thickness.")
        if cfg.stiffness_model != "plate":
            raise ValueError("Span bending requires the plate stiffness model.")
        if not (0 <= cfg.rho_inf <= 1 and cfg.added_mass_factor >= 0 and cfg.damping_ratio >= 0):
            raise ValueError("Invalid damping or added-mass settings.")
        # Full indexing: [w0,beta0,w1,beta1,...,wn,betan,theta0,...,thetan].
        self.pitch0 = 2*(n+1)
        self.keep = np.r_[np.arange(2,self.pitch0), np.arange(self.pitch0+1,3*(n+1))]
        size = 3*(n+1)
        K, M, A = (np.zeros((size,size)) for _ in range(3))
        base = np.zeros(size)
        self.ei, self.chord_k = [], []
        rod = cfg.rod
        fixed_rod = rod.diameter_m > 0 and rod.fixed_rotation
        for j, length in enumerate(h):
            c = (chords[j]+chords[j+1])/2
            ei = cfg.material.youngs_modulus_pa*c*cfg.thickness_m**3/12 + rod.youngs_modulus_pa*rod.polar_moment_m4/2
            self.ei.append(ei)
            bi = np.arange(2*j,2*j+4)
            K[np.ix_(bi,bi)] += beam_element_stiffness(ei,length)
            ti = np.array([self.pitch0+j,self.pitch0+j+1])
            gj = cfg.material.shear_modulus_pa*c*cfg.thickness_m**3/3
            if not fixed_rod:
                gj += rod.shear_modulus_pa*rod.polar_moment_m4
            K[np.ix_(ti,ti)] += gj/length*np.array([[1,-1],[-1,1]])
            # Equivalent rotational stiffness matching cantilever tip-load compliance:
            # k = 3 E I_chord/c; I_chord = dy*t^3/12. Rotation is sheet-only.
            kc = cfg.material.youngs_modulus_pa*cfg.thickness_m**3/(4*c) if fixed_rod else 0.
            self.chord_k.append(kc*length)
            nodes, weights = np.polynomial.legendre.leggauss(4)
            for xi, wi in zip((nodes+1)/2, weights*length/2):
                H, _ = hermite(xi,length)
                S = np.array([1-xi,xi])
                b, t = np.zeros(size), np.zeros(size)
                b[bi], t[ti] = H, S
                # z(x,y)=w(y)-x*theta(y). Include heave/pitch coupling in inertia.
                mu = cfg.areal_density*c
                M += wi*( (mu+rod.mass_per_length)*np.outer(b,b)
                          - mu*c/2*(np.outer(b,t)+np.outer(t,b))
                          + mu*c*c/3*np.outer(t,t))
                ma = cfg.added_mass_factor*math.pi*rho*c*c/4
                ia = cfg.added_mass_factor*math.pi*rho*c**4/128
                A += wi*(ma*np.outer(b-c/2*t,b-c/2*t)+ia*np.outer(t,t))
                K += wi*kc*np.outer(t,t)
                pos = y[j]+xi*length
                base += wi*pos*((mu+rod.mass_per_length)*b-mu*c/2*t)
        self.K, self.M, self.A = (a[np.ix_(self.keep,self.keep)] for a in (K,M,A))
        self.base = base[self.keep]
        self.C = 2*cfg.damping_ratio/(2*math.pi/period)*self.K
        self.q = np.zeros(3*n); self.v = self.q.copy(); self.a = self.q.copy()
        self.q1 = self.q.copy(); self.q2 = self.q.copy()

    def interpolation(self, j, s=0.5):
        size = 3*(self.n+1)
        b, slope, pitch = np.zeros(size), np.zeros(size), np.zeros(size)
        b[2*j:2*j+4], slope[2*j:2*j+4] = hermite(s,self.y[j+1]-self.y[j])
        pitch[self.pitch0+j:self.pitch0+j+2] = [1-s,s]
        return b[self.keep], slope[self.keep], pitch[self.keep]

    def fields(self, q=None):
        full = np.zeros(3*(self.n+1)); full[self.keep] = self.q if q is None else q
        return full[:self.pitch0:2], full[1:self.pitch0:2], full[self.pitch0:]

    def advance(self, force, dt):
        r = self.cfg.rho_inf
        am, af = (2*r-1)/(r+1), r/(r+1)
        g, b = .5-am+af, .25*(1-am+af)**2
        q,v,a = self.q,self.v,self.a
        qp = q+dt*v+dt*dt*(.5-b)*a
        d2_lagged = (q-2*self.q1+self.q2)/dt**2
        d2_pred = (qp-2*q+self.q1)/dt**2
        lhs = (1-am)*self.M+b*self.A+(1-af)*g*dt*self.C+(1-af)*b*dt**2*self.K
        rhs = (force+self.A@d2_lagged-am*self.M@a-self.A@d2_pred
               -self.C@((1-af)*(v+dt*(1-g)*a)+af*v)-self.K@((1-af)*qp+af*q))
        an = np.linalg.solve(lhs,rhs)
        self.q, self.v, self.a = qp+b*dt**2*an, v+dt*((1-g)*a+g*an), an
        self.q2, self.q1 = self.q1, q.copy()
        if not np.isfinite(self.q).all():
            raise elastic.ElasticDivergence("Nonfinite span bending state.")
        w,beta,theta = self.fields()
        if np.max(np.abs(np.degrees(beta))) > self.cfg.max_bend_deg or np.max(np.abs(w)) > self.cfg.max_tip_deflection_fraction*self.y[-1]:
            raise elastic.ElasticDivergence(f"Span slope {np.max(np.abs(np.degrees(beta))):.2f} deg, displacement {np.max(np.abs(w)):.4f} m exceed the reduced beam validity limit; reduce dt to check coupling, or use a nonlinear structural model.")
        if np.max(np.abs(np.degrees(theta))) > self.cfg.max_twist_deg:
            raise elastic.ElasticDivergence("Sheet pitch exceeds the configured angle limit.")
        return w,beta,theta


def deformed_sections(base_sections, y, w, beta, theta):
    """Rebuild native section frames; sheet pitch never rotates the leading-edge line."""
    import pterasoftware as ps
    sections = []
    prev_p, prev_R = np.zeros(3), np.eye(3)
    for i, sec in enumerate(base_sections):
        point = np.array([0.,y[i],w[i]])
        rot = Rotation.from_euler("XYZ", [beta[i],theta[i],0.]).as_matrix()
        relative = Rotation.from_matrix(prev_R.T@rot).as_euler("XYZ",degrees=True)
        offset = prev_R.T@(point-prev_p)
        sections.append(ps.WingCrossSection(airfoil=sec.airfoil, chord=sec.chord,
            num_spanwise_panels=sec.num_spanwise_panels, spanwise_spacing=sec.spanwise_spacing,
            Lp_Wcsp_Lpp=offset, angles_Wcsp_to_Wcs_ixyz=relative))
        prev_p,prev_R = point,rot
    return sections


_CLASS = None


def problem_class():
    global _CLASS
    if _CLASS is not None:
        return _CLASS
    import pterasoftware as ps

    class SpanwiseProblem(elastic.problem_class()):
        def __init__(self, movement, config, rho_water, flap_period_s):
            super().__init__(movement,config,rho_water,flap_period_s)
            wings = movement.airplane_movements[0].wing_movements
            if len(wings) != 1 or wings[0].base_wing.symmetric or wings[0].base_wing.mirror_only:
                raise ValueError("Span model supports one isolated right wing.")
            self.wm = wings[0]
            self.sections = self.wm.base_wing.wing_cross_sections
            if any(not np.allclose(s.angles_Wcsp_to_Wcs_ixyz,0) or not np.allclose(s.Lp_Wcsp_Lpp[[0,2]],0) for s in self.sections):
                raise ValueError("Span model requires straight leading edge and planar sections.")
            y = np.cumsum([s.Lp_Wcsp_Lpp[1] for s in self.sections])
            cls = Structure
            if config.large_deflection:
                from finite_span import FiniteStructure
                cls = FiniteStructure
                if not np.allclose(self.wm.base_wing.angles_Gs_to_Wn_ixyz[1:],0):
                    raise ValueError("Finite-rotation mode currently supports zero prescribed incidence and sweep.")
            self.structure = cls(y,[s.chord for s in self.sections],config,rho_water,flap_period_s)
            pitch_start = self.structure.n if config.large_deflection else 2*self.structure.n
            if config.warping_stiffness:
                # Same pitch-gradient regularization as v1.5, in absolute pitch DOFs.
                self.structure.K[pitch_start:,pitch_start:] += self._warping_matrix(self.wm.base_wing,np.diff(y))
                self.structure.C = 2*config.damping_ratio/(2*math.pi/flap_period_s)*self.structure.K
            self.span_history = []

        def initialize_next_problem(self, solver, step):
            if step >= self.num_steps-1:
                return
            st, cfg = self.structure, self.elastic_config
            next_step = len(self._steady_problems)
            dt, t = self.movement.delta_time, next_step*self.movement.delta_time
            wing = self._steady_problems[-1].airplanes[0].wings[0]
            rot = Rotation.from_euler("XYZ",wing.angles_Gs_to_Wn_ixyz,degrees=True).as_matrix()
            force = np.zeros_like(st.q)
            if next_step > cfg.step_discards:
                # Use force plus transported strip couple, not one root moment for all joints.
                for j in range(st.n):
                    panels = [wing.panels[i,j] for i in range(wing.num_chordwise_panels)]
                    F = sum((np.asarray(p.forces_GP1) for p in panels),np.zeros(3))
                    mid = (panels[0].Flpp_GP1_CgP1+panels[0].Frpp_GP1_CgP1)/2
                    moment = sum((np.asarray(p.moments_GP1_CgP1)-np.cross(mid,p.forces_GP1) for p in panels),np.zeros(3))
                    F, moment = rot.T@F, rot.T@moment
                    if cfg.large_deflection:
                        J,B = st.load_map(j)
                        force += J.T@F+B.T@moment
                    else:
                        H,D,S = st.interpolation(j)
                        force += H*F[2]+D*moment[0]+S*moment[1]
                if not cfg.large_deflection:
                    force -= st.base*self._flap_accel(self.wm,t)
                tr = t-cfg.step_discards*dt
                rt = cfg.ramp_cycles*self._flap_period
                ramp = 1. if rt <= 0 or tr >= rt else .5*(1-math.cos(math.pi*tr/rt))
                if cfg.large_deflection:
                    period = self._flap_period
                    amp = math.radians(self.wm.ampAngles_Gs_to_Wn_ixyz[0])
                    phase = math.radians(self.wm.phaseAngles_Gs_to_Wn_ixyz[0])
                    spacing = self.wm.spacingAngles_Gs_to_Wn_ixyz[0]
                    wave = math.sin if spacing == 'sine' else spacing
                    h = period*1e-5
                    omega = amp*(wave(2*math.pi*(t+h)/period+phase)-wave(2*math.pi*(t-h)/period+phase))/(2*h)
                    st.advance(ramp*force,dt,omega=omega,alpha=self._flap_accel(self.wm,t))
                else:
                    st.advance(ramp*force,dt)
            w,beta,theta = st.fields()
            self.elastic_history.append((t,np.degrees(theta[1:]).copy(),force[-st.n:].copy()))
            self.span_history.append((t,w.copy(),np.degrees(beta).copy()))
            # Preserve native diagnostics' relative-pitch convention.
            relative = np.r_[0.,np.diff(theta)]
            velocity = np.r_[0.,st.v[-st.n:]]
            self._record_structural_state(next_step,relative,np.r_[0.,np.diff(velocity)],0)
            prescribed = self.wm.generate_wing_at_time_step(next_step,dt)
            y_def = st.centerline()[:,1] if cfg.large_deflection else st.y
            deformed = ps.Wing(wing_cross_sections=deformed_sections(self.sections,y_def,w,beta,theta),
                name=prescribed.name,Ler_Gs_Cgs=prescribed.Ler_Gs_Cgs,
                angles_Gs_to_Wn_ixyz=prescribed.angles_Gs_to_Wn_ixyz,
                symmetric=False,num_chordwise_panels=prescribed.num_chordwise_panels,
                chordwise_spacing=prescribed.chordwise_spacing)
            airplane = ps.Airplane(wings=[deformed],name="Water Wing",weight=0.)
            self._steady_problems.append(ps.SteadyProblem(airplanes=[airplane],
                operating_point=self._aeroelastic_movement.operating_points[next_step]))

    _CLASS = SpanwiseProblem
    return _CLASS
