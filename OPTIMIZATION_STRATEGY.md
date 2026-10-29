# Wing optimization strategy

Improve **settled-cycle mean single-wing thrust** while keeping **peak absolute
single-wing root roll moment equal or lower than the current design**. There is no torque
ceiling in the search. Thrust/torque is a useful reported ratio, not the sole
objective and not an energy efficiency. Estimated pair thrust is twice the
isolated-wing result; wing interaction is not modeled.

## Search

- Start each requested span from selected families: triangle, rectangular,
  concave/inset, convex/full, and long/narrow. Narrow seeds use a constant half-root chord width (a thin rectangle)
  before applying fabrication bounds. These labels describe
  starting families, not constraints on their descendants.
- Chords are **widths**, at fixed equally spaced span stations. Vary root and
  tip too. Default minimum width is 0.01 m; explicit zero minima on outboard
  stations permit a contiguous removed suffix, leaving two positive sections.
  Root maximum, per-node bounds/steps, and optional decreasing widths apply.
- Poll coordinate, adjacent-pair, and optional coordinated shape changes.
  A candidate wins only if its settled-cycle mean thrust is equal or greater
  than the current parent's and its peak root torque is equal or lower, with
  at least one strict improvement.
  There is no torque tolerance that permits an increase. A torque reduction
  with unchanged thrust is a win; an exact tie is not. Of the qualifying neighbors, continue the highest
  thrust (break ties with lower torque). Each family/span follows one chain.
  All trials remain saved, but only the chosen winner enters evolution history.
  Neighborhood sampling is automatic. Cover the remaining directions before
  shrinking steps after an unsuccessful neighborhood; stop when useful local
  moves are exhausted at the smallest adjustment or the budget is reached.
- Advance family/span jobs fairly. The GUI uses one maximum-new-simulations
  budget, with no separate pass or candidate-request limit. Four Ptera processes are the
  GUI default; use fewer for memory-heavy cases. One coordinator writes IDs,
  histories, results and catalog records. Duplicate requests share a solve.

## Reuse and comparison

`GEOM-…` identifies the undeformed physical outline; redundant collinear
stations share this reference. `SIM-…` identifies the exact simulation,
including section discretization, motion, fluid, numerical settings and solver
provenance. Only an exact simulation match with available outputs authorizes
reuse. Current and Old catalogs are both checked through indexed lookups.
Different time steps correctly require new simulations even for the same wing.

Display **winning evolution designs, with optional seeds**, by default.
Only recorded improvements meeting the strict parent rule appear. Historical
tradeoff events are filtered by that same measured parent rule; no history is
invented for ordinary grid runs. The highest-thrust-per-0.1-N-m-band and full
frontier views remain optional. Bands and plot filters affect comparison only. Color/filter by seed
family to compare search basins; retain common physical silhouette scale.
Results and ancestry save automatically; exports produce additional views.

## Confidence and stopping

This is a budgeted local direct search, not a global-optimum certificate.
Hypervolume and repeated fine polls indicate progress, not physical validation.
Compare designs under common driving conditions and verify promising designs
with finer panels/time steps, more settled cycles and tank measurements.
Native aeroelasticity is optional; increased damping alone does not establish
stability or physical accuracy. Root moments omit drivetrain conversion and
any structural inertia absent from the chosen native model.
