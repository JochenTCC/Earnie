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

- [ ] **Virtual reserve: `advance_reserve_after_slot` / `set_trigger` wiped `target_kwh` to 0** — fix implemented (2026-10-10); live acceptance pending
  - Symptom (Nas productive, Geschirrspüler / `virtual_gs`): dishwasher running, MILP ZWANGSLADEN toward ~11.8% (≈1 kWh refill), but `powerstation_reserves.json` stayed `empty` / `stored_kwh=0` / `target_kwh=0`.
  - Cause: `get_or_init_state(..., target_kwh=0.0)` always overwrote the configured target on every slot advance / trigger latch, so charge credit was capped at `min(0, …)`.
  - Fix: `update_target=False` for advance + trigger; collect/learn still refresh the target.
  - Tests: `tests/test_powerstation_2_7_p.py` (`test_advance_and_trigger_preserve_target_kwh`).
- [ ] **Bug — config pack import accepts incompatible member files** — fix implemented (2026-10-17); live acceptance pending
  - Cause: `_migrate_and_validate_pack_docs` stamped members to current before `ensure_compatible` (would whitewash v1/v2/untagged if validate were bypassed). `validate_migrated_docs` already rejected incompatible members first.
  - Fix: ensure then stamp; `grid_fees.json` still exempt; doc `speichern-laden.md` now states members are checked too.
  - Tests: `tests/test_config_pack_and_paths.py` (`test_config_pack_rejects_v2_member_with_v4_manifest`, `test_migrate_and_validate_ensures_before_stamp`).
- [ ] **Greenfield: unclear Anlagen-PV-Abdeckung checkbox** — fix implemented (2026-10-18); live acceptance pending
  - Cause: `plant.pv_covers_all_inverters` was only an acknowledgement that a flat plant PV total covered every grid-tied inverter; wording was easy to misread as load coverage.
  - Fix: remove the Hauskonfigurator checkbox and the config flag; with several grid-tied inverters that own PV, always derive plant PV as Σ inv/pv · η_inv (flat plant EHAL value ignored); incomplete maps fail loud.
  - Tests: `tests/test_topology_p2.py` (`test_multi_inv_ignores_mapped_plant_and_derives_sum`), `tests/test_pv_attribution.py` (`test_with_attributed_multi_inv_derives_even_when_plant_mapped`).
- [ ] **Greenfield: Netznutzung Messart / Viertelstunden-Zähler UI** — fix implemented (2026-10-18); live acceptance pending
  - Cause: `netznutzung.quarter_hour_meter` and `power_metering` were user toggles; not Earnie's concern.
  - Fix: remove Hauskonfigurator Leistungsmessung select + QH-meter checkbox + migration QH question; always `quarter_hour_meter: true` and `power_metering: unmetered_power` on normalize; catalog still stores both base prices / `requires` for documentation.
  - Tests: `tests/test_grid_fees.py` (`test_snap_applies_even_when_quarter_hour_meter_flag_false_in_raw`, `test_metered_power_raw_is_forced_to_unmetered_base`).

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Greenfield Loxone Dogfood
  - [ ] On page "Szenarienkonfigurator" pre-select House-Profil (there is only one) and also pre-select all existing PVs and Batteries when opened the first time and live scenario has not started to be configured (no selections for none of these fields)

- [ ] "debug-dumps\debug_dump_20261015_222809"

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
