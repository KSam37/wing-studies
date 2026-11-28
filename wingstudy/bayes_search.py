"""Bayesian optimization of FAAV wings: most thrust under each torque budget, on the 8 x 4 search mesh.

    python -m wingstudy.bayes_search --freq 1.0 [--budgets 0.75 1 1.25 1.5] [--solves 1000] [--workers 21]
                                     [--init 32] [--span 150 400] [--free-root 50] [--seed 0] [--out DIR]
                                     [--dry] [--fake]

Wing: the FAAV build (0.5 mm sheet, chordwise model, model "t0.50"), 8 chord stations as in every atlas study. The
search variables are the unit cube [0, 1]^d:
  x1..x7   taper ratios: chord k = max(10 mm, chord k-1 * (0.15 + 0.85 x_k)), so outlines never widen toward the tip
  x8       half-span between --span lo and hi (default 150-400 mm, one sheet)
  x9       root chord between --free-root and 200 mm (only with --free-root; otherwise the root is 200 mm)

Two Gaussian processes (Matern 5/2, one length scale per variable, hyperparameters by maximum likelihood) model
thrust and log peak torque. Each new wing maximizes constrained expected improvement for one budget B, taken in
turn: EI over the best verified thrust at or below B times the probability that torque is at or below B. A solve
that fails or returns no forces is infeasible: it enters the torque model above every budget (the largest torque
seen, and at least twice the largest budget). Solves run
asynchronously: whenever a worker frees, the next wing is chosen with the wings still running filled in at their
predicted values (kriging believer), so every worker stays busy.

Solves go through the study solver (wingstudy.studies.run: same engine, verification ladder, cache and keys as the
evolutionary budget studies), so results are directly comparable and a repeated wing is never solved twice. The
first --init wings are a scrambled Sobol design. Nothing from the atlas is used: the search starts cold, which is
what the method comparison needs.

Writes OUT/trace.jsonl (one line per finished solve; a rerun resumes from it) and OUT/results.json (study-results
form, read by tools/build_site.py from atlas/bayes/<name>.json). --dry prints the settings and the first wings;
--fake runs the whole loop on an analytic stand-in for the solver, in seconds, to test the machinery.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

import numpy as np

from .studies import spec as S

OUT = S.ROOT / "outputs" / "bayes"
MODEL, STRUCTURE = "t0.50", "chordwise"
NUMERICS = {"span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4}
ROOT_MM, MIN_CHORD = 200.0, 10.0
RATIO_LO = 0.15
BUDGETS = (0.75, 1.0, 1.25, 1.5)
GOOD = ("verified", "ok")


# ----------------------------------------------------------------------------- parameters
def wing_of(x, span=(150.0, 400.0), root=None) -> tuple[list[float], float]:
    """Unit-cube point -> (8 chords in mm, half-span in mm), rounded to 0.1 mm and 1 mm."""
    r = ROOT_MM if root is None else root + (ROOT_MM - root) * float(x[8])
    ch = [round(r, 1)]
    for k in range(7):
        ch.append(round(max(MIN_CHORD, ch[-1] * (RATIO_LO + (1 - RATIO_LO) * float(x[k]))), 1))
    return ch, float(round(span[0] + (span[1] - span[0]) * float(x[7])))


def case_of(x, freq, span, root, tag) -> dict:
    ch, h = wing_of(x, span, root)
    return {"model": MODEL, "structure": STRUCTURE, "freq": freq, "chords_mm": ch, "half_span_mm": h,
            "numerics": dict(NUMERICS), "wing": tag}


# ----------------------------------------------------------------------------- Gaussian process
def _matern52(A, B, ell, s2):
    d2 = np.zeros((len(A), len(B)))
    for k in range(A.shape[1]):                     # one variable at a time: no (n, m, d) temporary
        d2 += (np.subtract.outer(A[:, k], B[:, k]) / ell[k]) ** 2
    t = math.sqrt(5) * np.sqrt(d2)
    return s2 * (1 + t + t * t / 3) * np.exp(-t)


class GP:
    """Zero-mean GP on standardized targets; theta = log [lengthscales..., signal variance, noise variance]."""

    def __init__(self, dim):
        self.theta = np.r_[np.log(np.full(dim, 0.3)), 0.0, np.log(1e-3)]

    def _unpack(self, th):
        return np.exp(th[:-2]), math.exp(th[-2]), math.exp(th[-1])

    def _nll(self, th, X, y):
        ell, s2, nv = self._unpack(th)
        K = _matern52(X, X, ell, s2) + (nv + 1e-8) * np.eye(len(X))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return 1e10
        a = np.linalg.solve(L.T, np.linalg.solve(L, y))
        return 0.5 * y @ a + np.log(np.diag(L)).sum()

    def fit(self, X, y, rng, max_points=400):
        """Maximum-likelihood hyperparameters on at most max_points points (the best ones plus a random rest)."""
        from scipy.optimize import minimize
        if len(X) > max_points:
            best = np.argsort(-y)[: max_points // 4]
            rest = rng.choice(np.setdiff1d(np.arange(len(X)), best), max_points - len(best), replace=False)
            idx = np.r_[best, rest]
            X, y = X[idx], y[idx]
        m, s = y.mean(), y.std() or 1.0
        ys = (y - m) / s
        d = X.shape[1]
        bounds = [(math.log(0.02), math.log(5.0))] * d + [(math.log(0.05), math.log(20.0)), (math.log(1e-6), math.log(0.2))]
        starts = [self.theta, np.r_[np.log(np.full(d, 0.5)), 0.0, np.log(1e-2)]]
        best = None
        for th0 in starts:
            r = minimize(self._nll, th0, args=(X, ys), method="L-BFGS-B", bounds=bounds, options={"maxiter": 60})
            if best is None or r.fun < best.fun:
                best = r
        self.theta = best.x

    def condition(self, X, y):
        self.X, self.m, self.s = X, y.mean(), (y.std() or 1.0)
        ell, s2, nv = self._unpack(self.theta)
        K = _matern52(X, X, ell, s2) + (nv + 1e-8) * np.eye(len(X))
        self.L = np.linalg.cholesky(K + 1e-8 * np.eye(len(X)))
        self.a = np.linalg.solve(self.L.T, np.linalg.solve(self.L, (y - self.m) / self.s))
        return self

    def predict(self, Xs):
        ell, s2, _ = self._unpack(self.theta)
        Ks = _matern52(Xs, self.X, ell, s2)
        mu = Ks @ self.a
        from scipy.linalg import solve_triangular
        v = solve_triangular(self.L, Ks.T, lower=True)
        var = np.maximum(s2 - (v * v).sum(0), 1e-12)
        return self.m + self.s * mu, self.s * np.sqrt(var)


def _phi(z):
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _Phi(z):
    from scipy.special import ndtr
    return ndtr(z)


# ----------------------------------------------------------------------------- the search
class Search:
    def __init__(self, a, rng):
        self.a, self.rng = a, rng
        self.dim = 9 if a.free_root else 8
        self.done = []            # dicts: x, case, result, target, n
        self.gT, self.gQ = GP(self.dim), GP(self.dim)
        self.fitted_at = -1

    # data -------------------------------------------------------------
    def arrays(self, pending=()):
        X, T, Q = [], [], []
        qmax = max([math.log(r["result"]["torque_Nm"]) for r in self.done if self._has(r)] + [math.log(2 * max(self.a.budgets))])
        for r in self.done:
            X.append(r["x"])
            if self._has(r):
                T.append(r["result"]["thrust_N"])
                Q.append(math.log(r["result"]["torque_Nm"]))
            else:
                T.append(None)
                Q.append(qmax + 0.3)
        return np.array(X), T, np.array(Q)

    @staticmethod
    def _has(r):
        res = r["result"]
        return res.get("thrust_N") is not None and res.get("torque_Nm") is not None and res["torque_Nm"] > 0

    def best(self, B):
        ok = [r["result"]["thrust_N"] for r in self.done if self._has(r) and r["result"]["status"] in GOOD
              and r["result"]["torque_Nm"] <= B + 1e-9]
        return max(ok) if ok else None

    def refit(self, force=False):
        X, T, Q = self.arrays()
        n = len(X)
        if force or self.fitted_at < 0 or n - self.fitted_at >= max(self.a.workers, n // 8):
            mt = np.array([t is not None for t in T])
            self.gT.fit(X[mt], np.array([t for t in T if t is not None]), self.rng)
            self.gQ.fit(X, Q, self.rng)
            self.fitted_at = n

    # proposals --------------------------------------------------------
    def propose(self, pending, target, seen_keys, key_of):
        """One new point for budget `target`, with the running points filled in at their predicted values."""
        X, T, Q = self.arrays()
        mt = np.array([t is not None for t in T])
        XT, yT = X[mt], np.array([t for t in T if t is not None])
        P = np.array([p["x"] for p in pending]) if pending else np.zeros((0, self.dim))
        gT = GP.__new__(GP); gT.theta = self.gT.theta
        gQ = GP.__new__(GP); gQ.theta = self.gQ.theta
        gT.condition(XT, yT)
        gQ.condition(X, Q)
        if len(P):                                   # kriging believer
            fT, _ = gT.predict(P)
            fQ, _ = gQ.predict(P)
            gT.condition(np.r_[XT, P], np.r_[yT, fT])
            gQ.condition(np.r_[X, P], np.r_[Q, fQ])
        from scipy.stats import qmc
        cand = [qmc.Sobol(self.dim, scramble=True, seed=self.rng).random(1024)]
        logB = math.log(target)
        good = [r for r in self.done if self._has(r) and r["result"]["status"] in GOOD]
        near = sorted(good, key=lambda r: -(r["result"]["thrust_N"] if r["result"]["torque_Nm"] <= target else
                                             r["result"]["thrust_N"] * (target / r["result"]["torque_Nm"]) ** 2))[:6]
        for r in near:
            for sd in (0.02, 0.06, 0.15):
                cand.append(np.clip(np.array(r["x"]) + self.rng.normal(0, sd, (120, self.dim)), 0, 1))
        C = np.vstack(cand)
        muT, sdT = gT.predict(C)
        muQ, sdQ = gQ.predict(C)
        pf = _Phi((logB - muQ) / sdQ)
        f0 = self.best(target)
        if f0 is None:
            acq = pf * (muT + sdT)                   # nothing feasible yet: feasible and promising
        else:
            z = (muT - f0) / sdT
            acq = pf * (sdT * (z * _Phi(z) + _phi(z)))
        for j in np.argsort(-acq):
            k = key_of(C[j])
            if k not in seen_keys:
                return C[j], float(acq[j]), float(muT[j]), float(math.exp(muQ[j]))
        return C[int(np.argmax(acq))], 0.0, float(muT[0]), float(math.exp(muQ[0]))


# ----------------------------------------------------------------------------- solving
def _fake_solve(case):
    """Analytic stand-in: thrust ~ area-weighted span, torque ~ span^2.5, some failures at large twist."""
    ch, h = np.array(case["chords_mm"]) / 1000, case["half_span_mm"] / 1000
    f = case["freq"]
    eta = np.linspace(0, 1, len(ch))
    w = eta ** 1.2
    T = 14 * f ** 2 * h ** 1.6 * float((ch * (0.4 + w)).mean()) * (1 - 2.5 * float(((ch - 0.06) ** 2 * w).mean()))
    Q = 220 * f ** 2 * h ** 2.5 * float((ch * (0.2 + w ** 1.5)).mean())
    if h > 0.37 and ch[-1] < 0.012:
        return {"status": "failed", "thrust_N": None, "torque_Nm": None, "error": "twist above 80 deg"}
    return {"status": "verified", "thrust_N": T, "torque_Nm": Q, "tip_twist_deg": 40.0}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.bayes_search", description=__doc__.split("\n\n")[0])
    ap.add_argument("--freq", type=float, default=1.0)
    ap.add_argument("--budgets", type=float, nargs="+", default=list(BUDGETS))
    ap.add_argument("--solves", type=int, default=1000, help="total solves, Sobol start included")
    ap.add_argument("--init", type=int, default=32)
    ap.add_argument("--workers", type=int, default=21)
    ap.add_argument("--span", type=float, nargs=2, default=[150.0, 400.0])
    ap.add_argument("--free-root", type=float, default=None, help="also search the root chord, from this value to 200 mm")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--fake", action="store_true", help="analytic stand-in for the solver (tests the loop)")
    a = ap.parse_args(argv)
    name = f"f{a.freq:.2f}".replace(".", "p") + ("-root" if a.free_root else "") + ("-fake" if a.fake else "")
    out = a.out or OUT / name
    rng = np.random.default_rng(a.seed)
    se = Search(a, rng)
    from scipy.stats import qmc
    init = qmc.Sobol(se.dim, scramble=True, seed=a.seed).random(a.init)
    span = tuple(a.span)

    if a.fake:
        digest, code = "fake", {"digest": "fake"}
    else:
        from .identity import code_identity
        code = code_identity()
        digest = code["digest"]
    from .studies import run as SR

    def key_of(x):
        c = case_of(x, a.freq, span, a.free_root, "")
        return SR.job_for(c, digest)["key"]

    print(f"Bayesian search, FAAV {MODEL} {STRUCTURE}, {a.freq:g} Hz, budgets {a.budgets} N·m, {a.solves} solves "
          f"({a.init} Sobol), span {span[0]:g}-{span[1]:g} mm, root {'%g-200 mm' % a.free_root if a.free_root else '200 mm'}, "
          f"{a.workers} workers, code {digest}, out {out}", flush=True)
    if a.dry:
        for x in init[:6]:
            print("  ", *wing_of(x, span, a.free_root), key_of(x))
        return 0

    out.mkdir(parents=True, exist_ok=True)
    trace = out / "trace.jsonl"
    seen = set()
    if trace.exists():                               # resume
        for line in trace.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                se.done.append(r)
                seen.add(r["case"]["key"])
        print(f"resumed {len(se.done)} solves from {trace}", flush=True)

    def solve_job(c):
        if a.fake:
            return _fake_solve(c)
        return SR.solve(SR.job_for(c, digest))

    def cached(c):
        if a.fake:
            return None
        p = SR.CACHE / f"{c['key']}.json"
        return S.read_json(p)["result"] if p.exists() else None

    pending, n_next, tgt = {}, len(se.done), 0
    t0 = time.time()
    pool = ProcessPoolExecutor(max_workers=a.workers) if not a.fake else None
    fh = trace.open("a", encoding="utf-8")

    def submit(x, target, info):
        nonlocal n_next
        n_next += 1
        c = case_of(x, a.freq, span, a.free_root, f"bayes {name} #{n_next}")
        job = SR.job_for(c, digest)
        c["key"] = job["key"]
        seen.add(c["key"])
        rec = {"n": n_next, "x": [float(v) for v in x], "case": c, "target": target, "info": info,
               "proposed": time.strftime("%Y-%m-%dT%H:%M:%S")}
        hit = cached(c)
        if hit is not None or a.fake:
            finish(rec, hit if hit is not None else _fake_solve(c))
            return
        pending[pool.submit(SR.solve, job)] = rec

    def finish(rec, res):
        if not a.fake and SR.CACHE.exists() and not (SR.CACHE / f"{rec['case']['key']}.json").exists():
            S.write_json(SR.CACHE / f"{rec['case']['key']}.json", {"key": rec["case"]["key"], "job": SR.job_for(rec["case"], digest),
                                                                  "result": res, "code": code, "solved": SR.now()})
        rec = dict(rec, result=res, finished=time.strftime("%Y-%m-%dT%H:%M:%S"))
        se.done.append(rec)
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        bests = " ".join(f"{B:g}:{(se.best(B) or 0):.3f}" for B in a.budgets)
        T, Q = res.get("thrust_N"), res.get("torque_Nm")
        print(time.strftime("%H:%M:%S"), f"{len(se.done)}/{a.solves}", f"B{rec['target']}", res.get("status"),
              f"{T:.3f} N {Q:.3f} N·m" if T is not None and Q is not None else res.get("error"), "| best", bests, flush=True)

    def next_point(free):
        nonlocal tgt
        for _ in range(free):
            if n_next >= a.solves:
                return
            if n_next < a.init:
                submit(init[n_next], None, {"phase": "sobol"})
                continue
            if sum(se._has(r) for r in se.done) < max(8, a.init // 2):
                return                                # wait for enough of the Sobol start
            se.refit()
            B = a.budgets[tgt % len(a.budgets)]
            tgt += 1
            x, acq, muT, muQ = se.propose(list(pending.values()), B, seen, key_of)
            submit(x, B, {"phase": "bo", "acq": acq, "pred_thrust": muT, "pred_torque": muQ})

    try:
        while n_next < a.solves or pending:
            next_point(a.workers - len(pending) if pool else 1)
            if not pending:
                if n_next >= a.solves:
                    break
                continue
            ready, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fu in ready:
                rec = pending.pop(fu)
                try:
                    res = fu.result()
                except Exception as exc:
                    res = {"status": "failed", "error": f"worker crashed: {exc}"}
                finish(rec, res)
    finally:
        fh.close()
        if pool:
            pool.shutdown(cancel_futures=True)
    write_results(out, name, a, code, se)
    print(f"done: {len(se.done)} solves in {(time.time() - t0) / 60:.1f} min; best " +
          ", ".join(f"≤ {B:g} N·m {se.best(B) or 0:.3f} N" for B in a.budgets), flush=True)
    return 0


def write_results(out, name, a, code, se):
    from .studies import run as SR
    cases = []
    for r in sorted(se.done, key=lambda r: r["n"]):
        c = dict(r["case"], case_id=f"c{r['n']:04d}", **{k: v for k, v in r["result"].items() if k not in ("history",)})
        cases.append(c)
    counts = {}
    for c in cases:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    S.write_json(out / "results.json", {
        "schema": S.RESULTS_SCHEMA, "study": f"bayes-{name}", "kind": "bayesian", "code": code,
        "title": f"Bayesian optimization, FAAV sheet, {a.freq:g} Hz",
        "question": (f"How quickly does Bayesian optimization (two Gaussian processes, constrained expected improvement "
                     f"per torque budget {', '.join(f'{B:g}' for B in a.budgets)} N·m) find the best FAAV wing at "
                     f"{a.freq:g} Hz, starting cold from {a.init} Sobol wings?"),
        "settings": {"freq": a.freq, "budgets": a.budgets, "solves": a.solves, "init": a.init, "workers": a.workers,
                     "span_mm": a.span, "free_root_mm": a.free_root, "seed": a.seed, "ratio_lo": RATIO_LO},
        "completed": SR.now(), "counts": counts, "cases": cases,
        "order": [{"n": r["n"], "key": r["case"]["key"], "target": r["target"], "phase": r["info"].get("phase")}
                  for r in sorted(se.done, key=lambda r: r["n"])]})


if __name__ == "__main__":
    raise SystemExit(main())
