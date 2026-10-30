# Torque–thrust optimization strategy

The goal is the best observed thrust available across a range of peak single-wing
root torques:

`T_best(Q) = max mean_thrust(chords), subject to peak_root_torque(chords) <= Q`.

Q is swept across a range, rather than imposing one chosen motor limit. Root
moments are hydrodynamic loads; drivetrain conversion remains outside this model.
Thrust/peak torque is a reported ratio, not the search objective or energy efficiency.

## Geometry and initialization

Use the selected triangle, rectangular, concave/inset, convex/full and narrow
rectangular seed families at each requested span. Narrow rectangles use half the
seed root width before applying bounds. Chord variables are widths at fixed span
stations; root and tip may vary within their bounds. Default positive minimum is
0.01 m. Explicit zero minima permit an outboard removed suffix and shorten actual
span. For fixed root width, set the root row minimum equal to its maximum; for a
fixed actual span, set span endpoints equal and retain positive outboard minima.

## Search and reuse

1. Evaluate or reuse the seeds. Unless bounds are entered, sample available torque
   from half the lowest seed torque to 1.25 times the highest, using 12 targets.
2. At every target and span, use the highest-thrust feasible result from all seed
   families and trials. A candidate may increase torque from its parent while
   remaining feasible at Q. Ties in thrust favor lower torque.
3. Poll coordinate and simultaneous opposite-sign chord changes. When enough
   full-rank local data exist, fit torque sensitivities to propose balanced
   redistribution. Every proposal is verified by native Ptera. The model never
   substitutes a fitted result for a simulation.
4. Share every evaluated candidate across all targets at the same reference span.
   Shrink unsuccessful local steps; try other seed basins when stalled. Below the
   feasible range, explore lower torque even if thrust falls, but never label an
   infeasible sample a target winner.
5. Interleave target requests, deduplicate geometry requests, and use the one
   shared maximum-new-simulations budget. Cache hits are free. Parallel native
   cases remain isolated; one coordinator writes catalog and study outputs.

`GEOM-...` references physical geometry. `SIM-...` includes exact motion, fluid,
mesh, time step and native-solver provenance. Only an exact simulation match with
available outputs authorizes reuse. No Ptera source modifications are introduced.

## Results and confidence

The primary wing plot shows current target winners, with optional starting seeds;
superseded incumbents and rejected trials remain saved. Choose an available torque
to inspect its winning design. `comparisons/torque_curve.csv` records every target,
its winner, thrust, actual torque and local-search status. Unattained targets stay
explicitly empty. `torque_targets.json` updates during the search; evolution keeps
incumbent history, and original native plots/animations remain per case.

This builds a sampled, locally optimized torque–thrust curve, not a certified
continuous/global optimum. In particular, an empty target has no feasible sampled
wing; it is not proof of physical impossibility. Verify finalists with finer mesh,
time step, longer settling and tank tests. Compare only consistent driving settings;
frequency variation is a separate study. Native aeroelasticity remains optional.
