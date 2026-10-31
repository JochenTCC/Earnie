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

- [ ] **[release/2.7] Forced-charge deviation (`battery_charge_energy_below_ratio`): absolute shortfall threshold.** The rule fired on the ratio alone (delivered slot energy < `params.max_ratio` × target energy), so small Soll amounts raised false alarms when only a few Wh were missing. Fix: both forced-charge rules fire only when the ratio is violated **and** the shortfall (target − delivered energy per slot) exceeds `params.min_shortfall_kwh` (shipped 0.1, per rule in the pack); a rule using the predicate without either parameter fails loud. Migration step `dm4.deviation_energy_shortfall` adds `min_shortfall_kwh` (0.1) where missing and keeps custom values. Needs a pick to `main`. Live check still open: forced-charge markers over a day with small Soll amounts.

- [ ] **[release/2.7] Heat-pump deviation („Freigabe, aber nicht angesprungen“): grade like forced charging.** The rule had only `power_mismatch_positive` with the global `tolerances.power_kw` (0.05 kW), so any shortfall above 50 W raised the hint, even when the heat pump ran and only drew a bit less. Fix: new consumer predicate `power_energy_below_ratio`: slot energy < `params.max_ratio` × Soll energy **and** shortfall > `params.min_shortfall_kwh` (shipped 0.5 / 0.1 kWh, per rule, separate from the forced-charge rules). No verdict without the consumer's closed-interval slot mean (`closed_interval.flex_kw`); the tooltip shows % and kWh. `dm4.deviation_energy_shortfall` rewrites the rule while it has the shipped form (ids `wp_heating_enable_no_start` / `waermepumpe_enable_no_start`) and keeps a custom message. Needs a pick to `main`. Live check still open: heat-pump hints over a day.

- [ ] **[release/2.7] forecast.solar PV forecast lags by about half an hour (found 2026-10-29):** forecast.solar `watts` is the power **at** the timestamp (`watt_hours_period` at T equals the trapezoid of `watts` over the preceding period, e.g. (1595 + 1773) / 2 = 1684 Wh), but `_map_hourly_data_to_vector` in `data/pv_forecast.py` takes `watts` at the full hour as the mean power of the **following** hour (QH slots inherit the parent hour). Effect: PV too low in the morning, too high in the afternoon; the daily sum is nearly right. Example call (south roof, 2026-10-30): slot 16–17 h 1.29 kWh vs. 1.04 kWh period energy, slot 17–18 h 0.79 kWh vs. 0.05 kWh (sunset 17:08); the sunrise period (07:01–08:00) is lost because no key exists at 07:00. Relevant for afternoon battery / PV-follow decisions in the MILP.
  - **Fix (2026-10-31, branch `fix/forecast-solar-period-energy`):** `_map_hourly_data_to_vector` now gives each slot the trapezoid mean of the forecast.solar `watts` points over the slot interval (hours plus sunrise / sunset points; 0 outside the points). For hourly slots this equals `watt_hours_period`; QH slots follow the curve. Only `watts` is used, so the cache, the disk cache, the Shadow feed and the URL are unchanged. Tests in `tests/test_pv_forecast.py` (period energy, sunrise / sunset split, QH slots, slots outside the points); user doc `docs/konfiguration/batterie-pv.md` § PV-Prognose im Live-Betrieb.
  - **Impact:** changes the PV input of every live plan and of replays → golden-master triage (`regression-triage`, expected: intended), release note; check whether the **PV forecast calibration factor** analysis (2026-10-25) and SE paths that read recorded forecast.solar feeds assumed the old mapping.
  - **Note:** `scripts/pv_forecast_compare.py` logs both mappings (`forecast_solar` vs. `forecast_solar_earnie`); its `evaluate` quantifies the error against measured PV before / after the fix.
  - **Verify:** live PV forecast in the cockpit / `forecast_pv_kw` against measured PV around sunrise and sunset (or `scripts/pv_forecast_compare.py evaluate` on `main`); pick to `main` afterwards.

## New Bugs (Do not remove this chapter — even if empty)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
