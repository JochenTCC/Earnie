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

- [ ] **`grid_fees.json` gets `earnie_data_model` stamped by config-pack export / import** — fix implemented (2026-10-16, ConfigMigration P2); acceptance pending
  - Export (`build_config_pack_bytes`) and `write_json_dict` no longer stamp `earnie_data_model` onto `grid_fees.json`; import already skipped stamp. Existing stamped keys are not stripped on load (migration step later).
  - Tests: `tests/test_config_pack_and_paths.py` round trip; `tests/test_json_io.py` (`test_write_json_dict_does_not_stamp_grid_fees`).

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

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
