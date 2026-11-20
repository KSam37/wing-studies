# FAAV Wing Studies

Simulation studies of flapping carbon-fibre wings in water, and an interactive atlas of every wing simulated so far.

**Website:** the landing page, atlas and (soon) study builder are published from this repository with GitHub Pages.

Each study predicts the mean thrust and the peak fluid root torque of one isolated wing. It uses one of three analysis types:

| Analysis type | What is modelled |
|---|---|
| Rigid | The outline flaps as a rigid plate |
| Chordwise elasticity | The sheet twists passively about the leading edge |
| Spanwise + chordwise elasticity | The sheet also bends along the span, with large deflections |

Wings are carbon-fibre sheets of several thicknesses, either bare or with a carbon leading-edge rod. Results are numerical predictions. "Verified" means two stabilization settings agree; it is not experimental validation.

## Repository layout

| Path | Contents |
|---|---|
| `site/` | Landing page source |
| `wingstudy/elastic_atlas.html` | Atlas page template (data is inserted at build time) |
| `atlas/data/` | Atlas data: one file per study plus metadata, catalog and span comparisons |
| `atlas/media/`, `atlas/files/` | Animations (recompressed to one flap cycle), plots and reports |
| `wingstudy/` | The study engine (Python package): geometry, rigid and elastic solvers, campaigns, searches, the atlas exporter. Run tools with `python -m wingstudy <command>` |
| `tools/` | Setup, launchers, site build, media compression, data import |
| `tests/` | Python tests for the package, plus the atlas UI test |
| `docs/history/` | Earlier READMEs and results notes, kept for provenance |

Large raw outputs (full time histories, SQLite catalogs, older rigid studies) stay on the machine that produced them and are never committed. See [RESTRUCTURE_PLAN.md](RESTRUCTURE_PLAN.md) for where the project is heading.

## Viewing the atlas locally

```powershell
python tools/build_site.py
```

Then open `_site/index.html` (landing page) or `_site/atlas/index.html` directly in a browser. No server is needed.

## Running a new study

Simulations run on your own computer. A study builder on the website is planned: it will submit a study spec to this repository for a local run to pick up. Until then:

1. **Set up (Windows).** Clone the repository (`git clone --recurse-submodules https://github.com/KSam37/wing-studies.git`). Then double-click `Setup Windows.cmd`, which installs the Python dependencies and the pinned Ptera solver into `%LOCALAPPDATA%\WingStudies`. That environment is tied to the folder you set up from: after moving the folder, run `Setup Windows.cmd` again. Linux: `tools/setup_linux.sh`.
2. **Run.**
   - `Run Span Flex Study.cmd` opens the campaign dashboard.
   - `Run Frontier Span Study.cmd` resumes the matched chordwise/spanwise frontier rerun.
   - `tools\wingstudy.cmd <command>` runs any tool in the registered environment; `tools\wingstudy.cmd --help` lists the commands (`dashboard`, `frontier`, `spanfree`, `study`, `refine`, `report`, ...). The same commands are `python -m wingstudy <command>` from the repository root.
   - [V1_5_SYSTEM_GUIDE.md](V1_5_SYSTEM_GUIDE.md) explains each workflow and its options.
3. **Publish.** Add results to `atlas/data/` and open a pull request. When it merges, the site rebuilds automatically.

The launchers keep the solver's compiled-function cache in `%LOCALAPPDATA%\WingStudies\numba`. If you run Python directly, set `NUMBA_CACHE_DIR` to a short path: long Windows paths (OneDrive folders, for example) can make the cache fail.

## Tests

```powershell
python -m unittest discover -s tests
```

Run this with the registered Ptera environment's Python. `tools\Check Installation.cmd` does the same after verifying the installation.

## Credits

Aerodynamic loads come from [Ptera Software](https://github.com/camUrban/PteraSoftware) by Cameron Urban and contributors. Ptera is an unsteady vortex-lattice method solver released under the MIT licence. This project pins upstream commit `17a98a10f724a743f1b5f1597579b24edf95cf2d` (see `tools/ptera-source.json`). The water operating point, the chordwise and spanwise structural models, and the study tooling are this project's extensions; they are not part of Ptera.

Developed for MIT 2.S986 Robotics in Fluids.
