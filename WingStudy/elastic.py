"""Stabilized torsional aeroelasticity for thin wings in water, on stock Ptera.

Why this exists
---------------
Ptera's native ``AeroelasticUnsteadyProblem`` advances each spanwise strip with an
explicit (loosely coupled) update: the UVLM moment from step n drives the strip
spring over step n -> n+1. For a 0.25-0.5 mm carbon plate in water the fluid
added inertia of a pitching strip is roughly 20-100x the strip's own inertia.
Loosely coupled partitioned FSI is unconditionally unstable at that mass ratio
(Causin, Gerbeau & Nobile 2005), independent of time step: the twist grows
step-to-step until Ptera rejects an angle beyond -90 deg. Large damping hides this,
but then the damper, not the stiffness, sets the response.

What this module changes (Ptera's native code is untouched)
-----------------------------------------------------------
``StabilizedAeroelasticProblem`` subclasses ``AeroelasticUnsteadyProblem`` and
replaces only the per-step structural update (``_calculate_spring_moments``):

1. Added-mass partitioning: an analytic 2-D flat-plate estimate of each strip's
   added pitch inertia is moved to the structural left-hand side, and the same
   estimate times the previous structural acceleration is added back to the
   force side. When the estimate is not much smaller than the real added
   inertia the explicit coupling is contractive. The correction cancels at
   convergence, so physics is unchanged to O(dt).
2. Generalized-alpha implicit integration of the whole strip chain (one small
   linear solve per step) instead of per-strip ``solve_ivp``: unconditionally
   stable for the structure, second-order accurate, with controllable
   high-frequency numerical dissipation (``rho_inf``), and much faster.
3. Moments are projected on each strip's actual leading-edge axis (which rolls
   with the flap), not on the fixed geometry y-axis.
4. Two stiffness models:
   * ``uniform``: Ptera's model. One spring constant k for every strip, driven
     by that strip's own moment only. Kept for comparison with native runs.
   * ``plate``: beam-consistent St. Venant torsion of the actual plate. Strip j
     gets k_j = (G c_j t^3 / 3 + G_rod J_rod) / dy_j from its own chord, and the
     twist between stations is driven by all moment outboard of it
     (generalized force L^T M). Stiffness follows the shape, so wings cut from
     the same sheet are compared fairly.
5. Inertial forcing uses the strip's heave acceleration times its chordwise
   center-of-mass offset (m r phi_ddot x_cg); Ptera's native form multiplies a
   flapping-axis inertia by the flap acceleration. In water both are small.

Limitations that remain (model, not numerics)
---------------------------------------------
* Only twist about the leading edge is modeled. Spanwise bending and chordwise
  camber of the plate are not. This is most faithful for a stiff leading-edge
  spar with a compliant plate, and least faithful for a bare plate, whose shear
  center is near mid-chord and which also bends spanwise.
* UVLM is attached-flow and inviscid. Large effective angles of attack
  (leading-edge vortex, separation) are not captured.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np


class ElasticDivergence(RuntimeError):
    """Raised when the twist exceeds the configured safety limit."""


@dataclass
class Material:
    """Thin laminate properties. Defaults: woven 0/90 carbon/epoxy sheet.

    Torsion of a 0/90 woven plate is governed by in-plane shear modulus G12,
    which is low (~3.5-5 GPa). A +/-45 or quasi-isotropic layup is ~4x stiffer
    in torsion (G ~ 15-20 GPa). Measure G for your actual sheet when possible.
    """
    name: str = "woven_cf_0_90"
    shear_modulus_pa: float = 4.5e9
    density_kg_m3: float = 1550.0
    youngs_modulus_pa: float = 50e9   # plain-weave bending modulus; sets warping stiffness


@dataclass
class Rod:
    """Optional leading-edge spar contributing torsional stiffness and mass."""
    diameter_m: float = 0.0
    shear_modulus_pa: float = 4.5e9
    density_kg_m3: float = 1550.0
    hollow_inner_diameter_m: float = 0.0
    youngs_modulus_pa: float = 120e9  # longitudinal bending; editable laminate assumption
    fixed_rotation: bool = True     # used by the span-bending model, not legacy torsion

    @property
    def polar_moment_m4(self) -> float:
        return math.pi * (self.diameter_m**4 - self.hollow_inner_diameter_m**4) / 32

    @property
    def mass_per_length(self) -> float:
        return self.density_kg_m3 * math.pi * (self.diameter_m**2 - self.hollow_inner_diameter_m**2) / 4


@dataclass
class ElasticConfig:
    """Everything that defines the structural model and its numerics.

    Physical parameters: stiffness_model, thickness_m, material, rod, uniform_k,
    damping_ratio. Numerical parameters (results should not depend on them; the
    validation script checks this): added_mass_factor, rho_inf, step_discards,
    ramp_cycles, max_twist_deg.
    """
    stiffness_model: str = "plate"          # "plate" or "uniform"
    thickness_m: float = 0.5e-3
    material: Material = field(default_factory=Material)
    rod: Rod = field(default_factory=Rod)
    uniform_k_nm_per_rad: float = 1.0       # only for stiffness_model="uniform"
    uniform_c_nms_per_rad: float = 0.0      # only for stiffness_model="uniform"
    damping_ratio: float = 0.02             # structural, stiffness-proportional, at flap freq.
    warping_stiffness: bool = True          # plate bending resistance to non-uniform twist (Vlasov E*Gamma)
    added_mass_factor: float = 0.5          # x 2-D flat-plate estimate; stable band ~0.35-0.7 (validated)
    rho_inf: float = 0.6                    # generalized-alpha high-frequency damping (1 = none)
    step_discards: int = 5
    ramp_cycles: float = 0.25
    max_twist_deg: float = 80.0
    spanwise_bending: bool = False  # opt in; existing atlas results retain their model
    large_deflection: bool = False  # finite-rotation, length-preserving span segments
    max_bend_deg: float = 20.0      # reduced linear beam validity guard
    max_tip_deflection_fraction: float = 0.25

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ElasticConfig":
        d = dict(d)
        d["material"] = Material(**d.get("material", {}))
        d["rod"] = Rod(**d.get("rod", {}))
        return cls(**d)

    @property
    def areal_density(self) -> float:
        return self.material.density_kg_m3 * self.thickness_m


def _problem_base():
    import pterasoftware as ps
    return ps.AeroelasticUnsteadyProblem


def _make_problem_class():
    Base = _problem_base()

    class StabilizedAeroelasticProblem(Base):
        """Ptera aeroelastic problem with a stabilized, implicit structural update."""

        def __init__(self, movement, config: ElasticConfig, rho_water: float,
                     flap_period_s: float):
            # Ptera's own spring values are unused; its step_discards hold logic is reused.
            super().__init__(movement=movement, wing_density=max(config.areal_density, 1e-9),
                             spring_constant_rad=1.0, damping_constant_rad=0.0,
                             step_discards=config.step_discards)
            self.elastic_config = config
            self._rho_water = rho_water
            self._flap_period = flap_period_s
            self._matrices = None
            self._q = self._v = self._a = None
            self.elastic_history = []      # per structural step: time, absolute twist (deg), generalized force

        # ---- structural matrices, built once from the undeformed wing --------------
        def _build(self, wing, n):
            cfg = self.elastic_config
            secs = wing.wing_cross_sections
            chords = np.array([(secs[j].chord + secs[j + 1].chord) / 2 for j in range(n)])
            widths = np.array([float(np.linalg.norm(wing.panels[0][j].frontLeg_G)) for j in range(n)])
            radii = np.cumsum(widths) - widths / 2
            area = chords * widths
            mass = cfg.areal_density * area + cfg.rod.mass_per_length * widths
            # Strip pitch inertia about its leading edge (uniform plate: m c^2 / 3).
            inertia_s = cfg.areal_density * area * chords**2 / 3 + 1e-12
            # 2-D thin plate pitching about its leading edge: pi rho b^4 (1/8 + a^2), a = -1.
            inertia_a = cfg.added_mass_factor * (9 * math.pi / 128) * self._rho_water * chords**4 * widths
            lower = np.tril(np.ones((n, n)))       # absolute twist = lower @ relative twist
            omega = 2 * math.pi / self._flap_period
            if cfg.stiffness_model == "plate":
                gj = cfg.material.shear_modulus_pa * chords * cfg.thickness_m**3 / 3 \
                    + cfg.rod.shear_modulus_pa * cfg.rod.polar_moment_m4
                k = np.diag(gj / widths)
                if cfg.warping_stiffness:
                    k = k + lower.T @ self._warping_matrix(wing, widths) @ lower
                proj = lower.T                     # outboard moments load each station
                mass_m = lower.T @ np.diag(inertia_s) @ lower
                damp = (2 * cfg.damping_ratio / omega) * k
            elif cfg.stiffness_model == "uniform":
                k = cfg.uniform_k_nm_per_rad * np.eye(n)
                proj = np.eye(n)                   # Ptera: strip's own moment only
                mass_m = np.diag(inertia_s)
                damp = cfg.uniform_c_nms_per_rad * np.eye(n) + (2 * cfg.damping_ratio / omega) * k
            else:
                raise ValueError(f"Unknown stiffness_model {cfg.stiffness_model!r}")
            added = proj @ np.diag(inertia_a) @ lower
            r = cfg.rho_inf
            am, af = (2 * r - 1) / (r + 1), r / (r + 1)
            gamma = 0.5 - am + af
            beta = 0.25 * (1 - am + af) ** 2
            dt = self.movement.delta_time
            # The added-mass estimate acts on the backward second difference of the
            # twist, D2 q_{n+1} = (q_{n+1} - 2 q_n + q_{n-1}) / dt^2, the same discrete
            # operator through which the UVLM (finite-differenced panel motion and
            # circulation) reports the fluid's inertial reaction one step later.
            # q_{n+1} is linear in a_{n+1} with coefficient beta dt^2, hence beta here.
            lhs = (1 - am) * mass_m + beta * added + (1 - af) * gamma * dt * damp + (1 - af) * beta * dt * dt * k
            self._matrices = dict(n=n, chords=chords, widths=widths, radii=radii, mass=mass,
                                  K=k, C=damp, M=mass_m, A=added, P=proj, L=lower,
                                  lhs_inv=np.linalg.inv(lhs), am=am, af=af, gamma=gamma, beta=beta,
                                  k_strip=np.diag(k).copy(), inertia_a=inertia_a, inertia_s=inertia_s)
            self._q = np.zeros(n); self._v = np.zeros(n); self._a = np.zeros(n)
            self._q_hist = [np.zeros(n), np.zeros(n)]   # q_{n-1}, q_{n-2}

        def _warping_matrix(self, wing, widths):
            """Vlasov warping stiffness on absolute station twist phi_1..phi_N.

            Strain energy 1/2 * E * Gamma * (phi'')^2 integrated along the span, with
            Gamma = c^3 t^3 / 144 for a thin flat strip. A continuous plate resists
            neighbouring strips twisting in opposite directions through this term; plain
            St. Venant torsion (G J) alone leaves that zigzag mode almost free, which is
            what destabilizes wide-chord wings. Root clamped (phi = phi' = 0), tip free.
            """
            cfg = self.elastic_config
            n = len(widths)
            secs = wing.wing_cross_sections
            ei = cfg.material.youngs_modulus_pa * np.array([secs[i].chord ** 3 for i in range(n + 1)]) \
                * cfg.thickness_m ** 3 / 144
            h = np.asarray(widths)                    # h[i-1] spans station i-1 -> i
            rows, weights = [], []
            # Root node: clamped, ghost phi_{-1} = phi_1  ->  phi'' = 2 phi_1 / h1^2.
            r = np.zeros(n); r[0] = 2 / h[0] ** 2
            rows.append(r); weights.append(ei[0] * h[0] / 2)
            for i in range(1, n):                     # interior stations 1..n-1
                hl, hr = h[i - 1], h[i]
                r = np.zeros(n)
                c = 2 / (hl + hr)
                r[i - 1] += -c * (1 / hr + 1 / hl)     # phi_i   (column i-1 holds phi_i)
                r[i] += c / hr                         # phi_{i+1}
                if i - 2 >= 0:
                    r[i - 2] += c / hl                 # phi_{i-1}
                rows.append(r); weights.append(ei[i] * (hl + hr) / 2)
            d = np.array(rows)
            return d.T @ np.diag(weights) @ d

        def _flap_accel(self, wing_movement, t):
            amp = math.radians(wing_movement.ampAngles_Gs_to_Wn_ixyz[0])
            if amp == 0:
                return 0.0
            period = wing_movement.periodAngles_Gs_to_Wn_ixyz[0]
            phase = math.radians(wing_movement.phaseAngles_Gs_to_Wn_ixyz[0])
            spacing = wing_movement.spacingAngles_Gs_to_Wn_ixyz[0]
            f = (lambda x: math.sin(x)) if spacing == "sine" else spacing
            b = 2 * math.pi / period
            h = period * 1e-4
            ang = lambda s: amp * f(b * s + phase)
            return (ang(t + h) - 2 * ang(t) + ang(t - h)) / (h * h)

        # ---- the only override of Ptera's structural step ----------------------------
        def _calculate_spring_moments(self, num_spanwise_panels, wing, mass_matrix,
                                      aeroMoments_GP1_Slep, step, wing_idx, wing_movement):
            n = num_spanwise_panels
            if self._matrices is None:
                self._build(wing, n)
            m = self._matrices
            cfg = self.elastic_config
            dt = self.movement.delta_time
            t_new = step * dt
            out_q = np.zeros(n + 1); out_v = np.zeros(n + 1)
            if step <= cfg.step_discards:
                return out_q, out_v
            # Moment of each strip about its own leading-edge axis (rolls with the flap).
            axes = []
            for j in range(n):
                p = wing.panels[0][j]
                e = np.asarray(p.Frpp_GP1_CgP1) - np.asarray(p.Flpp_GP1_CgP1)
                axes.append(e / np.linalg.norm(e))
            axes = np.array(axes)
            strip_moment = np.einsum("cjk,jk->j", aeroMoments_GP1_Slep, axes)
            t_eval = t_new - m["af"] * dt
            phi_dd = self._flap_accel(wing_movement, t_eval)
            inertial = m["mass"] * m["radii"] * phi_dd * (m["chords"] / 2)
            t_rel = t_new - cfg.step_discards * dt
            ramp_t = cfg.ramp_cycles * self._flap_period
            ramp = 1.0 if ramp_t <= 0 or t_rel >= ramp_t else 0.5 * (1 - math.cos(math.pi * t_rel / ramp_t))
            q, v, a = self._q, self._v, self._a
            q1, q2 = self._q_hist
            am, af, g, b = m["am"], m["af"], m["gamma"], m["beta"]
            # Lagged added-mass reaction the UVLM moment already contains (cancelled here)
            # and the predictor part of the implicit one (moved to the left-hand side).
            d2_lagged = (q - 2 * q1 + q2) / (dt * dt)
            q_pred = q + dt * v + dt * dt * (0.5 - b) * a
            d2_pred = (q_pred - 2 * q + q1) / (dt * dt)
            force = ramp * (m["P"] @ (strip_moment + inertial)) + m["A"] @ d2_lagged
            rhs = (force - am * m["M"] @ a - m["A"] @ d2_pred
                   - m["C"] @ ((1 - af) * (v + dt * (1 - g) * a) + af * v)
                   - m["K"] @ ((1 - af) * q_pred + af * q))
            a_new = m["lhs_inv"] @ rhs
            q_new = q + dt * v + dt * dt * ((0.5 - b) * a + b * a_new)
            v_new = v + dt * ((1 - g) * a + g * a_new)
            if not np.all(np.isfinite(q_new)):
                raise ElasticDivergence(f"Non-finite twist at step {step}.")
            absolute = np.degrees(m["L"] @ q_new)
            if np.max(np.abs(absolute)) > cfg.max_twist_deg:
                raise ElasticDivergence(
                    f"Twist {np.max(np.abs(absolute)):.1f} deg exceeds {cfg.max_twist_deg} deg at step {step} "
                    f"(t={t_new:.3f} s). The wing is too soft for a small-deformation torsion model, "
                    f"or the coupling is unstable; see validation notes.")
            self._q_hist = [q, q1]
            self._q, self._v, self._a = q_new, v_new, a_new
            self.elastic_history.append((t_new, absolute.copy(), strip_moment.copy()))
            out_q[1:] = q_new; out_v[1:] = v_new
            return out_q, out_v

    return StabilizedAeroelasticProblem


_CLASS = None


def problem_class():
    global _CLASS
    if _CLASS is None:
        _CLASS = _make_problem_class()
    return _CLASS


def strip_summary(problem) -> dict:
    """Per-strip stiffness and inertia ratios, useful to judge stability margin."""
    m = problem._matrices
    if m is None:
        return {}
    return {"chord_m": m["chords"].tolist(), "width_m": m["widths"].tolist(),
            "k_strip_nm_per_rad": m["k_strip"].tolist(),
            "added_to_structural_inertia": (m["inertia_a"] / m["inertia_s"]).tolist()}
