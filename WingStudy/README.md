# Master run catalog (v3.2.0)

Double-click **Run Master Catalog.cmd**, or open **04 Master runs** to browse the compiled catalog, select a ranking metric and direction, find a permanent case number, inspect driving settings, and open the originating study or native output files. Default: single-wing mean thrust divided by peak absolute root roll moment. Historical simulation modes are explicitly separated in the browser.

`outputs/master_runs.xlsx` has exactly two sheets: **Wing parameters** and **Ranked results**. Both carry the permanent case number and originating study/local-case IDs. Parameters include all active sections and entered chords, waveform, frequency, amplitude, speed, fluid properties, time step, cycles, mesh, wake and provenance. Run occurrences retain every study/case location, including reuse. Results include metric/order dropdowns in B3/D3; changing them updates the rank and ranking value. Sort Rank ascending to reorder the Excel rows, or use the browser's automatic ordering. The workbook's Open interactive catalog / Open case links require the local app to be running. Starting the app refreshes these links to its actual port.

Before a new case runs, its active geometry, motion, fluid and numerical settings plus actual solver code and dependency identity are compared with the persistent catalog. Case names, study names, case budget and omitted outboard sections do not cause another simulation. A verified, successful case with all seven original files and compatible raw history is reused; its case number remains unchanged. Native PNGs and animation are copied, the raw history is associated with the new local case, and tracing SVGs are regenerated with the new local ID. Missing, failed, incomplete or unverifiable results never suppress a fresh solve. Changes to driving conditions, mesh, time step, wake or solver identity create a different case number.

Existing studies are imported without rewriting their historical files. Archived release source and native package hashes are checked before trusting old runs for reuse. Unverified legacy cases remain documented but are not reused. Pending/interrupted cases remain listed and unranked until numeric results exist. The default worksheet ranking does not invent zero outputs for missing data.

The small `outputs/master_runs.sqlite3` file is the durable catalog; keep it with the studies when moving/sharing results. The Excel workbook is its generated view, not an editable simulation-input database. It refreshes during/after runs and through Update master Excel. If Excel holds the workbook open, simulations and records continue; close Excel and click Update master Excel to catch up. Exporting the workbook never requires Excel, Node, or extra Python packages on your partner's computer.

# Trailing zero chords and duplicate designs (v3.0.1)

Chord-node ranges and custom wings accept zero widths only in an outboard suffix. For example, 0.10 / 0.08 / 0 / 0 is allowed; 0.10 / 0 / 0.08 / 0 is invalid. At least two positive root-to-tip sections are needed. Zero means an absent section, not a pointed zero-chord tip: the active wing ends at the last positive station. Ptera receives only positive-width sections, without epsilon replacements or zero-area panels.

The original reference node positions are retained; surviving sections are not stretched to the original tip. Effective span, area, aspect ratio, moment normalization, previews and fabrication SVGs follow the shortened wing. Entered chords remain in requested_sections and chord_N_m fields, including zeros.

Each study merges exact duplicate active section definitions before running. Names and omitted outboard section coordinates do not cause another simulation. input_aliases retains the entered designs. Positive ranges are uniqued before enumeration; invalid zero patterns are pruned during counting and generation. Version 3.2.0 also reuses verified completed results across studies when all physical and solver settings match.

# Isolated single-wing studies (v3.0.0)

New runs simulate exactly one unmirrored main wing, with its root and airplane moment reference at the origin. Native Ptera force, moment, coefficient plots and animation now describe that one wing. The native roll moment is the physical root fluid moment; it no longer cancels against another wing.

Estimated two-wing thrust is twice isolated-wing thrust, recorded in the raw histories, summary CSV and ranked GUI. This estimate omits interaction between wings. The objective remains final-cycle mean single-wing thrust / peak absolute root roll moment. Fluid moment excludes wing inertia and drivetrain loads.

Existing paired-wing studies remain readable and are labeled as legacy runs. Their original plots are unchanged; rerun the geometry to obtain isolated-wing plots. Comparisons cannot mix the two simulation modes. Static tails are disabled for new isolated-wing studies.

Geometry inputs retain their prior dimensions: reference total span and root gap define the actual single-wing root-to-tip length as (reference span - gap) / 2. No wing is resized by this change. New result area and aspect ratio describe the simulated wing alone. Left and right fabrication SVGs are still exported, even though only one wing is simulated.

## Search and objective

Geometry sweep mode is now **Search chord-length combinations**. Set a fixed total span and 2–64 equally spaced root-to-tip chord nodes. Each node has its own minimum chord (m), maximum chord (m), and inclusive linspace sample count. One sample requires matching min/max. Every admissible combination is solved. The optional non-increasing checkbox enforces each subsequent chord <= the preceding chord; equal chords are allowed. A dynamic-programming count and prefix pruning avoid enumerating rejected Cartesian combinations. Case budget applies to admitted shapes, before optional fabrication bounds.

Leading-edge sweep = 0°, incidence = 0°, and tail off by default. Sweep and incidence can be edited as study constants. The tail remains an optional fixed design. Span includes the fixed hinge gap; exposed half-span L = (span - gap)/2. At least one span panel per chord interval is required. There is no imposed span or chord maximum. Geometry is piecewise linear between the nodes. Manual custom wings remain available with section location, width, sweep, pitch and dihedral controls.

The objective is **single physical right-wing final-cycle mean forward thrust / peak absolute roll moment about that wing's hinge**, in 1/m. Native panel thrust is summed for that wing. Native moments are shifted to its physical hinge before projection onto the flap axis; the canceled whole-airplane roll moment is never used. Both mirrored wings remain in the flow model to retain interaction. The left wing's individual forces/moment are saved for symmetry checks. Positive mean thrust and a moment above 1e-9 N m are required for a valid ratio; numerical zero never gives an infinite winner. Rankings require repeatable force and physical-root-moment cycles by default. Peak moments are sampled and need delta-time convergence. Tail thrust is excluded from the numerator even if a tail is enabled; its aerodynamic interaction remains.

There is **no shared-motor torque screen, gear-ratio model, linkage model, or motor constraint**. Those obsolete active paths were removed. The ratio is a shape-selection metric, not propulsive efficiency or motor qualification. RMS hinge moment and the dimensionless companion L*T/M are also reported.

## Span and scaling

Span is fixed across a shape grid. T/M has units 1/m, so even an ideally similar smaller wing would score higher dimensionally. L*T/M removes this dimensional bias, but does not prove hydrodynamic scale invariance. At matching velocity fields and force coefficients, geometric scaling s gives T proportional to s^2 and M proportional to s^3. At fixed flapping frequency, however, changing span changes wing velocity and reduced frequency; water viscosity also changes Reynolds number. Re-run scaled finalists with appropriate operating conditions; do not treat a dimensional scaling law as a validated flow prediction. Shape rankings across different spans or dynamics need this judgment.

## Motion, water and timing

Frequency, half-stroke amplitude, forward speed, water properties, waveform, time step, cycles, mesh and wake settings are constants across a study. Water defaults to approximately 20 °C fresh water: rho = 998.2 kg/m^3; kinematic viscosity nu = 1.004e-6 m^2/s. Stock Ptera requires positive forward speed; there is no zero-speed adapter.

The default flap is sinusoidal. Custom motion accepts 4–40 phase/relative-angle pairs, beginning 0,0 and ending 1,0. Phase increases strictly over one cycle. A periodic cubic spline joins the data with continuous angle/velocity/acceleration. The curve is normalized by its exact half-range and scaled to the half-stroke amplitude. Interpolation can overshoot and asymmetric curves can have an offset: inspect the actual angle range in the preview. The left wing mirrors the right; an enabled tail remains static. Motion is prescribed, not derived from a drivetrain. Refine time steps for fast strokes and reversals.

Preview runtime is a rough range calibrated from similar local completed cases. Once cases finish, remaining time updates from recent measured case durations. Timing includes native plots and animation. No matching history means 'calibrating first case'; machine load and native wake behavior can change runtime. More cycles/panels, smaller delta time and a full free wake increase cost. Prescribed wake and finite wake retention offer faster screening but require convergence checks for finalists.

For efficiency, geometry is pruned before creation and the aggregate ranking PNG is rendered once at the end rather than after each case. Shared CSV/results and ETA update after each case. Cases remain sequential to avoid saturating memory with growing wakes. Use coarse grids first, then narrow intervals around promising shapes; this is exhaustive optimization of a sampled grid, not a guaranteed continuous/global optimum.

## Results and files

Each case keeps four stock Ptera time-history PNGs, a WebP animation, and separate left/right full-scale SVG outlines. Native plot styling is unchanged. These total-model plots are reference solver outputs; the objective's single-wing loads are in the raw shared CSV. The per-case folder still contains seven files. Planar/bent developable strips unfold into cutting patterns; twist or overlap falls back to a labeled projection. SVG units are mm at 1:1 with a 100 mm scale check; no seam or attachment allowances. Print at 100% and measure the bar.

The comparison folder contains shared `time_histories.csv`, `top_performers.csv` (top ten eligible ratios), and `shape_comparison.png` + `.csv` (rankings, force/moment trade-off and all recorded shape inputs). Summary CSV and JSON retain every case, its chord node values, waveform and numerical settings. Two- or three-axis heatmaps use selected chord lengths; color defaults to thrust/roll ratio. Maximum-over-unchecked mode identifies the winning tested shape per cell; exact-slice mode holds other inputs fixed. No interpolation is used. Every exported comparison CSV retains the full winning chord vector. Custom plots are PNG only with serif type and 600 dpi. Native case plots keep Ptera's default styling.

The results GUI shows the best eligible ratio, the winning wing geometry, all chord inputs, single-wing force/moment values, RMS moment, size-normalized score, and settling checks. Old studies stay readable, but lack the new single-wing force/objective fields and must be rerun; old net moments or motor estimates are not silently substituted. Legacy geometry sweep configuration is replaced by the new chord editor on import: review the ranges before running. Original files are retained.

## Model confidence

Stock Ptera 5.1.0 rigid prescribed-motion UVLM is unchanged. Forces use named induced drag/thrust and wind-axis loads; the root moment uses the physical flap axis. The model omits membrane deformation/stiffness, skin friction, separated flow, body drag, free flight and actual drivetrain dynamics. Settling is distinct from mesh/time-step/wake convergence and tank validation. Engineering tests cover grid cardinality/pruning, native geometry/symmetry, hinge reference shifts, objective arithmetic and zero handling, scaling dimensions, ratio-based winner selection, heatmap provenance, ETA and portable relocation. Agreement is software/model evidence, not prototype qualification.


## 3D wing-shape landscape (v2.1)

Results now includes a rotatable plot with wing area (m²), single-wing mean thrust (N) and single-wing mean thrust / peak |roll moment| (1/m) on its three axes. Every measured case is represented by its actual neutral top-view wing-outline thumbnail rather than a circular marker. The single-wing planform is normalized in display size; area and thrust describe one isolated wing in new runs. Legacy results retain their paired definitions. Thumbnail size is adjustable; drag to rotate, wheel to zoom and click a wing to inspect its values and chords. Coincident measurements can be selected individually. Repeatability filtering is explicit. Existing chord-axis heatmaps remain available.

Smooth interpolation can be toggled. With independent area/thrust samples, a bounded cubic Bezier surface using limited Clough-Tocher gradient estimates is densely sampled inside the measured convex hull, with no extrapolation or triangle outlines. Collinear samples use a cubic curve; one location shows points only. Two locations cannot establish a curved thrust trend. Each patch stays within its measured corner values and neighboring patches share continuous edges; interpolation is an estimate and never changes measured rankings or adds CSV rows. All simulated wing markers remain visible.

Different chord vectors can have the same area and thrust. All such measured wings are retained at their actual z values. Interpolation uses the highest sampled ratio at each duplicate coordinate, explicitly labeled an upper envelope. The mesh is a descriptive estimate and cannot identify a unique new wing shape or certify an optimum.

A new study automatically saves one landscape PNG/CSV pair at completion. The Results button can regenerate the interactive display and exports from existing v2 single-wing results without rerunning Ptera. The measured-only CSV includes area, aspect ratio, ratio, physical force/moment values, complete section definitions, repeatability and whether a case defines an interpolation vertex. Each wing icon remains a vector marker in the GUI/plot; no extra per-case thumbnail files are created. The existing seven per-case files are unchanged.


## Standard comparison: ranked wing list (v2.1.1)

The default results view is now a list sorted by thrust/moment, with a neutral planform picture for every displayed case and its ratio, mean thrust, peak absolute hinge moment, chord lengths and status. The repeatability filter is retained. Winner details and the 3D landscape are optional collapsed views. No separate thumbnail image files are created.

The standard comparison PNG is also a ranked list with a wing picture per row, rather than a bar/scatter chart. It includes all valid ratios in descending order and flags unsettled cases. Large exports paginate at 25 wings per PNG to keep image memory bounded; the CSV retains all measured rows and eligible ranks. The Save ranked list button updates the export for an existing completed or stopped study. Per-case native solver plots and animations are unchanged.

### Filter compiled results (3.2.0)

In **Master runs**, select studies (Ctrl-click for several), global case numbers, geometry/performance ranges, and driving/solver conditions. Empty ranges impose no limit; endpoints are inclusive. Cases reused in a selected study are included. Choose the ranking and show the top 25, 50 (default), 100, or all matching cases. The list and 3D comparison share that selection; pagination does not limit the plot. Invalid or incomplete results cannot enter the 3D plot. Changing a filter clears the old plot and download links until regenerated.

**Generate filtered 3D plot + PNG/CSV** exports only selected measured cases, with permanent case numbers, source study/local case IDs, and driving/solver settings in the CSV. Exports are stored under `outputs/studies/compiled-view-<selection hash>/comparisons/`; repeating a selection reuses that comparison location, without another simulation. Different driving/solver conditions or unverified provenance disable interpolation while keeping measured wings visible. All original runs and the complete master workbook are retained.

### Excel export repair (3.2.1)

The exporter writes worksheet elements in the order required by Excel, placing filters, merges, validation and hyperlinks before page settings. This prevents Excel from discarding the two worksheet parts on open. Original study records are unchanged. Compact release identity files in `outputs/provenance` replace the need to keep obsolete application ZIPs for historical reuse verification.
