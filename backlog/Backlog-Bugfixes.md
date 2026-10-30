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


- [ ] **Synthetic PV fallback ignores orientation and is silent in Shadow mode (found 2026-10-30):** without forecast.solar data `_generate_seasonal_fallback` planned a parabola with 40 % of kWp in October, independent of azimuth/tilt and weather (a north roof got 2.72 kW peak); only a WARNING log line showed it. Causes: Shadow dropped the `ext:pv_forecast:*` feed record after the default 120 s, while Prod records it only on a real API call (15-min guard, longer under 429); the forecast.solar cache was in memory only, so a restart during a rate limit had no data. Fix `114a724d` (owner decision 2026-10-30, no version bump): (1) Shadow replays the PV feed up to 3 h (`replay_ext_payload(..., max_age_s=)`, `SHADOW_FEED_MAX_AGE_SEC`); (2) Prod persists the last successful answer per URL in `runtime/pv_forecast_cache.json` (used up to 6 h, restores the 15-min guard stamp); (3) without forecast.solar data the system is planned from Open-Meteo `global_tilted_irradiance` with its own tilt/azimuth (preceding-hour mean → slot `h` takes stamp `h + 1`, kW = GTI / 1000 × kWp); (4) the parabola is removed — if Open-Meteo fails too, `PvForecastUnavailableError` aborts the cycle like missing day-ahead prices; (5) source per system in `get_api_status()["source_by_system"]` and run state `pv_forecast_sources`, WARNING per cycle in `main.py`, cockpit warning in `ui/live_mode.py`. User doc `docs/konfiguration/batterie-pv.md` § PV-Prognose im Live-Betrieb. Tests `tests/test_pv_forecast.py` (disk cache restart / age limit, Open-Meteo orientation and hour shift, per-system substitute, abort, Shadow feed max age). Verify in Shadow and Prod: no seasonal curve in the log, `pv_forecast_sources` normally `forecast_solar`, after a Prod restart the log shows the disk cache being loaded.
  - **Tracker:** verify the PV forecast fix in Shadow and Prod after push and rollout.


## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Dump `debug_dump_20261030_055437` — discharge bar above zero during Zwangsentladen (2.7.0-beta.1, Loxone):** the note says 19.10. 17:00 Zwangsentladen with no battery-withdrawal bar above zero. History at 19.10. 17:00 is mode 0 (Automatik), plan −0.04 kW, Ist discharge ~0.18 kW. The chart that was open is 29.10. 07:00–31.10. 07:03. There, 29.10. 17:15–17:45 is Zwangsentladen 5 kW (Ist −4.2 / −5 / −5 kW). The chart draws „Batterie entladen (Verbrauch)“ above zero only for the house share (~0.39 / 0.50 / 0.48 kW). The rest (~3.8–4.5 kW) is „Einspeisung (Batterie)“ below zero. Confirmed gap: that export kW has no matching up bar, so the two columns differ by „Einspeisung (Batterie)“. Add an up segment of the same kW (discharge that feeds the export), stacked with „Batterie entladen (Verbrauch)“, and keep the down bar.

Findings from the viability study (house generator and offline runs, 2026-10-23/24; code in `studies/viability` and `studies/poc_cloud`).

Source of the next three items: [issue #50](https://github.com/JochenTCC/Earnie/issues/50) (live feedback, AT, HA backend, Docker image digest = `v2.6.2`; fixed import tariff + spot-indexed export). Findings were checked against `release/2.7` (2.7.0-alpha.9).

- [ ] **Issue #50 / 4 ([#57](https://github.com/JochenTCC/Earnie/issues/57)) — "Zwangsladen nicht ausgeführt" (deviation S3, `battery_power_below_tolerance`):** reporter's data (2.6.2, 3 slots, no restart, `the HA battery power sensor` positive while charging, 2.6.2 ran with `ehal.ha.sign: negate`) does **not yet show a sign bug**: `closed_interval` of a log entry at T covers the *previous* slot [T-15, T), so pairing it with that entry's `target_power_kw` (Soll for the *new* slot) is misleading; e.g. 11:47 shows snapshot -1.24 / closed -1.156 for a plan of 1.247 → consistent. **Next:** ask for the `closed_interval` of the *following* entry (T+15 min) for the three slots, plus `sample_count`; the 09:30 row (snapshot -2.49 but closed mean 0.0 over 23 samples) and the 11:32 row (snapshot -0.0 shortly after the slot start) stay unexplained until then. Candidates unchanged: decision-time snapshot fallback (`MIN_SAMPLE_COUNT_FOR_MEAN`), sign handling of the sampler vs. snapshot. Decision so far: do **not** harden the sampler state across restarts. **Mail of the reporter, 2026-10-24: no new data** (the mail does not mention forced charging or the `closed_interval` of the following entries); still waiting for the requested log entries.
- [ ] **Issue #50 / [#58](https://github.com/JochenTCC/Earnie/issues/58) — Forced-charge target stuck at 0.624 kW in many slots:** reporter sees `target_power_kw` exactly 0.624 across many slots and concludes the cap comes from the optimizer, not the inverter. **Next:** ask for the battery entry (max charge power, `conversion`/η, SoC window) from `components.json` / `house_profiles.json` and a few slots; check `optimizer/battery.py` and the MILP charge bounds (SoC headroom, inverter clipping, `battery_max_power_kw` vs. DC/AC conversion) for a limit that yields 0.624 kW. **Mail of the reporter, 2026-10-24: no new data** (battery entry, `conversion`/η and sample slots still requested).
- [ ] **Recorder replay plan differs from the live plan in 7 of 16 NAS cycles (found 2026-10-28):** all 16 cycles of the 2.7.0-beta.1 dump `debug_dump_20261028_103550` replay offline, but 7 plan hashes differ from the recorded ones (e.g. 09:44 replay runs `pool_swimspa` at 2.8 kW, live did not; 10:29 replay charges the battery at 2.745 kW, live mode 2). Suspected: inputs the replay still reads fresh instead of from the recording (outdoor forecast in `optimizer/thermal_targets.py`), and the recorder reading the thermal values a second time after the live run. Not investigated. The plan is info-level in the regression suite; the private case `REG-76-nas-thermal-replay` uses a matching cycle (09:59).
- [ ] **forecast.solar PV forecast lags by about half an hour (found 2026-10-29):** forecast.solar `watts` is the power **at** the timestamp (`watt_hours_period` at T equals the trapezoid of `watts` over the preceding period, e.g. (1595 + 1773) / 2 = 1684 Wh), but `_map_hourly_data_to_vector` in `data/pv_forecast.py` takes `watts` at the full hour as the mean power of the **following** hour (QH slots inherit the parent hour). Effect: PV too low in the morning, too high in the afternoon; the daily sum is nearly right. Example call (south roof, 2026-10-30): slot 16–17 h 1.29 kWh vs. 1.04 kWh period energy, slot 17–18 h 0.79 kWh vs. 0.05 kWh (sunset 17:08); the sunrise period (07:01–08:00) is lost because no key exists at 07:00. Relevant for afternoon battery / PV-follow decisions in the MILP.
  - **Fix direction:** derive slot energy from `watt_hours_period` (period ending at the key → slot containing the period, split sunrise / sunset periods), QH slots from the instantaneous `watts` (mean of both ends) or by splitting the hourly energy; no change to the URL (cache key, shadow feed hash, recorded replays stay valid).
  - **Impact:** changes the PV input of every live plan and of replays → golden-master triage (`regression-triage`, expected: intended), release note; check whether the **PV forecast calibration factor** analysis (2026-10-25) and SE paths that read recorded forecast.solar feeds assumed the old mapping.
  - **Note:** `scripts/pv_forecast_compare.py` logs both mappings (`forecast_solar` vs. `forecast_solar_earnie`); its `evaluate` quantifies the error against measured PV before / after the fix.



## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).
- [ ] **Issue #50 — confirm the version handling (`version.py`):** the fixes of #50 / #56 / #59 / #60 / #61 were merged to `main` (#62, #63) without a version bump; `main` still has `2.7.0-alpha.9`. On `release/2.7` they were cherry-picked (#65) and the version was bumped to `2.7.0-beta.1` (#66). Confirm that this covers the intended bump (rule: never change `version.py` without the maintainer's approval; completed bugfixes -> PATCH only); otherwise propose a PATCH bump before the next release.
- [ ] **Issue #50 — tell the reporter what changed:** the reporter has only the mail reply of 2026-10-24. New since then: the migration report page and daemon start (#61), `dm4.ha_sign` (#56), the EU retry pause (#59), the HA package fixes and watchdog (#60). Reply once the PRs are merged / released, and ask again for `EARNIE_AUTO_START_MAIN`, the `main_stdio.log` after a migration and the `Address` line of a VI/VO XML.


## Document Review Findings (Do not remove this chapter — even if empty)

