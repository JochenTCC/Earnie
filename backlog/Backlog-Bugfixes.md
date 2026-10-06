# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / `### Document Review …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome; plus `## Document Review Findings` (docs corrections).
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump). Docs-only findings: no version bump unless asked.
**Document Review Findings:** After the agent corrects the docs → move straight to `Backlog-Erledigt.md` (skip Verifications Pending). See skill `doc-review-findings`.

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **2.7.h — productive Earnie dogfood** (code archived in Erledigt; not yet verified live)
  - Physical `role: standby_backup` + `set_ess_source_select` (EcoFlow Delta 3 / Loxone Merker `Earnie_Speicher_Quellenwahl` → HA `switch.*_grid_bypass`): price-driven grid vs battery island flips, reserve sizing, charge in cheap slots
  - After successful live check: remove this item; add **Verified live** note on the **2.7.h** Erledigt entry

- [ ] Consumer editor: removed redundant "Standard-Laufzeit"; advice/reserve runtime = `schedule.duration_h` only (dropped persisted `appliance_recommendation.default_runtime_h`)

- [ ] Virtual and physical powerstations shall not be selectable in Scenario-Config (not only warning)
  - Scenario catalog filters via `scenario_selectable_batteries` (`house_config/powerstation.py` → `_load_scenario_catalogs`); regression `test_scenario_selectable_batteries_excludes_virtual_and_physical_ps`

- [ ] **Physical powerstation ESS writes fall back to the house battery's plant-flat entity** — fix implemented (2026-10-06); live acceptance pending before **2.7.h** dogfood with limits
  - `optimizer/powerstation_live.py`: no plant-flat remap for charge/discharge (HA + Loxone); explicit exception only for `set_ess_source_select` (EcoFlow bridge); missing binding → skip + `runtime/ehal_write_error.json`
  - Docs: `docs/konfiguration/batterie-pv.md`; regression: `tests/test_powerstation_2_7_h.py` (`test_ha_charge_does_not_remap_to_house_battery`, Loxone charge isolation, HA source_select plant-flat)

## New Bugs (Do not remove this chapter — even if empty)

- [ ] 2026-10-06 05:37:40 [WARNING] (main:199) - SoC-Lesung korrigiert: Miniserver 11.0% → 100.0% (Integration aus 100.0%, Batterie 0.52 kW).  --> Why this?
- [ ] "debug-dumps\debug_dump_20260930_182138"


## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
