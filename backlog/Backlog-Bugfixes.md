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

- [ ] **Live day-ahead prices re-fetched from ENTSO-E every cycle** — fix implemented (2026-10-15); NAS productive acceptance pending
  - Symptom (NAS productive `earnie.log`, 2026-10-15): `ENTSO-E AT request …` in every cycle, never `Using cached day-ahead`; `day_ahead_fetch` event in every `cycle_stats.jsonl` record; 4–17 s per cycle in `prices_matrix`.
  - Cause: `_try_cached_live` required the cache to cover the full planning window; the sunrise horizon reaches into D+2 (e.g. 17.10. 07:30), but day-ahead prices exist at most up to D+1 23:45, so coverage always failed.
  - Fix: fresh-cache coverage is checked up to `published_cover_end(window_end, now)` (last quarter-hour of `last_day_ahead_calendar_date(now)`); a cache without tomorrow after the publish hour still refetches. Outage path unchanged.
  - Tests: `tests/test_live_price_cache.py` (`test_published_cover_end_caps_window_at_last_day_ahead_day`, `test_sunrise_window_into_d2_uses_cache_once_tomorrow_is_published`, `test_cache_without_tomorrow_still_refetches_after_publish`).
  - Live verification: `Using cached day-ahead` in most cycles; `day_ahead_fetch` only around the auction publish (~12:45–13:00) and after restarts.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **`grid_fees.json` gets `earnie_data_model` stamped by config-pack export / import** (found 2026-10-16 while planning the config migration, [Config-Migration-Draft.md](Config-Migration-Draft.md) §2 / §3.7)
  - Symptom: the seed `share/config/grid_fees.json` and the bootstrap site copy carry no version key; after a config-pack export + import the site copy carries `earnie_data_model: 4`. The same file therefore exists in two states, depending on the install's history.
  - Cause: `build_config_pack_bytes()` calls `stamp_data_model()` on every pack JSON (`runtime_store/config_pack.py:60`); `_migrate_and_validate_pack_docs()` stamps + `ensure_compatible()` on import, and `write_json_dict()` (`settings/json_io.py:56`) stamps every file it writes — `grid_fees.json` is a tariff-domain catalog, not an Earnie data-model file.
  - Impact: none inside Earnie (`data/grid_fees.normalize_grid_fee_catalog` ignores unknown root keys). Edbert's strict loader (`edbert/gridfee.py` `parse_grid_fee_catalog`, allowed root keys `description` / `rule_sets` / `areas`) rejects the stamped file — matters for the Edbert CLI `--grid-catalog` today and for the Edbert integration in Version 2.8.
  - Fix direction: exclude `grid_fees.json` from `earnie_data_model` stamping and from `ensure_compatible()` in export, import and `write_json_dict`; strip an existing `earnie_data_model` from the site copy only via the planned migration step (no silent strip on load). The file's own format version (`tariff_format`, aligned with Edbert) comes with the config migration item, not with this fix.
  - Tests: export / import round trip leaves `grid_fees.json` without `earnie_data_model`; `write_json_dict` on a `grid_fees.json` path does not stamp.


## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
