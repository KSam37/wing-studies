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

The objective and dimensionless lambda weight are defined at the top.
Use the lambda checkboxes, torque minimum/maximum and torque-band width to
compare the data. Each occupied band selects the greatest observed mean thrust separately for each lambda,
breaking equal-thrust ties by smaller peak torque. Click a wing or table row for
actual span, chord widths, global case number, original native plots and SVGs.
The step plot answers a different question: greatest observed thrust at or below
each torque budget. It does not interpolate new simulated results.

All evaluated trials are available by default, because a trial rejected by its
lambda score may be valuable in another torque band. Switch to accepted evolution
or final designs to see only those subsets. Each lambda has a plot containing all 15 seed histories, with shared axes and family colors. Final-shape galleries use a common physical scale. Filter by starting span, or show seed/final shapes versus all accepted shapes.
Select a seed lineage to play its
geometry evolution or export its recorded GIF. Native flapping animations remain
separate. Figures export as 600 dpi PNG with source CSV, methods and a summary.
Use **Export wing design report · PDF** to make a self-contained sharing document with the
current lambda selections, torque limits, band width and design filter. It
uses embedded Times New Roman and shows the highest-thrust shapes in each torque band separately for every selected
lambda on one combined plot, plus the best-under-torque step envelopes. It does
not select an overall winning wing. It includes representative band results, a
typeset delta-score equation and concise methods with traceable case IDs.

The acceptance equation is `deltaS = (Tnew-Tcurrent)/Tref - lambda*(Mnew-Mcurrent)/Mref`, using final-cycle mean single-wing
thrust and peak absolute root roll moment. Current is the last accepted wing; accept
only when deltaS exceeds the saved positive tolerance. Tref = 11.5995490753 N and Mref =
14.4132303436 N m. There is no search-time torque ceiling. Larger lambda penalizes
torque more strongly. Thrust/torque is not an energy-efficiency measure.

Choose **Export wing template STL** in a wing's details or its standard results
row to download a ZIP of numbered print parts and an assembly guide. The cutting
outline extends inward by 2 mm; every chord reinforcement is 2 mm wide. All lines
are 3 mm high. Parts are split only at existing chord centers when needed to fit
the 250 × 250 mm bed, with matching zigzag joints around each shared chord centerline. Tooth depth is
±0.35 mm at approximately 6 mm pitch, leaving at least 0.65 mm of the nominal
1 mm half-rib on each side. The first/last 3 mm stay straight at the cutting rim.
Parts fit 248 × 248 mm to leave bed clearance; slicer brims need extra space.
Import STL files in millimeters at 100% scale and dry-fit the registering teeth and glue as shown. Mating faces have zero designed clearance. One wing is
exported; flip it for the mirror. Saved geometry is preserved, including its tip.
Stored smooth functions use ≤0.02 mm curve flattening; no new smoothing is added.
Untwisted developable bends unfold; unsupported twist reports an error. A single
chord bay too large for the bed requires more chord sections or smaller geometry.
The exporter checks bed fit, closed connected solids, saved dimensions/volume and
the assembled frame before offering the ZIP. Existing Windows installs should
rerun **Setup Windows.cmd** once to install the pinned CAD dependencies.

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

## All retained wings atlas

Open `http://127.0.0.1:8766/atlas` (or the **All tested wings** navigation link). Includes successful New and Old catalog simulations; exact simulation signatures are merged while all source-study memberships remain filterable. The initial view contains every single-wing result, with a spaced sample of silhouettes. The legacy paired-wing study (48 runs) was deleted on 2026-11-02; the remaining catalog contains single-wing simulations only.

Filter to matching saved conditions before attributing performance differences to shape. Color by span, area, taper, fullness or other metrics; switch to density for crowded regions, or normalize silhouette sizes to compare shape independently of display size. Hover/click inspects the actual case. Export saves one 600-dpi PNG and a CSV of every matching case with source identifiers and driving/numerical settings. No simulations or interpolated designs are generated.

## Refine one selected wing

**Refine this wing/shape** now prepares a single-seed coordinate search, using the source lambda and its fixed Tref/Mref when available. Default chord count is at least 16 and otherwise twice the saved active node count minus one (maximum 64). Original nodes are retained and new nodes are linearly inserted, preserving the saved outline rather than fitting a new curve. Default adjustment is half the source’s smallest chord adjustment. Node count, bounds, per-chord adjustments, lambda and simulation budget remain editable before running; rebuild the rows after changing node count or the global adjustment.

The search uses the same accepted-change objective and one half-step rule. Widths change at fixed section positions; a zero outboard suffix may shorten the wing. Native span-panel count increases to cover the added intervals, so refined-seed loads can differ due to mesh resolution. A source without recorded objective scales uses fixed scales from its refined seed. Original studies and every refinement trial remain saved. No simulations start just by clicking Refine.

The atlas supports cursor-centered wheel zoom, pointer dragging to pan, +/− buttons and double-click/Reset view to fit all filtered cases. Focus the plot for keyboard +/−, arrow-key pan and 0/Home reset. Zooming updates the spatial silhouette sample and gallery; all original filtered data remain available on reset. Changing data filters or axes resets the view; color/display changes preserve it. PNG axes and CSV selection follow the current viewport.
