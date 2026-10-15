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

- [ ] **Heat storage: Live never applied solar-collector heat** — fix implemented (2026-10-14); NAS productive acceptance pending
  - Symptom: heat storage appeared never to collect energy via the solar collector on NAS productive.
  - Cause: Live callers (`_live_store_flex_overlay`, horizon need, observability) never passed `solar_forecast_kw`; planner defaulted to zeros. Year-sim already injected collector yield.
  - Fix: `resolve_live_collector_solar_kw` (Open-Meteo archive DOY/hour) auto-fills when callers omit solar; wired in `plan_live_store_for_thermal_consumer`.
  - Tests: **add regression test after live verification** (mock sunny midday profile; assert store T rises above setpoint when `solar_forecast_kw=None` and `solar_thermal_area_m2` > 0).

- [ ] **Daemon wait loop drifts ~1 min behind the quarter-hour tick** — fix implemented (2026-10-15); NAS productive acceptance pending
  - Symptom (NAS productive `earnie.log`): regular cycles started 66–73 s after the tick (e.g. tick 09:15, `Live-Abfrage gestartet` 09:16:13), so setpoints landed ~1 min late every slot.
  - Cause: `wait_for_optimize_or_timeout` (`integrations/loxone_request_http.py`) decremented `remaining` only by the sleep chunk; time spent in `on_poll` (`touch_daemon_heartbeat` + `power_interval_sampler.tick`, loads the ~190 KB state JSON each poll) extended the wait (~900 polls × ~0.07–0.1 s ≈ 1 min).
  - Fix: wait against a monotonic deadline (`clock_fn`, default `time.monotonic`); early wake via Earnie_Request_Optimize unchanged. `wait_until_next_run` passes `clock_fn` through.
  - Tests: `tests/test_loxone_request_http.py` (`test_wait_on_poll_cost_does_not_extend_total_wait`, `test_wait_early_wake_with_fake_clock`).
  - Live verification: `wake_delay_sec` in `runtime/cycle_stats.jsonl` (EarlyStart P0) should drop to ~0–2 s for `quarter_hour` cycles.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] Debug dump to triage: `debug-dumps/debug_dump_20261014_221410` (incomplete note — fill symptom / expected)
- [ ] **Daemon wait loop drifts ~1 min behind the quarter-hour tick** (found 2026-10-15 in NAS productive `earnie.log`)
  - Symptom: regular cycles start 66–73 s after the tick (e.g. tick 09:15, `Live-Abfrage gestartet` 09:16:13), so setpoints land ~1 min later than necessary every slot.
  - Suspected cause: `integrations/loxone_request_http.py` `wait_for_optimize_or_timeout` subtracts only the sleep chunk from `remaining`, not the time spent in `on_poll` (`touch_daemon_heartbeat` + `power_interval_sampler.tick`, which loads the ~190 KB state JSON every poll). ~600 polls per wait → ~1 min drift.
  - Fix idea: wait against a monotonic deadline instead of a decremented counter. Confirm first with `wake_delay_sec` in `runtime/cycle_stats.jsonl` (EarlyStart P0).

## Minor changes (no bugs - do not remove this chapter - even if empty)

- [ ] Übernimm im HA-Addon die Positionsdaten aus HA, wenn möglich

## Document Review Findings (Do not remove this chapter — even if empty)
