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

- [ ] **Chart 1: battery export had no up bar during Zwangsentladen** *(dump `debug_dump_20261030_055437`, 2.7.0-beta.1, Loxone; fixed 2026-11-01 on `main`)*: during Zwangsentladen 5 kW (29.10. 17:15–17:45, Ist −4.2 / −5 / −5 kW) Chart 1 drew „Batterie entladen (Verbrauch)“ above zero only for the house share (~0.4–0.5 kW); the rest (~3.8–4.5 kW) appeared only as „Einspeisung (Batterie)“ below zero. A bug, not a design choice: `docs/ui/charts.md` requires equal up and down columns since the first Rauf/Runter commit (`466decd9`); PV export was always balanced (the PV up bar holds the exported share). No scenario covered battery export, so the balance check never saw it.
  - **Fix:** `ui/chart_flow_segments.py` adds the up segment „Batterie entladen (Einspeisung)“ (`battery_discharge_export`, same kW as `flows.export_from_battery`, color `MUTED_BATTERY_EXPORT`), stacked on „Batterie entladen (Verbrauch)“; the down bar stays. Trace order in `ui/chart_flow_traces.py` / `ui/chart_flow_balance.py`. Tests: scenario J in `scripts/flow_balance_test_data.py` (balance check), `tests/test_chart_flow_balance.py::test_forced_discharge_export_has_matching_up_segment`. Docs: `docs/ui/charts.md`.
  - **Not fixed in `release/2.7`** (owner, 2026-11-01): listed there as a known limitation in the 2.7 release notes.
  - **Verify:** Monitor on a slot with Zwangsentladen into the grid: up and down columns equal height, cyan up segment above the green one.

- [ ] **PV forecast comparison run** `[dev]` *(logger done 2026-10-30, [Erledigt](Backlog-Erledigt.md); in autumn the forecast.solar quality varies strongly, e.g. on fog / inversion days)*: run `scripts/pv_forecast_compare.py fetch` hourly for 3–4 weeks in autumn, then `evaluate`. The result decides the default source (see **Solcast as PV forecast source**) and feeds the **PV forecast calibration factor** (**Adaptation P3**): the MAE after the per-source linear scale separates a constant bias, which the calibration factor absorbs, from weather skill. Optional later: DWD MOSMIX `Rad1h` as a further source in the logger.

- [ ] **Austria: Region autoselects the Netzbereich** *(dogfooding finding, fixed 2026-10-31)*: the claim "Region and Netzbereich are 1-1" does not hold: 9 Bundesländer, 14 catalog areas; Kärnten, Oberösterreich, Steiermark, Tirol and Vorarlberg each also hold a city / valley grid (Klagenfurt, Linz, Graz, Innsbruck, Kleinwalsertal). Fix: every AT area in `share/config/grid_fees.json` (and the test fixture copy) names its Bundesland in Edibert's existing `regions` field (a correction, allowed by P8 D1/D4). The Hausprofil region select (`on_change`) sets the Netzbereich when exactly one area names the region (Burgenland, Niederösterreich, Salzburg, Wien) and a caption under the select says so; *Eigener Arbeitspreis* and an area that lies in the region stay; areas without `regions` (user areas) never decide. Tests: `tests/test_grid_area_regions.py`, `tests/apptest/test_house_profile_grid_area_autoselect_apptest.py`; docs `docs/konfiguration/preise.md`. **Limit:** site copies of `grid_fees.json` seeded before this change have no `regions` (seeded once, never refreshed), so there nothing is autoselected until the catalog channel or a re-seed brings them. Verify in the dogfooding setup with a fresh pack.

- [ ] **Dogfooding: `KeyError: 'type'` after switching a consumer to „Haus Wärme“** *(found 2026-10-31, fixed 2026-10-31)*: the house config page crashed on the switch rerun. Traceback summary: `_render_consumer_form` → `_consumer_expander_title` → `consumer_annual_kwh(preview)` → `house_thermal_parameters` → `heating_params_from_thermal` → `default_efficiency` (`heat_source["type"]` missing). Cause: the expander title computes the annual kWh from a live preview before the type fields render, so on the switch there is no heat-source widget value yet and the former generic consumer has no stored `heat_source`; the preview passed `{}`.
  - **Fix:** `ui/house_config_profile_thermal_annual.py` `_heat_source_select_start` gives the start values of the heat-source selectboxes (stored value, else Wärmepumpe / Luft as the form already preselected); the selectboxes and the preview both use it, so the title computes with the heat source the form shows. No new default: the form preselected Wärmepumpe / Luft before. Tests: `tests/apptest/test_consumer_type_switch_apptest.py` (fails before, passes after) and `tests/test_planning_editors.py::test_live_consumer_for_annual_type_switch_takes_heat_source_select_start`.
  - **Verify:** in the app, switch a consumer to „Haus Wärme“: no error, the title shows a kWh/a value, Wärmepumpe / Luft is preselected.



## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Recorder replay misses the live plan for some SwimSpa and heat pump cycles** *(found 2026-10-31)*: follow-up of the archived push-reads fix. Replay of all 112 NAS cycles with `start_state.push_reads` (30.10. 15:49 – 31.10. 17:59, 2.7.0-beta.2, `release/2.7` @ `10491702`, `solver_mode="production"`): 108 replay hashes equal live. Reserve refill and plugged-in EV are covered now (EV connected 105/107, `e_auto` in live setpoints 17/19, reserve-refill cycles 4/6; all four misses are explained by the consumers below). The four misses:
  - **30.10. 23:59:57:** same setpoints (Zwangsladen 0.213 kW), but live writes `pool_swimspa: 0.0` in `consumer_powers_kw` and replay leaves the key out, so the hash differs. Live and replay build a different consumer set.
  - **31.10. 08:59:53:** live switched the heat pump off (Automatik, battery 0.5 kW); replay keeps `waermepumpe` 1.9 kW (battery −1.4 kW). The 08:44 cycle before (heat pump 1.9 kW live) matches.
  - **31.10. 14:14:52 and 14:29:52** (both with a pending virtual reserve refill): live Entladesperre (mode 2) with `pool_swimspa` 2.8 kW; replay Automatik without SwimSpa (battery 0.635 / 1.652 kW). The matching 13:59 and 14:44 cycles have the same SwimSpa `push_reads` and `thermal_readings` (36 °C, setpoint 35 °C, heating active).
  - Suspected cause: a SwimSpa / heat pump state from the previous cycle (run or session state) that the live cycle reads and the recorder does not store; `flexible_consumers_state` is empty in every cycle. Not proven.
  - **Note:** the outage cycle 31.10. 14:49:58 (`flags.outage`) carries the same live hash as 14:14 — check whether the outage path re-writes the last plan, and whether outage cycles are excluded from replay checks.
  - Done when the four cycles replay to their live hash (or the remaining difference is a documented, intended non-input) and a regression test pins the missing input.

- [ ] **Flaky full-suite tests block the pre-commit hook** *(found 2026-10-31)*: in three full runs (two of them pre-commit) exactly one test failed each time, a different one per run: `tests/test_navigation_specs.py::test_n2_env_value_gives_expected_modes_and_sidebar_hints` (parameters `bogus` and `scenario_exploration`) and `tests/test_flash.py::test_flash_notices_are_shown_after_rerun_and_only_once`. Both files pass when run alone (twice each). Looks like state leaking between tests in the xdist full run (environment variable or session state), not a product bug. A commit had to use `--no-verify`. Done when five consecutive full runs are green
  - **Cause (2026-10-31):** not state leakage but load. The last red pre-commit run failed with `RuntimeError: AppTest script run timed out after 3(s)`: Streamlit `AppTest` defaults to a 3 s script timeout, and 128 bare `.run()` calls in the suite use it. Under `-n auto` (all cores busy with MILP tests) a cold script run exceeds 3 s now and then, so a random AppTest fails. The input data is the same in every run.
  - **Fix:** `tests/conftest.py` raises the `AppTest` default timeout to at least 30 s for every test (explicit larger values stay). The timeout only bounds a hung script, so green runs are not slower. Three consecutive full runs green after the fix (5126 passed); close after two more green full runs (e.g. the next pre-commit hooks). **Note (2026-10-31):** the pre-commit hook of commit 85b9a973 was green too, so four in a row; one more is missing
  - **Note (2026-10-31):** the pre-commit hook of 8a4d8d3e was green (fifth run), but two manual full runs the same day each failed one daemon timing test (`tests/test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, `tests/test_main_daemon.py::test_start_stop_with_stub_script`); both pass alone. A second flake pattern under xdist load, not the AppTest timeout; harden these tests, then count five green full runs again
  - **Note (2026-10-31):** `test_start_stop_with_stub_script` hardened: the stub takes `main.lock` before it writes its PID into it, so `status()` briefly reports `running` with `pid=None`; the test now waits for both (8 concurrent runs green). Pre-commit hook of 28d8ace9 failed on it once before the fix, the retry was green. Left: `test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, then count five green full runs
  - **Note (2026-11-01):** `test_early_cycle_plans_for_tick_and_writes_only_after_hold` hardened: it planned for the next quarter-hour tick, which can be seconds away; `planning_now()` is `max(real, tick)` and `_finalize_previous_interval` reads the real clock, so a slow run under xdist load passed the tick and the asserts saw the next slot. The test now plans one slot further out. Count restarted: 2 of 5 green full runs (5181 passed, 26 skipped)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).


## Document Review Findings (Do not remove this chapter — even if empty)

