# Span bending and independent sheet flex

> `wingstudy/spanwise_elastic.py` still refers to this file by its old name, SPANWISE_ELASTICITY.md. The module's bytes are part of the structural fingerprint, so its docstring is left unchanged.

This is an **opt-in reduced structural model**, coupled to Ptera's existing aeroelastic UVLM. It adds span deflection to version 1.5; it is not a native Ptera feature and does not modify the installed Ptera source. Historical atlas results remain torsion-only and are not relabeled or recomputed. The current focus is **0.5 mm carbon sheet without a rod**, including finite rotations.

## Finite-rotation mode (recommended for the bare 0.5 mm sheet)

`large_deflection=True` replaces linear span displacement with a chain of length-preserving segments. Root slope and passive pitch are fixed; all other station slopes `beta_i` and sheet pitches `theta_i` are free. For each span interval of material length `h_i`:

```
alpha_i = (beta_i + beta_(i+1)) / 2
delta_y_i = h_i cos(alpha_i)
delta_z_i = h_i sin(alpha_i)
U_bend = sum[ EI_i / (2 h_i) (beta_(i+1) - beta_i)^2 ]
```

Thus the span bends by rotating springs; it cannot gain material length as deflection grows. Sheet pitch rotates the chord behind the leading-edge point and cannot displace the centerline. Root slope is exactly zero; the finite first interval approximates root curvature and converges as intervals are refined.

The structural mass matrix is recomputed from analytic point-position Jacobians in the current pose. The inertial forcing includes the configuration-dependent acceleration, Coriolis, centrifugal and imposed-flap-acceleration terms. Fluid forces and moments enter through virtual work. Added-inertia stabilization is also assembled in the current pose. Integration remains partitioned and linearized per time step, so time-step, cycle and stabilization checks remain essential.

Default finite-mode guards are 75 degrees of span slope, 80 degrees of sheet pitch and tip displacement below 95% of the material span. These are numerical/geometric guards, **not validated accuracy limits**. The earlier 20-degree linear-beam guard is retained for `large_deflection=False`.

This is a planar bending / sheet-pitch reduction, not a full 3-D discrete-elastic-rod or laminate-shell solver: no span stretching, in-plane bending, self-contact, cross-section camber or complete anisotropic bend/twist coupling. It allows larger deflections without the linear model's artificial extension, but large fluid angles still challenge UVLM. The [discrete elastic rods literature](https://www.cs.columbia.edu/cg/rods/) motivates preserving rod geometry and using curvature energy; this implementation is a simpler model, not a reproduction of that paper.

## What the atlas established

The supplied Elastic Wing Atlas separates rod, bare-plate, geometric-sweep and historical rigid results. It reports final-cycle mean single-wing thrust, peak absolute fluid root roll moment, passive pitch, numerical repeatability and native animations. The rod campaign assumed the rod's torsional stiffness resisted the sheet's passive pitch. That assumption made both sheet thicknesses nearly rigid. Bare-sheet candidates sometimes reached 50–70 degrees of pitch, already outside a comfortable small-deformation interpretation. The new model addresses missing span bending and separates the rotation-constrained rod from sheet pitch; it does not retrospectively validate those results.

## Structural degrees of freedom

Each station has leading-edge displacement `w`, span slope `beta = dw/dy`, and sheet pitch `theta`. The root has `w = beta = theta = 0` relative to prescribed flapping. The tip is free: no artificial tip support or spring to ground is added for span bending.

Span bending uses cubic Hermite Euler–Bernoulli elements rather than uncoupled local load-to-angle formulas. This is a beam-consistent rotational-spring discretization: curvature costs energy, and loads on outboard panels reach inboard sections. Its element stiffness is the usual four-by-four beam matrix, proportional to `EI / h^3`.

For sheet thickness `t`, local mean chord `c`, and rod outer/inner diameters `do, di`:

```
EI_span = E_sheet c t^3 / 12 + E_rod pi (do^4 - di^4) / 64
GJ_sheet = G_sheet c t^3 / 3
```

Bare wings retain sheet torsion and the existing version 1.5 warping regularization. A fitted rod with `fixed_rotation=True` has zero passive torsional rotation relative to the flapping/bending frame. Its bending stiffness and mass remain active. Its `GJ` does **not** lock the sheet's passive pitch.

Behind that fixed-rotation rod, the sheet has an equivalent chord-bending spring:

```
k_chord = 3 E_sheet I_chord / c
I_chord = dy t^3 / 12
```

This matches the tip displacement of a tip-loaded chordwise cantilever through `delta_tip = c theta` and `M = F c`. It is an equivalent spring, not a literal hinge or a resolved curved cross-section. Ptera still sees straight chord sections. A true clamped sheet's zero slope at the rod and chordwise camber require more chordwise structural degrees of freedom. Attachment compliance and measured laminate stiffness should replace this estimate when available.

The leading-edge position is rebuilt independently of sheet pitch. Relative section translations and rotations are then passed to native Ptera geometry. Pitch cannot accidentally rotate downstream leading-edge offsets, a possible error when adding roll and pitch to a chained section model.

## Loads and integration

The model uses every strip's panel forces and moments, transported to the strip's leading-edge midpoint and projected into the prescribed wing frame. Virtual work distributes them to span displacement, slope and sheet-pitch degrees of freedom. It does not apply the same root moment to every section.

Consistent structural mass includes heave/pitch coupling and rod mass. The added-water-inertia estimate includes both heave and pitch and their coupling. For a local chord `c`, per unit span:

```
m_added = pi rho c^2 / 4
I_added_midchord = pi rho c^4 / 128
z(x,y) ~= w(y) - x theta(y)
```

Version 1.5's generalized-alpha time stepping and lagged added-mass correction are extended to the combined matrix system. Structural forcing includes prescribed flap acceleration. The stabilization factor is numerical, not material damping. Repeatability checks compare thrust, torque, tip deflection and tip pitch at different factors; span deflection must also settle cycle-to-cycle.

**Reported root torque remains the fluid root roll moment**, to match the atlas. It is not a motor load prediction and does not include the complete actuator reaction from solid inertia, drivetrain losses or linkage forces.

## Limits and assumptions

- Straight leading edge, initially planar isolated right wing; unsupported sweep, gull geometry and multiple wings are rejected.
- The linear alternative has linear beam strain and inertia and omits large-rotation corrections. Finite mode uses the current geometry/inertia as described above. Both retain an equivalent sheet-pitch spring and omit resolved chordwise camber and full laminate-shell coupling.
- For the linear alternative, the maximum span slope is 20 degrees and maximum deflection is 25% of active span. Reaching any configured limit is a rejected result, not a clipped deformation. A limit crossing alone does not distinguish physical excessive flexibility from fluid-coupling instability; repeat at smaller time steps.
- Sheet defaults remain `E = 50 GPa`, `G = 4.5 GPa`, density `1550 kg/m^3`; rod longitudinal `E = 120 GPa` is a new editable **assumption**, not a measured property. The rod campaign uses the existing 5 mm OD / 3 mm ID tube.
- Numerical repeatability is not physical validation. UVLM still omits separation, viscous rod drag and leading-edge vortices. The reduced model needs a static deflection/twist check on the actual sheet and tube, followed by water-tank comparison.

## Run it

Double-click **Run Span Flex Study.cmd** in this version 1.5 folder. It opens a new finite-rotation campaign for the **0.5 mm sheet without a rod**, plus the rigid reference, without automatically starting the campaign. It reuses the configured Python installation and keeps results separate under `outputs/elastic/campaigns/finite-span-plate`.

From the configured Python environment:

```
python -m wingstudy.elastic_campaign dashboard --large-deflection --variant plate --workers 4
python -m wingstudy.elastic_campaign dashboard --large-deflection --variant rod --workers 4
```

Use `--smoke` and a fresh `--campaign` folder for a small trial. Do not start a large bare-plate search until the desired thickness/span range passes deformation, time-step and mesh checks. `--spanwise-bending` without `--large-deflection` selects the linear alternative. To resume, supply the saved campaign folder. Asking to enable a new structural model inside a legacy campaign is rejected. Model version, material/options and resolution are included in new case identities so old torsion-only results cannot be reused as span-flex results.

For direct runs, set `ElasticConfig(spanwise_bending=True, ...)`; omit it to retain legacy behavior. Material properties, rod dimensions/rotation constraint, damping, stabilization and deformation limits live in that configuration. Campaign plans are stored in SQLite; changing a JSON export alone does not change an existing campaign.

The dashboard's design detail now includes a tip-deflection trace. Native plots and side/front/top animations use the deformed mesh. The new model does not replace the existing offline atlas snapshot. `span_history` stores physical deflection and, in finite mode, the instantaneous projected leading-edge coordinates.

## Verification artifacts

`python -m unittest discover -s tests -p test_spanwise_elastic.py -v` checks analytical tip-load and distributed-load deflections, first bending frequency, positive energy, static equilibrium, fixed leading-edge geometry, rod/sheet separation and distinct case identities. The existing `test_elastic.py` verifies unchanged legacy torsion behavior.

`python -m wingstudy.check_spanwise_elastic --animation` runs a bounded set of rigid-limit, rod, bare-sheet, stabilization and time-step checks. Outputs are under `outputs/elastic/span_validation`: full `validation.json`, a comparison PNG, and native animation/plots. These checks do not enter a campaign or either master catalog.

`python -m unittest discover -s tests -p test_finite_span.py -v` additionally verifies segment lengths at 70-degree bending, the point Jacobian and virtual work, positive pose-dependent mass/added inertia, unchanged leading edge under sheet pitch, and convergence to the small-load cantilever solution. `python -m wingstudy.check_finite_span --animation` tests the 0.5 mm bare wing at different stabilization factors, time steps and mesh sizes, saving `finite_validation.json` and the associated PNG and native animations.

## Sources and confidence

- [TU Delft: Euler–Bernoulli beam elements](https://teachbooks.tudelft.nl/computational-modelling/structural_linear/euler_bernouilli.html) supplies the Hermite beam formulation and stiffness matrix.
- [Causin, Gerbeau and Nobile (2005)](https://doi.org/10.1016/j.cma.2004.12.005) explains why light structures in incompressible fluid can destabilize partitioned coupling. The local added-inertia treatment here extends version 1.5; that paper does not validate this implementation.
- Native integration points were checked against the installed Ptera `AeroelasticUnsteadyProblem`, aeroelastic movement/geometry classes and `aeroelastic_unsteady_first_order_deformation.py` example.

Confidence is high for the tested linear structural calculations and constrained geometry; limited to the tested configurations for coupled numerical repeatability; unestablished for physical thrust/torque prediction with this new structural model.


## Lightweight atlas workflow

> Historical (17 November 2026): the separate atlas folder, `span_comparison.html` and the ZIP described here were replaced by the atlas on the website (`atlas/data/`, *Elasticity effects* tab). Kept for provenance.

The existing exported atlas now links to **Spanwise elasticity**. The comparison page embeds its data and runs offline. Independent checkboxes show chordwise-only reruns, span-flex reruns, and optionally uncertain/unverified cases. Connections compare identical outlines. The source atlas value is kept separately from the matched rerun.

`python -m wingstudy.span_atlas` reruns the four recorded category winners for **0.5 mm bare sheet** (three campaign frequencies plus the sweep winner), caching their full records under `outputs/elastic/span_atlas`. It checks both models at 8 x 4 panels, 50 steps per cycle with two stabilization settings and no automatic refinement; a targeted recheck at 100 steps per cycle is available with `--recheck`, and actual settings are recorded. Failed screening records are retained in the screening subfolder for this batch. It publishes compact results into the supplied Elastic_Wing_Atlas folder as each comparison completes. This is a focused cohort, not every thickness or rod configuration.

For future GUI campaigns use **Save span-flex results to atlas**, or `python -m wingstudy.span_atlas --campaign <campaign-folder>`. This exports completed case summaries and final-cycle traces; native solver histories and animations stay in the full program folder. Campaign imports without matched baselines are clearly labeled not compared. The original all-wing map stays unchanged; span-flex points are in the dedicated comparison view.

The atlas folder remains portable. Share `span_comparison.html` alone for the small comparison (the return link needs the rest of the atlas), or the atlas folder for all previous results and media. This source distribution does not include the collaborator's original elastic campaign SQLite databases; the initial cohort therefore comes from the exported atlas's embedded winner records.

## Numerical check results (17 November 2026)

Wing 7657, 0.5 mm bare sheet, 1 Hz, 0.5 m/s, four cycles: 16 span panels and dt=0.0025 s produced mean thrust 0.6105–0.6107 N, peak fluid root torque 0.36875–0.36884 N m, tip travel amplitude 127.30–127.32 mm, and maximum span slope 43.85–43.86 degrees at stabilization factors 0.7 and 1.0. The 16-panel dt=0.005 s result was about 0.6015 N / 0.3656 N m, a 1.5% thrust change on time refinement. The 8-to-16 panel change at dt=0.005 s was about 2% in thrust. Factor 0.35 at coarse dt and factor 0.5 at the finest dt were unstable and are retained as failures. These checks support numerical repeatability for this case, not physical validation or convergence for every planform.

17 new structural, geometry and identity checks passed, alongside the three existing legacy elastic regressions. Native side/front/top animation is saved under `outputs/elastic/span_validation/bare_0p5mm_animation`.

The standalone `Spanwise_Comparison.zip` includes the interactive comparison, compact JSON and a short README. The GUI export action and model toggles were checked; no solver is required to read this export.

### Atlas winner rerun outcomes

Four 0.5 mm bare-sheet category winners were rerun. Two matched pairs passed stabilization agreement (0.75 Hz campaign winner and 1 Hz sweep winner). The 1 Hz campaign pair has only one settled factor per model and remains unverified; the 1.25 Hz span-flex case is unresolved. All are retained, with uncertain results excluded from the default plot. Screening used 8 x 4 panels; targeted rechecks used 100 time steps/cycle. This is not a mesh-convergence qualification for the four winners.
