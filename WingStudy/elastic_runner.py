"""Headless runner: one wing + one elastic configuration -> metrics.

Reuses model.py geometry, waveform and metric definitions so rigid and elastic
numbers are directly comparable to the catalog. No plots or animations are
written; that keeps a case at solver cost, which matters for overnight batches.
"""
from __future__ import annotations

import contextlib
import copy
import json
import math
import sqlite3
import time
import warnings
from pathlib import Path

import numpy as np

import elastic
import model

ROOT = Path(__file__).resolve().parent.parent
CATALOGS = [ROOT / "outputs" / "master_runs.sqlite3", ROOT / "outputs" / "master_runs_old.sqlite3"]
TEMPLATE_CASES = Path(__file__).resolve().parent / "template_cases"


def load_catalog_case(case_no: int):
    """Return (case, settings) exactly as recorded for a global case number."""
    for db in CATALOGS:
        if not db.exists():
            continue
        row = sqlite3.connect(db).execute("select payload from cases where case_no=?", (case_no,)).fetchone()
        if row:
            payload = json.loads(row[0])
            return payload["case"], payload["settings"]
    # The legacy catalogs stay local; the template cases the elastic studies need ship with the repo.
    frozen = TEMPLATE_CASES / f"case_{int(case_no)}.json"
    if frozen.exists():
        payload = json.loads(frozen.read_text(encoding="utf-8"))["payload"]
        return payload["case"], payload["settings"]
    raise KeyError(f"Case {case_no} not found in {', '.join(str(c) for c in CATALOGS)} or {TEMPLATE_CASES}")


def sections_case(template_case, settings, chords_m, span_m, name="Elastic wing"):
    """New straight-LE wing with equally spaced stations, sharing the template motion."""
    case = copy.deepcopy(template_case)
    ys = np.linspace(0.0, span_m, len(chords_m))
    base = template_case["sections"][0]
    case["sections"] = [dict(base, chord_m=float(c), y_m=float(y), x_m=0.0) for c, y in zip(chords_m, ys)]
    case["design_name"] = name
    case.pop("adaptive_trial", None)
    case.pop("geometry_id", None)
    return case


def rectangle_7835(settings):
    """Reconstruction of case 7835, which is not in this repository's catalogs.

    A 0.200 m chord rectangle whose span reproduces the recorded rigid results
    at dt = 0.02 s (peak root torque 0.999 N m, mean thrust 0.78 N, RMS lift 6.34 N).
    """
    template, s = load_catalog_case(7657)
    return sections_case(template, s, [0.2] * 8, 0.1872, name="Rectangle (7835 reconstruction)"), s


def build_solver(case, settings, config: elastic.ElasticConfig | None):
    """Rigid stock solver when config is None, otherwise the stabilized elastic one."""
    import pterasoftware as ps
    if config is None:
        rigid = dict(settings, aeroelastic_enabled=False)
        return model.build_solver(case, rigid), None
    if config.large_deflection and not config.spanwise_bending:
        raise ValueError("Enable spanwise_bending when requesting finite rotations.")
    if "sections" in case:
        sections, angles = model.custom_sections(case, settings, ps)
    else:
        sections, angles = model.sweep_sections(case, settings, ps)
    wing = ps.Wing(wing_cross_sections=sections, name="Study Wing", Ler_Gs_Cgs=(0., 0., 0.),
                   angles_Gs_to_Wn_ixyz=angles, symmetric=False, explode_into_strips=True,
                   num_chordwise_panels=settings["chord_panels"], chordwise_spacing="cosine")
    airplane = ps.Airplane(wings=[wing], name="Water Wing", weight=0.)
    spec = settings.get("waveform", {"mode": "sine"})
    custom = spec["mode"] == "custom"
    kwargs = {"spacingAnglesSecondDerivative_Gs_to_Wn_ixyz": (model.FlapAcceleration(spec), None, None)} if custom else {}
    wm = ps.AeroelasticWingMovement(
        base_wing=airplane.wings[0],
        wing_cross_section_movements=[ps.AeroelasticWingCrossSectionMovement(base_wing_cross_section=c)
                                      for c in airplane.wings[0].wing_cross_sections],
        ampAngles_Gs_to_Wn_ixyz=(case["amplitude_deg"], 0., 0.),
        periodAngles_Gs_to_Wn_ixyz=(1 / case["frequency_hz"], 0., 0.),
        spacingAngles_Gs_to_Wn_ixyz=(model.FlapWave(spec) if custom else "sine", "sine", "sine"), **kwargs)
    rows = math.ceil(settings["wake_cycles"] / case["frequency_hz"] / settings["dt_s"]) if settings.get("wake_cycles", 0) else None
    movement = ps.AeroelasticMovement(
        airplane_movements=[ps.AeroelasticAirplaneMovement(base_airplane=airplane, wing_movements=[wm])],
        operating_point_movement=ps.OperatingPointMovement(base_operating_point=ps.OperatingPoint(
            rho=settings["rho"], nu=settings["nu"], vCg__E=case["speed_mps"], alpha=0., beta=0.)),
        delta_time=settings["dt_s"],
        num_steps=math.ceil(settings["cycles"] / case["frequency_hz"] / settings["dt_s"]),
        max_wake_rows=rows)
    if config.spanwise_bending:
        import spanwise_elastic
        cls = spanwise_elastic.problem_class()
    else:
        cls = elastic.problem_class()
    problem = cls(movement, config, settings["rho"], 1 / case["frequency_hz"])
    return ps.AeroelasticUnsteadyRingVortexLatticeMethodSolver(aeroelastic_unsteady_problem=problem), problem


FACTOR_LADDER = (0.5, 0.4, 0.6, 0.35, 0.7)


STATUS_RANK = {"verified": 3, "uncertain": 2, "unverified": 1, "unresolved": 0}


def run_verified(case, settings, config: elastic.ElasticConfig | None, overrides: dict | None = None,
                 ladder=FACTOR_LADDER, tolerance=0.03, dt_refinements=(1,)) -> dict:
    """As _run_verified_at_dt, retrying at dt / r for each r in dt_refinements until verified.

    Soft plates (large twist) need a smaller time step for the explicit aerodynamic
    coupling; stiff plates verify at the base dt and never pay for the retries. If no
    retry verifies, the best result found is returned (uncertain beats unverified beats
    unresolved; ties keep the larger, earlier time step).
    """
    if config is None:
        return run(case, settings, None, overrides)
    overrides = dict(overrides or {})
    base_dt = overrides.get("dt_s", settings["dt_s"])
    base_cycles = overrides.get("cycles", settings["cycles"])
    best, tried = None, []

    def consider(result, ov):
        nonlocal best
        tried.append({"dt_s": ov["dt_s"], "cycles": ov.get("cycles", base_cycles), "status": result["status"]})
        if best is None or STATUS_RANK[result["status"]] > STATUS_RANK[best["status"]]:
            best = result
        return result["status"] == "verified"

    for r in dt_refinements:
        ov = {**overrides, "dt_s": base_dt / r}
        result = _run_verified_at_dt(case, settings, config, ov, ladder, tolerance)
        if consider(result, ov):
            break
        # Runs that finish but have not yet repeated cycle-to-cycle (soft, slow structural
        # mode) get twice the flapping cycles at the same dt before refining dt.
        if any(x["status"] == "ok" and not x["settled"] for x in result.get("attempts", [])):
            ov = {**ov, "cycles": 2 * base_cycles}
            if consider(_run_verified_at_dt(case, settings, config, ov, ladder, tolerance), ov):
                break
    best["dt_attempts"] = tried
    return best


def _run_verified_at_dt(case, settings, config: elastic.ElasticConfig, overrides: dict | None = None,
                        ladder=FACTOR_LADDER, tolerance=0.03) -> dict:
    """Elastic solve that measures its own numerical uncertainty.

    The added-mass factor is a numerical stabilization parameter: physics must not
    depend on it. Walk the ladder until two different factors both finish, settle,
    and agree on thrust and peak torque within ``tolerance``. If they disagree, run
    the rest of the ladder and report the spread over every settled factor.
    Statuses:
      verified    two factors agree within tolerance; the first is reported
      uncertain   >= 2 settled factors disagree; value = midpoint of their range, and
                  *_range fields give min/max (plot as an error bar)
      unverified  only one factor settled (no spread available)
      unresolved  no factor settled
    """
    attempts, good = [], []
    for factor in ladder:
        cfg = elastic.ElasticConfig.from_dict({**config.to_dict(), "added_mass_factor": factor})
        r = run(case, settings, cfg, overrides)
        attempts.append({"added_mass_factor": factor, "status": r["status"], "settled": r.get("settled"),
                         "mean_thrust_N": r.get("mean_thrust_N"), "peak_abs_root_torque_Nm": r.get("peak_abs_root_torque_Nm"),
                         "tip_twist_amplitude_deg": r.get("tip_twist_amplitude_deg"),
                         "tip_bend_amplitude_m": r.get("tip_bend_amplitude_m"),
                         "bend_cycle_error_pct": r.get("bend_cycle_error_pct"),
                         "elapsed_s": r["elapsed_s"], "error": r.get("error")})
        if r["status"] == "ok" and r["settled"]:
            r["added_mass_factor"] = factor
            good.append(r)
        if len(good) == 2 and _spread(good) <= tolerance:
            break
    if not good:
        out = dict(r)
        out.update(status="unresolved", verification="no stabilization factor produced a settled solution")
    elif len(good) == 1:
        out = dict(good[0]); out["status"] = "unverified"
    elif _spread(good) <= tolerance:
        out = dict(good[0]); out["status"] = "verified"; out["verification_spread_pct"] = 100 * _spread(good)
    else:
        out = _uncertain(good)
    out["attempts"] = attempts
    out["elapsed_s"] = round(sum(x["elapsed_s"] for x in attempts), 2)
    return out


def _spread(good) -> float:
    def rel(key):
        v = [g[key] for g in good]
        return (max(v) - min(v)) / max(abs(sum(v) / len(v)), 1e-9)
    values = [rel("mean_thrust_N"), rel("peak_abs_root_torque_Nm")]
    if all("tip_bend_amplitude_m" in g for g in good):
        values.append(rel("tip_bend_amplitude_m"))
        values.append(rel("tip_twist_amplitude_deg"))
    return max(values)


def _uncertain(good) -> dict:
    keys = ("mean_thrust_N", "peak_abs_root_torque_Nm", "tip_twist_amplitude_deg", "thrust_per_torque")
    ranges = {k: [min(g[k] for g in good), max(g[k] for g in good)] for k in keys}
    mid = {k: (lo + hi) / 2 for k, (lo, hi) in ranges.items()}
    # Representative run (for histories/animation): settled factor closest to the midpoint.
    rep = min(good, key=lambda g: abs(g["mean_thrust_N"] - mid["mean_thrust_N"])
              + abs(g["peak_abs_root_torque_Nm"] - mid["peak_abs_root_torque_Nm"]))
    out = dict(rep)
    out.update(status="uncertain", verification_spread_pct=100 * _spread(good),
               representative_added_mass_factor=rep["added_mass_factor"],
               settled_factors=[g["added_mass_factor"] for g in good], **mid,
               thrust_range_N=ranges["mean_thrust_N"], torque_range_Nm=ranges["peak_abs_root_torque_Nm"],
               tip_twist_range_deg=ranges["tip_twist_amplitude_deg"], thrust_per_torque_range=ranges["thrust_per_torque"])
    return out


FRONT_VIEW = (-1.0, 0.15, 0.1)   # from upstream, looking into the leading edge
TOP_VIEW = (0.0, 0.0, 1.0)       # straight down on the planform: straight LE on top, tapered TE below


@contextlib.contextmanager
def camera_view(vector):
    """Render Ptera's animation from another direction.

    In automated (testing) mode Ptera passes the fixed view vector cpos=(-1, -1, 1) to
    pyvista's Plotter.show; interactively, the user would rotate the view by hand.
    This swaps only that vector, only inside this context. Ptera is not modified.
    """
    import pyvista as pv
    from pterasoftware import _output_rendering as OR
    original = pv.Plotter.show
    original_shot = OR.screenshot_image

    def shot(plotter, *args, **kwargs):
        # Ptera fits the clipping range to the first frame only (for body-fixed views);
        # from above, a flapping tip rising toward the camera would then be cut off.
        plotter.reset_camera_clipping_range()
        return original_shot(plotter, *args, **kwargs)

    def show(self, *args, **kwargs):
        if kwargs.get("cpos") is not None and tuple(kwargs["cpos"]) == (-1, -1, 1):
            kwargs["cpos"] = vector
        return original(self, *args, **kwargs)

    pv.Plotter.show = show
    OR.screenshot_image = shot
    try:
        yield
    finally:
        pv.Plotter.show = original
        OR.screenshot_image = original_shot


# Ptera's animate defaults are 1024 x 768 at lossy WebP quality 75, which smears the thin mesh lines.
# Callers can raise these (e.g. for the shareable atlas); Ptera's own code is unchanged.
ANIMATION_OPTIONS = {"window_size": (1024, 768), "quality": 75.0}


def save_native_outputs(solver, directory: Path):
    """Ptera's own plots and animation, exactly as model.run_case writes them, plus a
    wing-only front view in which leading-edge twist is seen face-on (a rigid wing at
    zero pitch is edge-on from this view; a twisting wing shows its surface)."""
    import matplotlib
    import pterasoftware as ps
    directory.mkdir(parents=True, exist_ok=True)
    with matplotlib.rc_context(matplotlib.rcParamsDefault):
        ps.plot_results_versus_time(solver, show=False, save=True, directory=directory, file_format="png")
    ps.animate(solver, scalar_type="lift", show_wake_vortices=True,
               save=True, path=directory / "animation.webp", testing=True, **ANIMATION_OPTIONS)
    with camera_view(FRONT_VIEW):
        ps.animate(solver, scalar_type="lift", show_wake_vortices=False,
                   save=True, path=directory / "animation_front.webp", testing=True, **ANIMATION_OPTIONS)
    with camera_view(TOP_VIEW):
        ps.animate(solver, scalar_type="lift", show_wake_vortices=False,
                   save=True, path=directory / "animation_top.webp", testing=True, **ANIMATION_OPTIONS)


def run(case, settings, config: elastic.ElasticConfig | None, overrides: dict | None = None,
        output_dir: Path | None = None) -> dict:
    """Solve one case. Never raises for solver failures: returns status='failed'.

    output_dir: when given, also save Ptera's native plots and animation there
    (slow; intended for spot checks, not batch runs).
    """
    settings = dict(settings, **(overrides or {}))
    t0 = time.time()
    out = {"design_name": case.get("design_name"), "elastic": config.to_dict() if config else None,
           "dt_s": settings["dt_s"], "cycles": settings["cycles"], "span_panels": settings["span_panels"],
           "chord_panels": settings["chord_panels"], "wake_model": settings["wake_model"],
           "wake_cycles": settings["wake_cycles"]}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            solver, problem = build_solver(case, settings, config)
            solver.run(prescribed_wake=settings.get("wake_model", "free") == "prescribed",
                       calculate_streamlines=False, show_progress=False)
        hist = []
        for step in range(solver.first_results_step, solver.num_steps):
            a = solver.steady_problems[step].airplanes[0]
            thrust, lift = model.single_wing_forces(a)
            hist.append([step * solver.delta_time, thrust, lift, model.wing_root_roll_moment(a)])
        d = np.array(hist)
        if not np.isfinite(d).all():
            raise RuntimeError("Non-finite loads.")
        span = float(case["sections"][-1]["y_m"]) if "sections" in case else (case["span_m"] - settings["gap_m"]) / 2
        m = model.shape_metrics(d[:, 0], d[:, 1:3], d[:, 3], case["frequency_hz"], settings["cycle_tolerance_pct"], span)
        # Compare the last two cycles by time interpolation: dt need not divide the period.
        period, end = 1 / case["frequency_hz"], d[-1, 0]
        phase = np.linspace(0, period, 201)
        last = np.interp(end - period + phase, d[:, 0], d[:, 3])
        prev = np.interp(end - 2 * period + phase, d[:, 0], d[:, 3])
        n = int(round(period / solver.delta_time))
        out.update(status="ok", mean_thrust_N=m["single_wing_mean_thrust_N"],
                   peak_abs_root_torque_Nm=m["single_wing_peak_abs_roll_moment_Nm"],
                   rms_root_torque_Nm=m["single_wing_rms_roll_moment_Nm"],
                   rms_lift_N=float(np.sqrt(np.mean(d[-n:, 2] ** 2))),
                   force_cycle_error_pct=m["single_wing_force_cycle_error_pct"],
                   torque_cycle_error_pct=float(100 * np.sqrt(np.mean((last - prev) ** 2)) / max(np.sqrt(np.mean(last ** 2)), 1e-9)),
                   thrust_per_torque=m["single_wing_mean_thrust_N"] / m["single_wing_peak_abs_roll_moment_Nm"])
        out["settled"] = bool(out["force_cycle_error_pct"] <= settings["cycle_tolerance_pct"]
                              and out["torque_cycle_error_pct"] <= settings["cycle_tolerance_pct"])
        if problem is not None and problem.elastic_history:
            tw = np.array([h[1] for h in problem.elastic_history])
            tt = np.array([h[0] for h in problem.elastic_history])
            sel = tt > tt[-1] - 1 / case["frequency_hz"]
            tip = tw[sel, -1]
            out.update(tip_twist_min_deg=float(tip.min()), tip_twist_max_deg=float(tip.max()),
                       tip_twist_amplitude_deg=float((tip.max() - tip.min()) / 2),
                       peak_abs_twist_deg=float(np.abs(tw[sel]).max()),
                       twist_profile_amplitude_deg=((tw[sel].max(0) - tw[sel].min(0)) / 2).tolist(),
                       strips=elastic.strip_summary(problem))
        out["history"] = {"t": d[:, 0].tolist(), "thrust": d[:, 1].tolist(), "lift": d[:, 2].tolist(), "torque": d[:, 3].tolist()}
        # Compact final-cycle traces (60 samples) for dashboards; full replay is re-solving.
        period = 1 / case["frequency_hz"]
        ph = np.linspace(0, period, 60, endpoint=False)
        tc = d[-1, 0] - period + ph
        cyc = {"phase": (ph / period).round(4).tolist(),
               **{k: np.interp(tc, d[:, 0], d[:, i]).round(5).tolist() for k, i in (("thrust", 1), ("lift", 2), ("torque", 3))}}
        if problem is not None and problem.elastic_history:
            cyc["tip_twist"] = np.interp(tc, tt, tw[:, -1]).round(3).tolist()
            cyc["twist_profile_amplitude_deg"] = [round(v, 3) for v in out["twist_profile_amplitude_deg"]]
        out["final_cycle"] = cyc
        if problem is not None and getattr(problem, "span_history", None):
            import spanwise_elastic
            bh = problem.span_history
            bt = np.array([h[0] for h in bh])
            bw = np.array([h[1] for h in bh])
            bb = np.array([h[2] for h in bh])
            sel = bt > bt[-1] - period
            out.update(structural_model=spanwise_elastic.FINITE_MODEL_VERSION if config.large_deflection else spanwise_elastic.MODEL_VERSION,
                tip_bend_amplitude_m=float(np.ptp(bw[sel,-1])/2),
                peak_abs_tip_deflection_m=float(np.abs(bw[sel,-1]).max()),
                peak_abs_bend_deg=float(np.abs(bb[sel]).max()),
                span_stations_m=problem.structure.y.tolist(),
                span_bending_EI_Nm2=problem.structure.ei,
                chord_spring_Nm_per_rad=problem.structure.chord_k,
                leading_edge_passive_pitch_deg=0. if config.rod.diameter_m and config.rod.fixed_rotation else None)
            cyc["tip_deflection_m"] = np.interp(tc,bt,bw[:,-1]).tolist()
            cyc["span_deflection_amplitude_m"] = (np.ptp(bw[sel],axis=0)/2).tolist()
            bend_last = np.interp(end-period+phase,bt,bw[:,-1])
            bend_prev = np.interp(end-2*period+phase,bt,bw[:,-1])
            out["bend_cycle_error_pct"] = float(100*np.sqrt(np.mean((bend_last-bend_prev)**2))/max(np.sqrt(np.mean(bend_last**2)),1e-6))
            pitch_last = np.interp(end-period+phase,tt,tw[:,-1])
            pitch_prev = np.interp(end-2*period+phase,tt,tw[:,-1])
            out["pitch_cycle_error_pct"] = float(100*np.sqrt(np.mean((pitch_last-pitch_prev)**2))/max(np.sqrt(np.mean(pitch_last**2)),1e-4))
            out["settled"] = bool(out["settled"] and max(out["bend_cycle_error_pct"],out["pitch_cycle_error_pct"]) <= settings["cycle_tolerance_pct"])
            out["span_history"] = {"t":bt.tolist(),"deflection_m":bw.tolist(),"slope_deg":bb.tolist()}
            if config.large_deflection:
                angles = np.radians((bb[:,:-1]+bb[:,1:])/2)
                yl = np.cumsum(np.diff(problem.structure.y)[None,:]*np.cos(angles),axis=1)
                out["span_history"]["leading_edge_y_m"] = np.column_stack((np.zeros(len(yl)),yl)).tolist()
        if output_dir is not None:
            save_native_outputs(solver, Path(output_dir))
    except elastic.ElasticDivergence as exc:
        out.update(status="diverged", error=str(exc))
    except Exception as exc:  # noqa: BLE001 - batch runs must record, not stop
        out.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    out["elapsed_s"] = round(time.time() - t0, 2)
    return out
