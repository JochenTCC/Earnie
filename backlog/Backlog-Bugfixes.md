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

- [ ] Chart1 SoC line thickness by battery capacity (≤5 kWh: 1 px / ≤10: 1.5 / ≤15: 2 / >15: 2.5); virtual PS keep dash styling. Visual check: multi-ESS + small virtual carve-out.

- [ ] **[release/2.7] forecast.solar PV forecast lags by about half an hour (found 2026-10-29):** forecast.solar `watts` is the power **at** the timestamp (`watt_hours_period` at T equals the trapezoid of `watts` over the preceding period, e.g. (1595 + 1773) / 2 = 1684 Wh), but `_map_hourly_data_to_vector` in `data/pv_forecast.py` takes `watts` at the full hour as the mean power of the **following** hour (QH slots inherit the parent hour). Effect: PV too low in the morning, too high in the afternoon; the daily sum is nearly right. Example call (south roof, 2026-10-30): slot 16–17 h 1.29 kWh vs. 1.04 kWh period energy, slot 17–18 h 0.79 kWh vs. 0.05 kWh (sunset 17:08); the sunrise period (07:01–08:00) is lost because no key exists at 07:00. Relevant for afternoon battery / PV-follow decisions in the MILP.
  - **Fix (2026-10-31, branch `fix/forecast-solar-period-energy`):** `_map_hourly_data_to_vector` now gives each slot the trapezoid mean of the forecast.solar `watts` points over the slot interval (hours plus sunrise / sunset points; 0 outside the points). For hourly slots this equals `watt_hours_period`; QH slots follow the curve. Only `watts` is used, so the cache, the disk cache, the Shadow feed and the URL are unchanged. Tests in `tests/test_pv_forecast.py` (period energy, sunrise / sunset split, QH slots, slots outside the points); user doc `docs/konfiguration/batterie-pv.md` § PV-Prognose im Live-Betrieb.
  - **Impact:** changes the PV input of every live plan and of replays → golden-master triage (`regression-triage`, expected: intended), release note; check whether the **PV forecast calibration factor** analysis (2026-10-25) and SE paths that read recorded forecast.solar feeds assumed the old mapping.
  - **Note:** `scripts/pv_forecast_compare.py` logs both mappings (`forecast_solar` vs. `forecast_solar_earnie`); its `evaluate` quantifies the error against measured PV before / after the fix.
  - **Verify:** live PV forecast in the cockpit / `forecast_pv_kw` against measured PV around sunrise and sunset (or `scripts/pv_forecast_compare.py evaluate` on `main`); pick to `main` afterwards.

## New Bugs (Do not remove this chapter — even if empty)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
