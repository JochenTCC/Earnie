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
- [ ] **Missing next-month `monthly_table` rate** — pricing falls back to same month prior year, else prior calendar month (log warning); Szenarienkonfigurator warns + appends Cent/kWh into `earnie_env/config/tariffs.json`; `reload_config` / `reinit_config` reread disk. Tests: `tests/test_tariff_pricing.py`, `tests/test_feed_in_prices.py`, `tests/test_append_monthly_rate.py`. Live verify: select monthly export without next month → hint + save → next `main` cycle uses new row.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] Loxberry Plugin - Button "Stop" is not working - manual stop works and Container-Status shows this

## Organizational Changes - no bugs (but still no development issue)
