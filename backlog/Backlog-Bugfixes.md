# Open Bugs

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md) (sections `### Bugfix …` / regressions)

Feature roadmap → [Backlog.md](Backlog.md)

## Classification

**Here:** Prod deviation, regression (`xfail`), known misbehavior, review with clear fix/remove outcome.
**Not here:** New behavior, UX, models, research — see feature backlog in `Backlog.md`.
**Versioning:** completed bugfixes → **PATCH** only in `version.py` (no minor bump).

### `## Bugfix Verifications Pending`

Fix is **implemented** (code + tests + optional PATCH in `version.py`), but **prod/live acceptance** is still pending.

- Move item from the thematic bugfix chapter here once the fix is committed — **not** directly to `Backlog-Erledigt.md`.
- Briefly note what changed (commit/version) if helpful.
- After successful verification: remove from this chapter → `Backlog-Erledigt.md` (`### Bugfix …`) with `- [x]`.
- If verification fails: return to open bugfix chapter or formulate follow-up; document PATCH if applicable, but do not archive as done.


## Bugfix Verifications Pending (Do not remove this chapter — even if empty) + Testing Todos

- [ ] **EV still connected after charge → re-planned full charge** — config-path house-profile EVs now honor Ist-SOC complete; `plug_cycle_fulfilled` latch survives deadline purge while plugged (cleared on unplug). Real SOC (or equivalent complete signal) remains necessary when Earnie has no fulfillment memory and Rest-/Ist-SOC stay stuck at plug-in values. Tests: `tests/test_charging_session.py`, `tests/test_charging_context.py::TestPluggedInChargeComplete`. Live verify: finish a session, stay plugged past FertigUm → no new EV target.
- [ ] **SoC spike at SA₁ (night grid charge → forced dump)** — Live hourly MPC charged before sunrise SOC_min for later EV, then re-opt moved EV and forced export; fix: PV-only charge through sunrise slot (`_add_pv_only_charge_through_sunrise`). Tests: `tests/test_milp_sunrise_soc.py`. Live: Chart 1 SoC near SA₁ with overnight EV — no 19→50→10 jump.
- [ ] **EV absent daytime plan after overnight ready_by** — dumps `debug_dump_20260731_075323` / `091219`: FertigUm kept overnight open past config `ready_by` → daytime Smart plan while unplugged. Also ports config-path Ist-SOC (not `daily_rest_soc`) when plugged. Fix in `hotfix/2.3.2` (`v2.3.2`): `resolve_absent_availability` + `_config_path_apply_live_ist_soc`. Tests: `TestAbsentAvailability`, `TestLoxoneAbsentForecast`, `TestPluggedInChargeComplete`. Live verify: unplugged daytime → no EV plan before next `car_available_from`; plugged @ ~99% Ist-SOC → no full replan.


## New Bugs (Do not remove this chapter — even if empty)

## Organizational Changes - no bugs (but still no development issue)
