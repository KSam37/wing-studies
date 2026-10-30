# Independent wing coordinate optimization

Goal: evolve each shape/span seed independently using one editable torque weight,
then compare the measured thrust–torque tradeoffs. Native Ptera physics is unchanged.

## Objective

S = T / Tref - lambda * M / Mref.

T is settled-cycle mean single-wing thrust. M is sampled peak absolute hydrodynamic
roll moment about the wing root, not gearbox or motor-shaft torque. Tref is the
largest absolute thrust of valid starting seeds; Mref is the largest seed torque.
Both scales are fixed once for the whole study and saved in coordinate_objective.json.
Lambda defaults to 0.75, giving normalized thrust changes slightly more weight.
Acceptance requires score increase greater than the editable tolerance (default 1e-6).
That tolerance is not a calibrated solver-uncertainty estimate. No torque ceiling applies.

## Search, exactly

1. Evaluate/reuse all selected shape/span seeds. Triangle, rectangle, concave,
   convex and narrow rectangle are independent lineages. Duplicate physical cases
   reuse simulations, but acceptance and parent links remain local to each seed.
2. On the first root-to-tip pass, test +step and -step on one chord from the same
   current parent. Default step is 0.02 m, editable per chord. Choose the larger
   positive score change, accept it, remember its sign, and move to the NEXT chord.
   These finite differences supply the local directional score sensitivity.
3. On subsequent passes, test only each chord's remembered winning sign. Keep
   the same full step following success, moving to the next chord after each trial.
4. When that direction fails or is blocked, try one half step from the last
   accepted parent. Accept it only if the score increases, then retire that chord
   regardless of success. No recursive shrinking. If neither initial sign wins,
   try both signs once at half size, choose the best positive change, and retire it.
5. Continue root-to-tip passes until all chords are retired, or the shared new-
   simulation budget is reached. Retired chords are not generally reopened when neighbors
   change, except that a newly exposed tip gets another turn after its outer
   neighbor disappears. This can stop short of a coordinate stationary point; do not claim global
   convergence. Failed/unsettled cases cannot become accepted parents.

## Geometry and execution

Only chord WIDTH changes; station spacing remains fixed within a seed grid.
Root maximum is adjustable, and root width may shrink. Positive widths default
at least 0.01 m. Zero is permitted only as a contiguous outer suffix. Normal
negative width steps can reach/snap to zero, so the previous positive section
becomes the active tip. Positive section values below the floor snap to zero
only for a removable active tip; no hidden tiny positive chords. Native Ptera
omits zero sections, reducing actual span discretely, and requires two positive
sections. Bounds and optional decreasing widths constrain each coordinate change.
No extra beam model, geometry adapter, special deletion solver, or torque conversion.

The coordinator advances lineages together and batches independent native cases
across the selected processes. One writer owns IDs, files and the master catalog.
Exact physical AND numerical identity is required for cache reuse. Cached results
are free against the new-simulation budget; all rejected results remain saved.

## Results

The evolution view shows seeds and accepted descendants with dashed connections
in ancestry order, never sorted-by-torque connections. Each lineage has its own
score/thrust/torque progress trace and selected-wing evolution GIF. The final
comparison can instead show the highest measured thrust per occupied 0.25 N m
band (editable), breaking exact thrust ties by lower torque. Bands are display only.
Raw cases, histories, native plots, animations, SVGs, trial CSV, accepted events,
fixed objective scales and lineage statuses are autosaved.

This is local weighted coordinate ascent. Linear scalarization may miss nonconvex
frontier regions. A finite budget, retired coordinates or flat traces do not certify
an optimum. Finalists need mesh/time/wake/settling checks and water-tank validation.
Legacy studies and their torque-envelope or Pareto histories remain readable.
