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


- [ ] **[release/2.7] forecast.solar PV forecast lags by about half an hour (found 2026-10-29):** forecast.solar `watts` is the power **at** the timestamp (`watt_hours_period` at T equals the trapezoid of `watts` over the preceding period, e.g. (1595 + 1773) / 2 = 1684 Wh), but `_map_hourly_data_to_vector` in `data/pv_forecast.py` takes `watts` at the full hour as the mean power of the **following** hour (QH slots inherit the parent hour). Effect: PV too low in the morning, too high in the afternoon; the daily sum is nearly right. Example call (south roof, 2026-10-30): slot 16–17 h 1.29 kWh vs. 1.04 kWh period energy, slot 17–18 h 0.79 kWh vs. 0.05 kWh (sunset 17:08); the sunrise period (07:01–08:00) is lost because no key exists at 07:00. Relevant for afternoon battery / PV-follow decisions in the MILP.
  - **Fix (2026-10-31, branch `fix/forecast-solar-period-energy`):** `_map_hourly_data_to_vector` now gives each slot the trapezoid mean of the forecast.solar `watts` points over the slot interval (hours plus sunrise / sunset points; 0 outside the points). For hourly slots this equals `watt_hours_period`; QH slots follow the curve. Only `watts` is used, so the cache, the disk cache, the Shadow feed and the URL are unchanged. Tests in `tests/test_pv_forecast.py` (period energy, sunrise / sunset split, QH slots, slots outside the points); user doc `docs/konfiguration/batterie-pv.md` § PV-Prognose im Live-Betrieb.
  - **Impact:** changes the PV input of every live plan and of replays → golden-master triage (`regression-triage`, expected: intended), release note; check whether the **PV forecast calibration factor** analysis (2026-10-25) and SE paths that read recorded forecast.solar feeds assumed the old mapping.
  - **Note:** `scripts/pv_forecast_compare.py` logs both mappings (`forecast_solar` vs. `forecast_solar_earnie`); its `evaluate` quantifies the error against measured PV before / after the fix.
  - **Verify:** live PV forecast in the cockpit / `forecast_pv_kw` against measured PV around sunrise and sunset (or `scripts/pv_forecast_compare.py evaluate` on `main`); pick to `main` afterwards.
- [ ] **[release/2.7] Signal-list export misses signals that Live-Lesen reads (found 2026-11-01 in a community fork, issue #89):** the EHAL-Com Signal-list export (Loxone VO / VI templates) builds its signals from the device-role templates in `share/ehal/roles/*.json` only (`ehal/signal_catalog.py::_plant_kinds`, consumer loop over `_role_kinds`). Live-Lesen expects more (`integrations/ehal_debug_fields.py::PLANT_HOUSE_LIVE_READ_FIELDS`, `integrations/ehal_debug_mapping.py::_consumer_live_read_fields`). Missing in the export: plant energy counters `sens_pv_energy`, `sens_grid_energy_import`, `sens_grid_energy_export`; heat pump `sens_consumer_active`, `sens_energy_total`; EV `sens_energy_total`.
  - **Effect:** a setup built from the export gets no VO for these counters; Live-Lesen shows them as missing, and everything that uses counters instead of power (slot-Ist energy in the charts, energy-graded deviation rules) has no data. Hand-made VO setups are not affected.
  - **Fix (2026-11-01, branch `contrib/issue-89-stoeff99`, cherry-pick of fork commit 02c7af1b, author consent per `LICENSE.md` § 6 in issue #89):** `ehal/signal_catalog.py` plant kinds = grid role + `PLANT_HOUSE_LIVE_READ_FIELDS`; consumer kinds = role kinds + `integrations/ehal_debug_mapping.py::consumer_live_read_kinds(consumer)` (same per-type rules as Live-Lesen), deduplicated, IDs from the configured entity ids. Tests in `tests/test_ehal_signal_list.py` (a real setup's 38 Live-Lesen IDs are exported; export reads equal `expected_live_read_fields()`).
  - **Note:** the fork also sends `sens_pv_energy` with 3 decimals via `_DECIMALS_BY_KIND` in `scripts/pilot_vo_template_gen.py`; that placeholder mechanism (`<v.N>`) exists only on `main`, so this part was left out on `release/2.7` and must come with the port to `main` (the full fork commit applies there).
  - **Verify:** Signal-list export of a Loxone setup contains the plant energy counters, heat pump `sens_consumer_active` / `sens_energy_total` and EV `sens_energy_total`; Live-Lesen shows no missing signal after import; pick to `main` afterwards.
- [ ] **[release/2.7] Possible bug: EV with a bound charging-power setpoint fails every live cycle, `charging_schedule.milp` cannot be created in the UI (found 2026-11-01 in a community fork, issue #89):** the live MILP needs the EV block `charging_schedule.milp` (`live_modus_a_min_remaining_kwh`, `tie_break_on_epsilon`, `tie_break_time_epsilon`) as soon as the EV uses a power setpoint. `optimizer/eauto_milp.py` (`ev_in_modus_b`, `milp_uses_power_setpoint`) raises „eauto_milp-Konfiguration fehlt für Live E-Auto-Optimierung“ when `params is None`. The legacy Loxone path fails earlier in `house_config/planning_flex_converters.py` („charging_schedule.milp fehlt … Pflicht bei loxone_outputs.power_setpoint_name“); an EV bound through EHAL (wallbox setpoint) seems to pass the converter and fail in the MILP instead. No form in `ui/house_config_profile_ev.py` writes the block and new EV consumers do not get it, so only a hand-edited `house_profiles.json` works.
  - **Fix (2026-11-01, branch `contrib/issue-89-stoeff99`, cherry-pick of fork commit 23a20ae7, author consent per `LICENSE.md` § 6 in issue #89):** EV form section **MILP-Feintuning** in `ui/house_config_profile_ev.py` with the three values; without a stored block the suggestions are shown (2 × P_min, 1.4 kW without P_min; 0.001 / 0.0001) and written only on save; new EV consumers get the block; `optimizer/eauto_milp.py::missing_live_params_error` names the EV and the form field. User doc `docs/konfiguration/flexible-verbraucher.md` § E-Auto: block is required with a current setpoint. Tests in `tests/test_eauto_milp_mode.py`, `tests/apptest/test_persist_consumers_apptest.py`.
  - **Verify:** EHAL-bound wallbox without the block → form shows the suggestions, save writes them, live cycle runs; pick to `main` afterwards (applies cleanly there).

## New Bugs (Do not remove this chapter — even if empty)



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
