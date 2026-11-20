# Wing Studies: agent entry point

This is the one entry point for AI agents (Claude Code reads it through `CLAUDE.md`). Humans should start with [README.md](README.md). Before you change models or interpret results, read [docs/system-guide.md](docs/system-guide.md). [docs/README.md](docs/README.md) indexes the other documents.

## Working rules

- This folder is the `KSam37/wing-studies` repository. The owner's working copy is `Documents\Coursework\2.S986-Robotics in Fluids\wing-studies`, outside OneDrive. The older OneDrive copies and the outer Ptera app are different programs, so confirm the working directory before you run anything.
- Analyze underwater wings by mean single-wing thrust against peak absolute fluid root torque. Motor and gearbox torque are outside this model.
- Use the existing atlas (`wingstudy/elastic_atlas.html`) with its navigation, theme, filters, tooltips and viewer. Don't create another results app.
- Preserve geometry, material, rod, motion and numerical provenance. Never silently change settings or merge structural model identities.
- A nominal fallback is authorized where the original settings are missing: 8 × 4 panels, 50 steps per cycle, four cycles. Label it as nominal, and don't claim it reproduces the unknown original settings.
- "Verified" means numerical settling plus agreement between stabilization settings. It does not mean mesh convergence or experimental validation. A failed case is a failure, not a zero-valued result.
- Keep Python environments outside OneDrive and reuse the registered launchers (`tools\wingstudy.cmd`). Check the installed Ptera import path before changing solver code.
- `outputs/`, the study cache and the legacy master catalogs stay local and are never pushed.
- Prefer bounded diagnostics to large reruns. Don't increase damping or deformation guards just to make cases pass.
- Old documents in `docs/history/` describe past workflows. Follow the current instructions, the code and the saved plans, and refresh changing facts before you report them.

## Recipe: answering a question with a study

New simulations go through a planned study ([docs/studies.md](docs/studies.md)), not through ad-hoc scripts.

1. **Write the spec.** Run `tools\wingstudy.cmd new <name> --kind evolutionary|geometry-sweep|design-set`, then edit `studies/<id>/spec.json`. Alternatively, import one the user made in the website builder with `tools\wingstudy.cmd import spec.json`. Say which engineering question the study answers in `question`.
2. **Validate.** Run `tools\wingstudy.cmd validate <id>` and fix every problem it lists. Don't loosen the limits in `spec.py` to make a spec pass.
3. **Plan.** Run `tools\wingstudy.cmd plan <id> --workers N` and report the case count and time estimate to the user (for searches, both the typical figure and the maximum).
4. **Propose it.** `tools\wingstudy.cmd publish <id> --spec-only` commits only `studies/<id>/spec.json` on `study/<id>` and opens a PR whose body gives the question, the kind, the plan's numbers and the code identity. Pushing and opening a PR are outward-facing, so do this step only when the user has asked for it.
5. **Stop.** Running the study is the user's decision. Run it yourself only when the user asks you to in this conversation, and only within the size they agreed to. `run` refuses unattended studies estimated at more than 30 minutes unless you pass `--yes`, and you may pass `--yes` only when the user has approved that run.
6. **Publish results** with `tools\wingstudy.cmd publish <id>` once a run the user asked for has finished. This pushes `study/<id>` and opens the results PR.

Agents never merge pull requests, enable auto-merge or push study results to `main`. A person merges each PR after CI passes. Agents also never edit a study that already has results, and never hand-edit `results.json`, `atlas/data/` or `atlas/media/`. [CONTRIBUTING.md](CONTRIBUTING.md) lists every rule that CI enforces.

## Changing code

- Run the tests listed in [docs/system-guide.md §13](docs/system-guide.md#13-verification-and-confidence) that cover your change, and report what you actually ran. CI runs only the standard-library subset, so the solver tests are your job.
- If you change validation rules in `wingstudy/studies/spec.py`, port them to `site/new/spec.js` and run `node tests/builder.test.cjs`.
- If you change the atlas, run `python tools/build_site.py`, `node tests/atlas_ui.test.cjs _site/atlas/index.html` and `python tools/check_site.py _site`.
- A structural-code change changes the code identity, so later studies re-solve. That is intended; don't work around it.
