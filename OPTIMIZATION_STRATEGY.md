# Wing optimization strategy

Find useful tradeoffs between **higher settled-cycle mean single-wing thrust**
and **lower peak absolute single-wing root roll moment**. There is no torque
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
  Keep every result and every nondominated thrust/torque tradeoff. Refine a
  small active beam; continue the child with the greatest marginal
  two-objective hypervolume gain against the frozen pre-poll archive.
  Neighborhood size and direction rotation are automatic, sharing work
  across families without an additional user-facing poll-size control.
  Shrink adjustment sizes after each poll so archive growth cannot starve
  fine refinement. Refill the beam when its local branches finish.
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

Display the **highest mean thrust in each occupied 0.1 N m torque band** by
default. Bands and plot filters affect comparison only. Color/filter by seed
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
