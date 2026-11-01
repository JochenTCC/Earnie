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

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay misses the live plan for some SwimSpa and heat pump cycles** *(found 2026-10-31)*: follow-up of the archived push-reads fix. Replay of all 112 NAS cycles with `start_state.push_reads` (30.10. 15:49 – 31.10. 17:59, 2.7.0-beta.2, `release/2.7` @ `10491702`, `solver_mode="production"`): 108 replay hashes equal live. Reserve refill and plugged-in EV are covered now (EV connected 105/107, `e_auto` in live setpoints 17/19, reserve-refill cycles 4/6; all four misses are explained by the consumers below). The four misses:
  - **30.10. 23:59:57:** same setpoints (Zwangsladen 0.213 kW), but live writes `pool_swimspa: 0.0` in `consumer_powers_kw` and replay leaves the key out, so the hash differs. Live and replay build a different consumer set.
  - **31.10. 08:59:53:** live switched the heat pump off (Automatik, battery 0.5 kW); replay keeps `waermepumpe` 1.9 kW (battery −1.4 kW). The 08:44 cycle before (heat pump 1.9 kW live) matches.
  - **31.10. 14:14:52 and 14:29:52** (both with a pending virtual reserve refill): live Entladesperre (mode 2) with `pool_swimspa` 2.8 kW; replay Automatik without SwimSpa (battery 0.635 / 1.652 kW). The matching 13:59 and 14:44 cycles have the same SwimSpa `push_reads` and `thermal_readings` (36 °C, setpoint 35 °C, heating active).
  - Suspected cause: a SwimSpa / heat pump state from the previous cycle (run or session state) that the live cycle reads and the recorder does not store; `flexible_consumers_state` is empty in every cycle. Not proven.
  - **Note:** the outage cycle 31.10. 14:49:58 (`flags.outage`) carries the same live hash as 14:14 — check whether the outage path re-writes the last plan, and whether outage cycles are excluded from replay checks.
  - Done when the four cycles replay to their live hash (or the remaining difference is a documented, intended non-input) and a regression test pins the missing input.
  - **Analysis (2026-11-01):** `flexible_consumers_state` is not empty (it holds `delivered`, e.g. `pool_swimspa` 14.0 kWh on 30.10.). Two causes, none of them SwimSpa / heat pump run state:
    - **Planning clock (23:59:57, 08:59:53):** every NAS cycle is an early start (a few seconds before its tick) and live plans with `planning_now() = max(real now, tick)`. Replay froze the clock at the recorded `timestamp`, so 23:59:57 counted as 30.10. (SwimSpa target already delivered, `pool_filter` still in the set) and 08:59:53 as the 08:00 hour (heat pump window). Replay now freezes at `max(timestamp, planning_window.start)` (`_recorded_planning_moment`); `planning_window.start` is the anchored tick, so no new input is needed. Both cycles replay to their live hash.
    - **Solver time limit (14:14:52, 14:29:52):** these solves take ~3.2–3.7 s against the 3.0 s strict time limit. HiGHS returns its incumbent with status `Optimal` at the limit, so `strict_fallback` never fires and the plan depends on CPU load and timing. Sequential replays of the same entry give the live plan or the other one (objective 315.88 vs 316.48); all 12 cycles slower than 2.85 s (31.10. 13:44–17:44) are affected, all faster cycles match. Documented non-input (wall clock), not fixable by recording inputs; see the follow-up below.
    - **Telemetry limits:** live applies the HK + inbound export cap (`hk_max_export_kw`, `inbound_export_limit_kw`) and the effective `get_ess_*` limits; replay applied neither and did not drop ESS without own SoC. The recorder now stores `start_state.export_limits` and `start_state.ess_limits`; replay applies them and `filter_planning_batteries_with_soc` (cycles without the keys replay as before). Not the cause of the four misses (export cap 11 kW, limits equal to HK in these cycles), but live inputs replay could not see.
    - **Outage note:** `flags.outage` is set for out-of-band triggers (`bool(out_of_band)` in `main.py`), not for an outage. 14:49:58 runs a full fresh MILP; its hash equals 14:14 because the setpoints are equal (mode 2, SwimSpa 2.8 kW) — the hash covers only mode, target, battery plan and consumer powers. `list_full_horizon_cycles(require_unflagged=True)` excludes flagged cycles from the regression selection; ad-hoc replays of all cycles include them. The flag name is misleading (follow-up).
    - **Result:** replay of all 112 cycles, one worker: 110/112 match; the two misses (14:49:58, 14:50:11) are time-limited solves (14:14 and 14:29 matched in that run, missed in others). Tests: `tests/test_recorder_replay.py` (tick freeze, ESS / export limits), `tests/test_cycle_recorder.py` (recorded keys).
    - **Follow-up (open):** make time-limited live solves visible or reproducible, e.g. record the strict elapsed time / time-limit hit and the objective in `outputs`, and treat a HiGHS time-limit stop as not optimal so `strict_fallback` fires; rename `flags.outage` to `out_of_band`.
    - **Landed (2026-11-01):** fix committed on `release/2.7`; cherry-pick to `main` pending (collected pick).

- [ ] **[release/2.7] Possible bug: EV with a bound charging-power setpoint fails every live cycle, `charging_schedule.milp` cannot be created in the UI (found 2026-11-01 in a community fork, not reproduced yet):** the live MILP needs the EV block `charging_schedule.milp` (`live_modus_a_min_remaining_kwh`, `tie_break_on_epsilon`, `tie_break_time_epsilon`) as soon as the EV uses a power setpoint. `optimizer/eauto_milp.py` (`ev_in_modus_b`, `milp_uses_power_setpoint`) raises „eauto_milp-Konfiguration fehlt für Live E-Auto-Optimierung“ when `params is None`. The legacy Loxone path fails earlier in `house_config/planning_flex_converters.py` („charging_schedule.milp fehlt … Pflicht bei loxone_outputs.power_setpoint_name“); an EV bound through EHAL (wallbox setpoint) seems to pass the converter and fail in the MILP instead. No form in `ui/house_config_profile_ev.py` writes the block and new EV consumers do not get it, so only a hand-edited `house_profiles.json` works.
  - **Check:** reproduce with an EHAL-bound wallbox (HA testbed or HouseSim) without the block; confirm the error per cycle and whether the EV is dropped or the whole cycle aborts.
  - **Fix idea (decide, no silent default):** EV form section for the three values with proposed values shown and written only on save; new EV consumers get the block; the live error names the EV and the form field; user doc `docs/konfiguration/flexible-verbraucher.md` states that the block is required with a power setpoint.
- [ ] **[release/2.7] Signal-list export misses signals that Live-Lesen reads (found 2026-11-01 in a community fork, not reproduced yet):** the EHAL-Com Signal-list export (Loxone VO / VI templates) builds its signals from the device-role templates in `share/ehal/roles/*.json` only (`ehal/signal_catalog.py::_plant_kinds`, consumer loop over `_role_kinds`). Live-Lesen expects more (`integrations/ehal_debug_fields.py::PLANT_HOUSE_LIVE_READ_FIELDS`, `integrations/ehal_debug_mapping.py::_consumer_live_read_fields`). Missing in the export: plant energy counters `sens_pv_energy`, `sens_grid_energy_import`, `sens_grid_energy_export`; heat pump `sens_consumer_active`, `sens_energy_total`; EV `sens_energy_total`.
  - **Effect:** a setup built from the export gets no VO for these counters; Live-Lesen shows them as missing, and everything that uses counters instead of power (slot-Ist energy in the charts, energy-graded deviation rules) has no data. Hand-made VO setups are not affected.
  - **Fix idea:** export kinds = role kinds plus the Live-Lesen kinds of the same entity (one source, deduplicated, IDs from the configured entity ids); `sens_pv_energy` with 3 decimals in `scripts/pilot_vo_template_gen.py::_DECIMALS_BY_KIND`; test that the export IDs equal `expected_live_read_fields()` for the same entities. A fix for this exists in the fork; reuse only with the author's consent under `LICENSE.md` § 6.

## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)


## Document Review Findings (Do not remove this chapter — even if empty)
