## Authorized nominal fallback — 18 November 2026

The user approved documented nominal settings for missing original details. The preserved-material frontier batch uses 8 × 4 panels, 50 steps/cycle (dt = 1/(50 f)), and four cycles wherever the source run settings are absent. Original thickness and the 5 mm OD / 3 mm ID rod configuration are preserved. Nominal and geometry-rounding provenance is saved per case and shown in the atlas. Both chordwise and spanwise reruns use the same settings; no automatic refinement. Resume the prepared plan with Run Frontier Span Study.cmd. The missing-database restriction described below is superseded for this authorized batch.

# Current batch: original material and original numerics

Updated selection: one global thrust/torque frontier per frequency across all 1.5 campaign models, retaining the maximum-thrust point in each 0.01 N m torque band. No torque ceiling. This selects 578 elastic wings and 131 rigid references. Elastic reruns preserve original thickness, material, rod and source run settings. Rigid cases are references because no finite sheet stiffness is specified.

The plan is outputs/elastic/frontiers/preserved-0p01/plan.json. It is prepared but blocked pending the original campaign databases: the supplied lightweight atlas omits actual per-case time step and cycle count (which can differ from nominal settings), and rounds geometry. The runner deliberately refuses to guess these values. Supply the directory containing weekend, rod and sweep campaign subfolders:

    python WingStudy/span_frontier.py --scope preserved --source-root "PATH_TO_CAMPAIGNS" --run --workers 4

The importer reads each original design by key, restores precise chords/span, actual dt/cycles, source mesh, material and rod from its saved plan. There is no automatic time or mesh refinement for this batch. Failed cases remain failures at the requested original settings. Both models use those same numerical settings. The new rod model fixes rod rotation while allowing sheet pitch, as requested; rod-case differences therefore include this structural boundary-condition change, not only added span bending.

The earlier four-case bare-sheet pilot completed with both models verified for all four designs at 100 steps/cycle. It is not part of this exact-original-settings batch. The earlier bare/all plans below are superseded and have not been launched beyond that pilot.

---

# Spanwise frontier study

The selection is the exact observed nondominated frontier: no other eligible wing has at least as much mean thrust and at most as much peak torque, with one strict improvement. Selection is independent for each frequency and source material model. There is no torque ceiling or torque-band thinning. Only verified elastic or settled rigid points are eligible.

Two plans are saved in outputs/elastic/frontiers: bare (714 shapes) and all (3,220 unique geometry/frequency pairs). Both remodel as 0.5 mm carbon sheet without a rod, with finite span bending plus chordwise elasticity. The all plan uses each original material model's frontier to select shapes, not to set the target material. Earlier rigid catalog runs with different conditions are excluded.

Each geometry also receives a matched chordwise-only rerun. The original atlas result is kept separately. Atlas dimensions are rounded to 0.1 mm; full-precision original campaign databases were not included in the supplied export. Motion uses the same template 7657 settings as the original 1.5 campaigns, at each source frequency.

Screening: 8 spanwise by 4 chordwise panels, 100 steps/cycle, four cycles. Two stabilization settings are checked per model. There is no automatic mesh refinement or unrestricted retry. Verification means stabilization agreement and settling, not mesh convergence or experimental validation. Failures remain saved and excluded from default plots.

Run from the configured Python environment:

    python WingStudy/span_frontier.py --scope bare --run --workers 4

Use --scope all for the broader plan. Without --run the command only displays the plan and remaining count. --limit 4 runs a bounded four-case trial. Finished cases are saved immediately and exact matching geometry/frequency/numerics/code records are reused across both plans. Plans refuse to resume if structural code changed. Create a file named STOP inside the selected plan folder to stop scheduling new cases; active cases finish and save. Remove STOP to resume.

progress.json records completed count and a runtime estimate based on completed cases; the early estimate may be biased by easy small wings. The integrated atlas is updated every ten cases and when a batch ends. Native histories stay with the full program. No old studies are modified.

## Atlas comparison view

The Wing map has an independent Spanwise elasticity Off/On filter, in addition to material, frequency and study filters. The spanwise tab defaults to the union of highest-mean-thrust designs under each model at each frequency, selected from cases verified under both models. This yields six highlighted designs for the current batch, without a torque cutoff. All 149 verified matched pairs remain selectable. This selection is conditional on verification and does not imply the unresolved thin bare sheets perform poorly.

Hover shows the physical outline, active span, chord lengths, area, material/rod, frequency, numerical settings, forces, moments and deflection. Dashed lines connect identical wings between models; the table reports thrust and torque percentage changes. Clicking a highlighted design opens paired native animations with side/front/top views. Replays use the exact stored configuration and stabilization factor; output thrust and torque must agree with saved results before media are published. Full histories remain outside the lightweight atlas. The data-only ZIP does not include animation media.
