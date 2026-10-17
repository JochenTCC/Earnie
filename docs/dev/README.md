# docs/dev — working notes (not maintained documentation)

Developer working documents that are **not** part of the maintained docs:

- `docs/dev/` — open drafts, lab TODO lists, working notes that may still change.
- `docs/dev/done/` — finished epics, research notes, test plans and historical plans. Kept for reference; content reflects the state at the time of writing.

**Excluded** from doc reviews (the temporary review checklist lives here while a quality gate runs and moves to `docs/dev/done/` with the release), the quality / release gate (`.cursor/skills/quality-gate/`) and the doc-editor subagents. Statements here may be outdated — check the code or `docs/workflow/` before relying on them.

New development and design documents are created here and written in **English**. Existing German ones are translated in one pass later.

When a document becomes a maintained reference again, move it to the matching user-doc folder; from then on it is in review scope.

| File | Status |
| --- | --- |
| [bug-regression-release-workflow.md](bug-regression-release-workflow.md) | Draft (2026-10-15) — bug → regression case → release operating model |
| [openems-testing-platform-todo.md](openems-testing-platform-todo.md) | Lab checklist for the OpenEMS stack (referenced by `docker/compose/openems-lab.yml`) |
| [ha-lab-setup.md](ha-lab-setup.md) | Lab stack Earnie + Home Assistant + evcc (`docker/compose/ha-lab.yml`) |
| [openems-lab-setup.md](openems-lab-setup.md) | Lab stack Earnie + OpenEMS (`docker/compose/openems-lab.yml`) |
| [house-sim.md](house-sim.md) | House simulator HouseSim S1–S4 (`house_sim/`) |
| [shadow-mode.md](shadow-mode.md) | Shadow Mode: dev instance fed by production data |
| [done/backtesting-deviation-calendar.md](done/backtesting-deviation-calendar.md) | Feature spec, implemented |
| [done/backtesting-horizon-fixed24h-vs-sunrise.md](done/backtesting-horizon-fixed24h-vs-sunrise.md) | Experiment report (2026-07) |
| [done/backtesting-plausibility-s2-kein-pv-jan-2-7.md](done/backtesting-plausibility-s2-kein-pv-jan-2-7.md) | Research note (2026-07) |
| [done/efm-auto-sync.md](done/efm-auto-sync.md) | Historical research note |
| [done/epic-deploy-user.md](done/epic-deploy-user.md) | Historical draft, never shipped |
| [done/MIGRATION.md](done/MIGRATION.md) | Historical file-structure migration plan (phases P1–P7) |
| [done/se-calculation-test-plan.md](done/se-calculation-test-plan.md) | SE test matrix (results written by `scripts/se_calc_test_compare.py`) |
| [done/smarthome-backend-page.md](done/smarthome-backend-page.md) | Development plan, implemented 2026-08-18 |
| [done/ui-menu-structure.md](done/ui-menu-structure.md) | Historical epic record (Version 1.21) |
