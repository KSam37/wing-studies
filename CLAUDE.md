# Wing Studies v1.5 — start here

Read [V1_5_SYSTEM_GUIDE.md](V1_5_SYSTEM_GUIDE.md) before editing or running studies. It is the current project handoff, dated 19 November 2026.

## Working rules

- This v1.5 application differs from the older outer Ptera app. Confirm cwd before running anything.
- Analyze underwater wings using mean single-wing thrust versus peak absolute fluid root torque. Motor/gearbox torque is outside this model.
- Use `wingstudy/elastic_atlas.html` and its existing navigation, theme, filters, tooltips and viewer. Do not create another results app.
- Preserve geometry, material, rod, motion and numerical provenance. Never silently change settings or merge structural model identities.
- Nominal fallback is authorized for missing originals: 8 × 4 panels, 50 steps/cycle, four cycles. Label it; do not claim it reproduces unknown original settings exactly.
- Current selection: global observed frontier across material/rod models, separately per frequency; maximum thrust per 0.01 N m band. No simulation torque ceiling. Preserve selected thickness and rod.
- The 578-case batch and twelve highlight animation replays are complete. Inspect progress before restarting.
- `verified` means numerical settling and stabilization agreement, not mesh convergence or experimental validation. Failures are not zero-valued results.
- Keep environments outside OneDrive; reuse registered launchers. Check the actual installed Ptera import path before changing solver code.
- This folder is the `KSam37/wing-studies` Git repository. The working copy lives in OneDrive by the owner's choice; keep the Python environment and numba cache in `%LOCALAPPDATA%\WingStudies` (the launchers do this), and treat GitHub as the code backup. `outputs/` and the legacy master catalogs stay local and are never pushed; the template cases the elastic studies need are in `wingstudy/data/template_cases/`. A restructure is in progress: see `RESTRUCTURE_PLAN.md`.
- Prefer bounded diagnostics before large reruns. Do not increase damping or deformation guards merely to obtain passing results.

## First five minutes

1. Read the system guide, especially model distinctions, current results and known issues.
2. Inspect `outputs/elastic/frontiers/preserved-0p01/plan.json` and `progress.json`.
3. Open `../Elastic_Wing_Atlas/Elastic_Wing_Atlas/index.html`.
4. `python -m wingstudy.span_frontier` checks remaining count without solving; `--run` starts computation.
5. Test changes appropriately and report what was actually checked.

Existing README files mix historical workflows. Follow current user instructions, actual code and saved plans; do not treat every historical paragraph as an active requirement. Refresh changing facts before reporting them.
