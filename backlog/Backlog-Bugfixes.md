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

- [ ] **Heating rod was lost on save when „Heizstab im Wärmespeicher“ is checked** *(dog-fooding, found and fixed 2026-11-01 on `main`)*: the checkbox writes a `heating_rod` part and `normalize_thermal_annual_consumer()` keeps it, but `_serialize_thermal_annual_fields()` (`house_config/profiles_consumers.py`) wrote only the `thermal` block and `min_on_quarterhours`. `house_profiles.json` never got `parts`, so after reload the rod was gone and never planned. The same save also dropped `optimizer_flex`, `max_on_quarterhours`, `max_pulses_per_day` and `thermal_flex_window`.
  - **Fix:** `_serialize_thermal_annual_fields()` writes `parts` (when non-empty) and those four fields (when set). Tests: `tests/test_heat_source.py::test_profile_save_keeps_heating_rod_and_flex_fields` (normalize → serialize → normalize), `::test_profile_save_without_rod_writes_no_parts`.
  - **By design, not part of this fix:**
    - **Live:** `resolve_heating_rod_horizon_kwh()` (`optimizer/targets.py`) returns 0 in live planning until the rod has its own EHAL binding, so live the rod never runs (the field help says so).
    - **Planning beside a heat pump:** the rod only replaces heat-pump heat inside the day's heat target (`_add_one_thermal_flex_consumer()` in `optimizer/thermal_flex_context.py`: rod kWh count 1/JAZ toward the heat-pump target, no extra storage charge beyond it). At JAZ > 1 it runs only when the heat pump hits its run-time / pulse limits or prices are negative.
    - **Planning beside a fuel source (gas, oil, …):** the rod heat (η = 1) replaces fuel heat, capped at the day's heat demand (`_add_fuel_parent_rod_caps()`), and earns the avoided fuel cost (`fuel_credit_cent_per_kwh`).
    - **Not in the consumption data, no annual estimate in the Hauskonfigurator** (dog-fooding greenfield 2026-11-02): the rod has no demand of its own; only the MILP decides when it runs. `cons_data` is the house's reference consumption without Earnie, so it gets no rod column, and a fuel-heated consumer has 0 kWh electricity there (the Hauskonfigurator shows its fuel demand instead). Putting the rod into `cons_data` would count it twice (baseload and MILP, see `docs/dev/heating-system-variants.md` § Heating rod with measured data). Display follow-up: **Heating rod hint in the Hauskonfigurator** in [Backlog](Backlog.md).
  - **Verify:** Hauskonfigurator → „Heizstab im Wärmespeicher“ on → save → reload: checkbox still on, `house_profiles.json` has `parts`; fresh Szenarien-Explorer run (the rod is not in Verbrauchsdaten / `cons_data`) shows the column `<consumer_id>_heating_rod` with energy on PV-surplus or cheap slots (runs only in the cases above).

- [ ] **Chart 1: battery export had no up bar during Zwangsentladen** *(dump `debug_dump_20261030_055437`, 2.7.0-beta.1, Loxone; fixed 2026-11-01 on `main`)*: during Zwangsentladen 5 kW (29.10. 17:15–17:45, Ist −4.2 / −5 / −5 kW) Chart 1 drew „Batterie entladen (Verbrauch)“ above zero only for the house share (~0.4–0.5 kW); the rest (~3.8–4.5 kW) appeared only as „Einspeisung (Batterie)“ below zero. A bug, not a design choice: `docs/ui/charts.md` requires equal up and down columns since the first Rauf/Runter commit (`466decd9`); PV export was always balanced (the PV up bar holds the exported share). No scenario covered battery export, so the balance check never saw it.
  - **Fix:** `ui/chart_flow_segments.py` adds the up segment „Batterie entladen (Einspeisung)“ (`battery_discharge_export`, same kW as `flows.export_from_battery`, color `MUTED_BATTERY_EXPORT`), stacked on „Batterie entladen (Verbrauch)“; the down bar stays. Trace order in `ui/chart_flow_traces.py` / `ui/chart_flow_balance.py`. Tests: scenario J in `scripts/flow_balance_test_data.py` (balance check), `tests/test_chart_flow_balance.py::test_forced_discharge_export_has_matching_up_segment`. Docs: `docs/ui/charts.md`.
  - **Not fixed in `release/2.7`** (owner, 2026-11-01); the known-limitation hint is not in the 2.7.0 release notes (maintainer decision, 2026-11-02).
  - **Verify:** Monitor on a slot with Zwangsentladen into the grid: up and down columns equal height, cyan up segment above the green one.

- [ ] **PV forecast comparison run** `[dev]` *(logger done 2026-10-30, [Erledigt](Backlog-Erledigt.md); in autumn the forecast.solar quality varies strongly, e.g. on fog / inversion days)*: run `scripts/pv_forecast_compare.py fetch` hourly for 3–4 weeks in autumn, then `evaluate`. The result decides the default source (see **Solcast as PV forecast source**) and feeds the **PV forecast calibration factor** (**Adaptation P3**): the MAE after the per-source linear scale separates a constant bias, which the calibration factor absorbs, from weather skill. Optional later: DWD MOSMIX `Rad1h` as a further source in the logger.



- [ ] Chart1 SoC line thickness by battery capacity (≤5 kWh: 1 px / ≤10: 1.5 / ≤15: 2 / >15: 2.5); virtual PS keep dash styling. Visual check: multi-ESS + small virtual carve-out.

## New Bugs (Do not remove this chapter — even if empty)

- [ ] **Dog-fooding: „Haus Wärme“ editor and heating rod** *(found 2026-11-01)*
  - [ ] **„Haus Wärme“ editor mixes house and heat-source parameters**: the `thermal_annual` consumer is one flat block (`ui/house_config_profile_thermal_annual.py`): building fields, the heat source selectbox („Wärmequelle“), comfort fields, solar collector, storage and heating rod sit side by side, and `nominal_power_kw` / `min_on_quarterhours` are on the consumer, not on the heat source.
    - **Belong to the house (consumer), the same for every heat source:** Personen, Solltemperatur, Heizband Toleranz, Haus-Verlustkoeffizient H, Temperaturabsenkung wenn abwesend, Solar-Kollektor (Fläche, Neigung, Azimut).
    - **Belong to a heat source (only some types):** Nennleistung, Mindestlaufzeit (Viertelstunden), e.g. a heat pump or the heating rod; a gas or district-heat source needs neither for the MILP.
    - **Do:** check the data model (`spec["thermal"]` in `house_config/profiles_thermal_annual.py`, `heat_source`, `parts` in `house_config/heat_source.py`) and fix it: house parameters on the consumer, per-source parameters on the source / part. Structural pack change → migration via `runtime_store/migration/` (`config-migration.mdc`). Editor groups follow the model; user docs (`docs/konfiguration/`) in the same change.
  - Heating rod not used when checked → see **Heating rod was lost on save** under Verifications Pending.

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
    - **Landed (2026-11-01):** fix committed on `release/2.7` and cherry-picked to `main` (collected pick).
    - **Replay on 2026-11-01 (open on `main`):** 73/76 cycles replay to their live hash; three deterministic misses remain: 09:29:52 (SwimSpa), 10:14:52 (heat pump), 16:44:53 (consumer list). Not analysed yet; follow-up on `main`.

- [ ] **Flaky full-suite tests block the pre-commit hook** *(found 2026-10-31)*: in three full runs (two of them pre-commit) exactly one test failed each time, a different one per run: `tests/test_navigation_specs.py::test_n2_env_value_gives_expected_modes_and_sidebar_hints` (parameters `bogus` and `scenario_exploration`) and `tests/test_flash.py::test_flash_notices_are_shown_after_rerun_and_only_once`. Both files pass when run alone (twice each). Looks like state leaking between tests in the xdist full run (environment variable or session state), not a product bug. A commit had to use `--no-verify`. Done when five consecutive full runs are green
  - **Cause (2026-10-31):** not state leakage but load. The last red pre-commit run failed with `RuntimeError: AppTest script run timed out after 3(s)`: Streamlit `AppTest` defaults to a 3 s script timeout, and 128 bare `.run()` calls in the suite use it. Under `-n auto` (all cores busy with MILP tests) a cold script run exceeds 3 s now and then, so a random AppTest fails. The input data is the same in every run.
  - **Fix:** `tests/conftest.py` raises the `AppTest` default timeout to at least 30 s for every test (explicit larger values stay). The timeout only bounds a hung script, so green runs are not slower. Three consecutive full runs green after the fix (5126 passed); close after two more green full runs (e.g. the next pre-commit hooks). **Note (2026-10-31):** the pre-commit hook of commit 85b9a973 was green too, so four in a row; one more is missing
  - **Note (2026-10-31):** the pre-commit hook of 8a4d8d3e was green (fifth run), but two manual full runs the same day each failed one daemon timing test (`tests/test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, `tests/test_main_daemon.py::test_start_stop_with_stub_script`); both pass alone. A second flake pattern under xdist load, not the AppTest timeout; harden these tests, then count five green full runs again
  - **Note (2026-10-31):** `test_start_stop_with_stub_script` hardened: the stub takes `main.lock` before it writes its PID into it, so `status()` briefly reports `running` with `pid=None`; the test now waits for both (8 concurrent runs green). Pre-commit hook of 28d8ace9 failed on it once before the fix, the retry was green. Left: `test_main_early_start.py::test_early_cycle_plans_for_tick_and_writes_only_after_hold`, then count five green full runs
  - **Note (2026-11-01):** `test_early_cycle_plans_for_tick_and_writes_only_after_hold` hardened: it planned for the next quarter-hour tick, which can be seconds away; `planning_now()` is `max(real, tick)` and `_finalize_previous_interval` reads the real clock, so a slow run under xdist load passed the tick and the asserts saw the next slot. The test now plans one slot further out. Count restarted: 2 of 5 green full runs (5181 passed, 26 skipped)


## Minor changes (no bugs but still not worth to put it in backlog.md - do not remove this chapter - even if empty)

- [ ] **Issue #50 — release notes for the next version:** the Netznutzung now receives VAT on gross import tariffs (`prices_include_vat: true`), so computed import prices rise by the VAT share of the grid fee (e.g. +1.0 ct at 5 ct grid fee, 20 %). Also mention the new load warnings and the recompute button. Draft only, per `release-notes.mdc`; not started yet (no draft in `.github/release-notes/`, `UNRELEASED.md` only has the HA sign hint and the removed `flexible_consumers`). Also mention the new migration question `dm4.ha_sign` (leftover `ehal.ha.sign`, #56) the EU feature pause after an unreachable host (#59), the new HA package automation `earnie_watchdog_release_force` (default on, 300 s; #60), the templated `set_value` action for `input_number` targets (#60) and the report page / daemon start after the migration (#61).


## Document Review Findings (Do not remove this chapter — even if empty)

