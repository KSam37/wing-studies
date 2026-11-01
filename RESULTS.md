# Saved wing results

Open **Lambda comparison** from the app header or Results page, or visit
http://127.0.0.1:8766/comparison while Wing Studies is running.

The primary comparison contains three completed independent-seed searches:

| Lambda | Evaluated designs | New solves | Cached | Accepted changes |
|---|---:|---:|---:|---:|
| 0.75 | 347 | 259 | 88 | 151 |
| 1.25 | 333 | 255 | 78 | 121 |
| 1.75 | 361 | 262 | 99 | 181 |

There are 879 distinct simulation identities across these 1,041 occurrences.
Each search includes 15 independent lineages: five seed families at three
starting spans. Shared settings and fixed seed-derived objective scales match.
Scores increase along every accepted path; that is not a global convergence test.

Use the lambda checkboxes, torque minimum/maximum and torque-band width to
compare the data. Each occupied band selects the greatest observed mean thrust,
breaking equal-thrust ties by smaller peak torque. Click a wing or table row for
actual span, chord widths, global case number, original native plots and SVGs.
The step plot answers a different question: greatest observed thrust at or below
each torque budget. It does not interpolate new simulated results.

All evaluated trials are available by default, because a trial rejected by its
lambda score may be valuable in another torque band. Switch to accepted evolution
or final designs to see only those subsets. Select a seed lineage to play its
geometry evolution or export its recorded GIF. Native flapping animations remain
separate. Figures export as 600 dpi PNG with source CSV, methods and a summary.

The score is `S = T/Tref - lambda*M/Mref`, using final-cycle mean single-wing
thrust and peak absolute root roll moment. Tref = 11.5995490753 N and Mref =
14.4132303436 N m. There is no search-time torque ceiling. Larger lambda penalizes
torque more strongly. Thrust/torque is not an energy-efficiency measure.

The **New** master contains the three primary studies and future runs. The
**Old** master contains 20 substantial earlier studies, labeled by date, name,
successful case count and partial completion where relevant. On 2026-11-01,
31 small/test/failed study directories were deleted with user authorization.
Before deletion, 69 catalog origins were redirected to retained result copies.
Retained global case numbers and signatures were preserved. Study paths are not
renamed, so existing file links continue to work. Organization metadata lives in
`outputs/study_organization.json`; catalog metadata backups and the cleanup
record live under `outputs/maintenance/organization/`.

These are rigid UVLM screening results. The saved root torque excludes wing
inertia and drivetrain conversion. Repeatable cycles are not a mesh/time-step/
wake-convergence test. Finalists need those checks and physical validation before
claiming an optimal or hardware-qualified design.
