🗺️ Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [x] Review Smart Energy app for comparison
- [x] Review other providers with flexible prices
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)



## Reminder für Greenfield Reset

It depends which local Greenfield setup you mean — the project distinguishes venv (:8511) and Docker (:8502).

Local venv Greenfield (port 8511)
Stop any running main.py / Streamlit first, then from the repo root:

Remove-Item -Recurse -Force greenfield\config, greenfield\runtime
mkdir greenfield\config, greenfield\runtime
Then restart via VS Code „main.py + Streamlit (Greenfield :8511)“ (or the individual Greenfield launch configs). Bootstrap runs automatically on startup and recreates the default files.

Docker Greenfield (port 8502)
Manual reset (from docs/einrichtung/greenfield-dev-stack.md):

docker compose -f docker-compose-greenfield.yml down
Remove-Item -Recurse -Force greenfield\config, greenfield\runtime
mkdir greenfield\config, greenfield\runtime
docker compose -f docker-compose-greenfield.yml up -d --build
One-liner (reset + start + smoke checks):

.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --reset
Use --no-build if you don’t want to rebuild the image:

.venv\Scripts\python.exe -m scripts.smoke_greenfield_docker --reset --no-build
Note: All of these wipe everything under greenfield/config/ and greenfield/runtime/; your normal ./config and ./runtime dev stack is untouched.

Command für boots

For bootstrap (scripts.bootstrap_runtime):

Default dev stack (config/ + runtime/)
.venv\Scripts\python.exe -m scripts.bootstrap_runtime
Creates only missing files; existing ones are not overwritten.

Greenfield (venv, port 8511)
After wiping greenfield\config and greenfield\runtime, either restart via VS Code (main.py + Streamlit Greenfield :8511) — bootstrap runs automatically — or run it manually with Greenfield env vars:

$env:EARNIE_CONFIG_PATH = "greenfield/config/config.json"
$env:EARNIE_RUNTIME_DIR = "greenfield/runtime"
$env:EARNIE_DOTENV_PATH = "greenfield/config/.env"
$env:EARNIE_HOUSE_PROFILES_PATH = "greenfield/config/house_profiles.json"
$env:EARNIE_TARIFFS_PATH = "greenfield/config/tariffs.json"
$env:EARNIE_BACKTESTING_SCENARIOS_PATH = "greenfield/config/backtesting_scenarios.json"
.venv\Scripts\python.exe -m scripts.bootstrap_runtime

## Feature Backlog



### Version 2.0 — Scenario Exploration consumption model (immediate)

**Goal:** Scenario Exploration (SE) compares **optimized** dispatch per scenario — baseline load from house-profile specs (default schedules), optimizer **shifts** MILP-flex start times for cost; `cons_data_hourly.csv` is **baseline / reference only**, not the simulation’s load truth.

**Precursor to:** credible greenfield scenario matrix (*Backtesting Tests*, *SE higher cost with fixed tariffs*); unblocks meaningful hourly comparison when only `battery_id` / `pv_system_id` / tariffs differ.

**Problem today (2026-07-13)**

| Area | Current behaviour | Intended (SE / greenfield) |
| ---- | ----------------- | -------------------------- |
| `cons_data_hourly.csv` | Drives hourly total load, flex kWh budgets, and `historical_reference` replay (`HistoricalDataCache` in [`simulation/engine.py`](simulation/engine.py)) | **Non-optimized baseline** for display + reference € only |
| MILP flex targets | `consumer_daily_targets_kwh` = sums of cons_data `{id}_kw` columns per 24h window | From **house profile** (`planning_flex_daily_targets` in [`house_config/planning_flex_bridge.py`](house_config/planning_flex_bridge.py) — exists, **unused** in backtesting) |
| Flex windows | `_planning_flex_consumers` from profile (`generic_flex_window`) | Same — keep |
| Plausibility | Optimized kWh must match cons_data historical (± tolerance) | Optimized kWh matches **profile spec** energy; timing may differ from baseline |
| Hourly UI | Shared `cons_data` + profile overlays (`render_reference_consumption_ui`) | **Baseline vs optimized** hourly per scenario |
| `backtesting_hourly.csv` | `sim_cost`, SoC, battery — no consumption profile | Optional: optimized hourly load columns per scenario |
| Greenfield | `flexible_consumers: []` — only generic MILP-flex from profile; EV / thermal shapes fixed from cons_data synthesis | Shiftable consumers (incl. EV where configured) enter MILP per profile |

**Observed symptom:** Two scenarios with same `house_profile_id` and only `battery_id` differing show **identical** hourly consumption (Jan 2025 test: 1411.3 kWh each; costs differ). Expected: same **total** spec energy, but battery/PV/tariff comparison — not replay of identical cons_data curves for “optimized” paths.

**Design — two load paths**

1. **Baseline path** — `cons_data` and/or `generic_hourly_kw_for_day` at reference `start_hour` ([`house_config/generic_schedule.py`](house_config/generic_schedule.py)): reference € (`historical_reference`), SE “Referenz-Verbrauch” chart.
2. **Optimized path** — matrix + MILP from resolved scenario: flex targets from profile, flex windows from `_planning_flex_consumers`; `simulate_horizon` output drives optimized hourly load for plausibility and charts.
3. **Prod / Loxone path (later):** logged cons_data remains valid **baseline** when present; SE greenfield uses synthetic baseline from profile (already how [`build_synthetic_dataframe_from_house_profile`](data/cons_data_house_profile.py) builds cons_data).

**Rollout (4 steps)**

- [ ] **Step 1 — Targets & matrix input (engine)**
  - SE/backtesting: `consumer_daily_targets_kwh` from `planning_flex_daily_targets` (+ config `flexible_consumers` where applicable), not cons_data window sums
  - Baseload / fixed consumers: house-profile overlay ([`house_profile_baseload_overlay`](house_config/planning_flex_bridge.py)); do not re-derive optimized baseload from cons_data `Total`
  - Flag or mode: `consumption_source=profile_spec` vs `logged_day` (prod replay) — default **profile_spec** for greenfield / SE
- [ ] **Step 2 — Plausibility & reference**
  - Plausibility: optimized kWh vs **profile-spec** totals for the window (not cons_data replay)
  - `compute_historical_reference_costs`: baseline load from profile default schedule (or cons_data when `source=loxone`); align with per-scenario tariffs (cf. *SE higher cost* Phase 2)
- [ ] **Step 3 — UI**
  - SE hourly chart: baseline (dashed) vs optimized per scenario (solid), per consumer where useful
  - Consumption debug table: show Δ kWh vs baseline when timing shifts but energy matches spec
- [ ] **Step 4 — Greenfield flex registration**
  - Document / bootstrap: which profile consumer types are MILP-flex in SE (generic with `start_shift_h > 0`, EV when `charging_schedule` present)
  - Ensure greenfield `mein_haushalt` exercises at least one shiftable generic + EV in test matrix

**Acceptance**

- Greenfield: `live` vs `s3-no-battery` — **same** spec total kWh, **same or shifted** flex timing depending on prices; hourly optimized chart differs from baseline when MILP moves loads; **costs** still differ by battery.
- Two scenarios with **different** `house_profile_id` — different baseline and optimized consumption curves.
- Prod path: logged cons_data baseline unchanged until explicit cutover item; no silent change to live `main.py` cons_data append.
- Tests: extend [`tests/test_backtesting_critical_cases.py`](tests/test_backtesting_critical_cases.py), [`tests/test_consumption_display.py`](tests/test_consumption_display.py); fixture run with shifted `standard` / `waschmaschine` windows.

**Out of scope (this chapter)**

- **Thermals P1a** — thermal PWM as MILP-flex (cost shift vs fixed overlay); this chapter only fixes **generic / EV flex** and baseline vs optimized separation.
- Re-optimizing every 15 min in SE (still one step per E-Auto anchor per [`docs/spec/planning-horizon-sunset.md`](docs/spec/planning-horizon-sunset.md)).

**Related:** *Version 2.0 — smoke-test follow-ups* → Phase B (*SE higher cost*), *Backtesting Tests*.



### Version 2.0

Branding (Earnie rename) → [Backlog-Erledigt.md](Backlog-Erledigt.md).

**Status (2026-07-13):** P1–P5, **P6a**, **Components**, and **Unified Open-Meteo solar** done (see [Backlog-Erledigt.md](Backlog-Erledigt.md)). Open under 2.0: **P7** + EV nominal voltage + remaining smoke follow-ups. Loxone sidebar bugfix → [Backlog-Erledigt.md](Backlog-Erledigt.md); cons_data ID fix pending verification in [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

Recommended order (2.0): smoke-test **Phase A** (Open-Meteo solar) → **Phase B** (*SE higher cost*) → **P7** README / evaluations → propose `version.py` → `2.0.0` (user approval). **P6b** live cutover → **2.+1** (first item after 2.0 release).

Critical path: **fixed-tariff SE investigation**, then **P7**. Open bugs → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

**Decisions (2026-07-11):**


| Topic                            | Decision                                                                                                                                                                                                                |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EARNIE_UI_MODES` key            | Hard rename `backtesting` **→** `scenario_exploration` — no alias; update compose, launch configs, docs, tests in same PR (P2)                                                                                          |
| Scenario id `runtime_settings`   | **Remove in 2.0** — live baseline is a normal scenario entry (default id `live`) selected via `live_scenario_id` in `config.json`; update scripts/tests/fixtures in same release (P2)                                   |
| Battery without PV               | **Allowed** — battery still required for MILP / planning readiness; PV optional (zero PV forecast when `pv_system_id` unset) (P1)                                                                                       |
| **7g-a** before P6               | **Skip for 2.0** — parallel NAS stack after local silent acceptance; 7g-a remains in Packaging backlog, not a 2.0 gate                                                                                                  |
| **P6 NAS deploy**                | **Parallel stack** — deploy validated `silent-migration-test/` to a new NAS folder; legacy `docker/earnie/` unchanged for rollback; **P6a** silent trial done; **P6b** non-silent cutover → **2.+1**                    |
| `sunrise_window` **rename (P4)** | Hard rename `sunset_window` **→** `sunrise_window` — no alias; internal symbols renamed; prod deploy only with P6a config migration                                                                                     |
| **2.0 release gate**             | `version.py` **→** `2.0.0` after **P7** acceptance (user approval); **P6b** not required for 2.0 release                                                                                                                |
| `components.json` **sidecar**    | **Hard cutover in 2.0** — `batteries[]` / `pv_systems[]` only in `config/components.json`; startup error if keys remain in `config.json`; no alias/fallback (same pattern as `runtime_settings`, global `battery_wear`) |




### Version 2.0 — smoke-test follow-ups

Components (`components.json` sidecar) → [Backlog-Erledigt.md](Backlog-Erledigt.md).

- [ ] **Scenario-Exploration without PV** — optimization/backtesting path incomplete when `pv_system_id` unset (P1 allows battery-only; simulation/MILP gaps remain)
- [ ] **EV nominal voltage for power calculation** — configurable per EV consumer (house profile + `flexible_consumers`); replace hardcoded 230 V in A→kW conversion (`integrations/loxone_client.py`); shared helper for live and planning paths; default 230 V / 1 phase when unset



#### Smoketest Findings — next actions (2026-07-12)

Ordered work plan after greenfield smoke. **Bugfix** items → [Backlog-Bugfixes.md](Backlog-Bugfixes.md); **UX/copy** here; **investigation** ties to *Backtesting Tests* below.

**Phase A — Unified Open-Meteo solar (manual smoke, 2026-07-13)**

Implementation → [Backlog-Erledigt.md](Backlog-Erledigt.md) (*Unified Open-Meteo solar*). Verify on greenfield venv (:8511) with network; reset per **Greenfield Reset** reminder at top of this file if `cons_data` is stale.

1. [ ] **Regenerate synthetic `cons_data`**
   - Set `EARNIE_*` paths to `greenfield/config` + `greenfield/runtime`; run [`scripts/generate_cons_data.py`](scripts/generate_cons_data.py) (or bootstrap after reset)
   - Spot-check **July 2024** in `cons_data_hourly.csv`: `pv_kw` and `haus_kw` peaks align to **2024-07** calendar hours (no 2023-modulo / wrong-season pattern)
2. [ ] **Solar-Kollektor reduces Haus Wärme in summer**
   - In `house_profiles.json`: set `solar_thermal_area_m2` > 0 (e.g. 8 m²) on thermal consumer; regenerate cons_data
   - July 2024: lower midday `haus_kw` vs same profile with `solar_thermal_area_m2: 0`
3. [ ] **Hauskonfigurator WP preview**
   - Thermal tab: metric + caption show **Open-Meteo-Archiv {year}** at profile lat/lon
   - Increase collector area → estimated kWh/a drops when `solar_thermal_area_m2` > 0
4. [ ] **File cache (`data/cache/open_meteo/`)**
   - First preview / backtesting fetch creates `*.json` cache entry; repeat run reuses cache (no API storm)
   - Corrupt one cache file → clear error; **no** silent fixture fallback
5. [ ] **Fail-hard (offline)**
   - Block network or archive API; `generate_cons_data` / backtesting aborts with explicit Open-Meteo error
6. [ ] **Backtesting smoke — July 2024**
   - `scripts/run_backtesting.py --start-month 7 --end-month 7` with `live` + `mein_haushalt` completes
   - PV from Open-Meteo when `scenario_params` set (not measured Loxone `pv_kw` from CSV)

**Enables:** *Backtesting Tests — Test mit Standard-Setting* climate/PV/solar-collector credibility (Haus Wärme MILP shift still **Thermals P1a**).

**Phase B — Scenario-Exploration credibility (fixed tariffs)**

0. [ ] **SE consumption model** — baseline vs optimized load paths; see *Version 2.0 — Scenario Exploration consumption model (immediate)* above (identical hourly consumption across battery-only scenarios = architectural gap, not test failure).

1. [ ] **SE higher cost after optimization with** `fixed_24h` **+ fixed-price tariffs** — deviations note *extra consumption*; greenfield scenario uses `fixed_25ct` / `fixed_37ct`
  - Reproduce: scenario **without EV** and **with EV** (see *Backtesting Tests* below)
  - Per bad window: `scripts/diag_single_window.py --anchor …`; check plausibility / deviation list vs reference (`historical_reference`)
  - Answer: is there optimization potential with flat import prices? (expect mainly PV self-consumption / export spread, not import timing)
  - If plausibility fails → bugfix + regression; if consumption matches but cost higher → battery wear / terminal SOC / export math
  - **Dump for single days:** CLI exists (`diag_single_window.py`); optional follow-up: expose from SE deviation detail (not a new dump format)
  - **Multiple scenarios for testing:** already supported in Szenarieneditor + `backtesting_scenarios.json`; document adding comparison entries (greenfield currently only `live`)



##### Plan of Attack

1. [ ] **SE higher cost after optimization with** `fixed_24h` **+ fixed-price tariffs** — deviations note *extra consumption*; greenfield scenario uses `fixed_25ct` / `fixed_37ct`
  **Goal:** (1) Is simulation plausible (kWh within tolerance)? (2) If plausible, why is € worse — bug, reference mismatch, or expected economics on flat import?
   **Phase 0 — Test matrix** (`greenfield/config/backtesting_scenarios.json`; pattern in `config/backtesting_scenarios.example.json`):
  - [x] `fixed_full` — `fixed_25ct` / `fixed_37ct`, full house (heat + PV + battery + EV)
  - [x] `fixed_no_pv` — `pv_system_id` unset
  - [x] `fixed_no_battery` — `battery_id` unset
  - [x] `fixed_no_pv_no_battery` — no battery, no EV
  - All runs: `--horizon-mode fixed_24h` (not `sunrise_window`)
   **Phase 1 — Bulk reproduce & classify**
  - [ ] Run per scenario: `scripts/run_backtesting.py --horizon-mode fixed_24h --start-month 1 --end-month 12`
  - [ ] Record: total € vs `historical_reference`, plausibility ok/total, deviation kinds (`consumption_tolerance` vs CBC)
  - [ ] Many consumption deviations → Phase 3A; plausibility clean but € worse → Phase 3B; use `scripts/analyze_plausibility_failures.py` if needed
    **Phase 2 — Reference fairness (do first — high leverage)**
  - [ ] `compute_historical_reference_costs` in `scripts/run_backtesting.py` is called **without** scenario tariff context → reference uses default/live import pricing while optimized scenario uses `fixed_25ct` / `fixed_37ct`
  - [ ] Recompute one window: reference cost **with** scenario tariffs vs optimized; if Δ€ collapses → fix is per-scenario reference tariffs (design), not MILP
    **Phase 3A — Plausibility failures (*extra consumption*)**
  - [ ] Per bad window: `scripts/diag_single_window.py --anchor … --scenario …`
  - [ ] Compare historical vs optimized kWh (tolerance: 0.5 kWh or 5% — `CONSUMPTION_TOLERANCE_*` in `simulation/engine.py`); split baseload vs flex (EV + `ready_by_hour` under `fixed_24h` is regression-sensitive — cf. 1.25.d)
  - [ ] Confirmed bug → [Backlog-Bugfixes.md](Backlog-Bugfixes.md) + pytest regression
    **Phase 3B — Plausible but more expensive**
  - [ ] Per 24h window decompose: consumer kWh, grid import/export kWh, import €, export €, end SOC vs start (`terminal_soc_percent` under `fixed_24h`)
  - [ ] Expected ceiling with flat import: savings only from PV self-consumption vs export spread (~12 ct/kWh at 25/37 ct), minus battery round-trip losses — **no import-timing arbitrage**
  - [ ] Tools: `diag_single_window.py`, window snapshots (`backtesting_window_snapshots.jsonl`), optional `scripts/analyze_benchmark_window.py`
    **Phase 4 — Sanity table (one month)**
  - [ ] `fixed_no_pv` / `fixed_no_battery` / `fixed_baseload_only` → Δ€ ≈ 0 expected
  - [ ] Document answer: optimization potential with flat import = small, bounded; negative Δ€ with matched kWh may be legitimate
    **Phase 5 — Outcomes**
  - Consumption mismatch → bugfix + regression
  - Reference tariff mismatch → pass resolved scenario tariffs into reference (or per-scenario reference field)
  - Matched kWh, small negative Δ€ → close as expected; SE caption / user doc
  - Matched kWh, large negative Δ€ → export / SOC / cost-row deep dive
  - Optional UX: expose `diag_single_window` from SE deviation detail (no new dump format)
   **Existing bullets (unchanged scope):**
  - Reproduce: scenario **without EV** and **with EV** (see *Backtesting Tests* below)
  - **Multiple scenarios:** Szenarieneditor + `backtesting_scenarios.json` (greenfield currently only `live`)

**Phase C — polish (may slip to 2.+1)**

1. [ ] **Speichern** always at eye level in Hauskonfigurator (sticky top bar or duplicate save on long tabs: Hausprofil / PV / Batterien) or shortkey (Ctrl-S)

**Open findings (unchanged scope, tracked above)**

- [ ] Backtesting Tests
  - [ ] Test mit Standard-Setting (inkl. Haus Wärme / PV / Batterie)
    - Optimization delivers higher costs than baseline
    - *Climate/PV/solar-collector alignment — verify via smoke **Phase A** (Unified Open-Meteo solar, 2026-07-13)*
    - *Blocked until **Thermals P1a** — Haus Wärme is fixed PWM overlay today; no MILP shift*
    - *Identical consumption across scenarios with same profile — **SE consumption model** chapter (not battery/PV test failure)*
  - [ ] Test ohne Haus Wärme
  - [ ] Test ohne PV
  - [ ] Test ohne Batterie
  - [ ] Test ohne PV und Batterie

- [ ] **Version 2.0 P7 — Documentation & evaluations**
  - Expand README with motivation / benefits — sensible order of use; less technical background than install/configuration hints
  - Build additional container for Windows as pure Python environment (if that makes sense) — spike vs local venv; go/no-go note
  - Evaluate running Scenario-Exploration as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility



### Version 2.+1

- [ ] **P6b — Live cutover (non-silent)** *(former 2.0 P6b; first post-2.0 prod step)*
  - **Stop legacy worker**; remove silent mode on new stack (delete or set `loxone_silent_mode: false` in `local_settings.json`); restart new worker
  - Switch daily use to new stack (UI port); keep old `docker/earnie/` stopped but intact for rollback window
  - Rollback: stop new containers, start legacy compose on `docker/earnie/`, UI on 8501
  - **Live `cons_data` `pv_kw`:** keep Loxone-measured append in `main.py` until this cutover; scenario exploration / backtesting use Open-Meteo only (*Unified Open-Meteo solar*, [Backlog-Erledigt.md](Backlog-Erledigt.md))



### Version 2.+1 — Quality epic / post-migration cleanup

After 2.0 release: dead code, obsolete tests, and leftover patches from pre-1.26.0 data model (1.26.0 P6 removed runtime fallbacks; this epic mops up the rest)

- [ ] Evaluate option for code coverage testing and identification of deprecated code / tests (especially due to substantial data model change) / obsolete patches because of legacy data model
- [ ] Thorough code review and refactoring
- [ ] Search for deprecated and unnecessary files and remove them
- [ ] Evaluate option for automated UI testing



### Version 2.+1

- [ ] **SwimSpa case B — follow-up review historical power & Loxone separation**
  - Check whether historical SwimSpa power logs (`thermal_control.history_logs.power_csv` = `..._SwimSpa_Leistung_...csv`, source `Ernie_Swim-Spa-P_act`) also contain the **filter share** (case B). If yes: assess impact on **thermal model calibration** (`heat_loss_kw_per_k` etc.) — filter (~0.18 kW) would be misinterpreted as heating power.
  - **Fundamental question:** Should heating/filter separation happen **directly in Loxone** (separate heating power marker without filter) instead of software-side via `subtract_consumer_ids`? Advantage: consistent live **and** historical data at the source.
  - Reference: case B correction (live actual) already implemented; thermal calibration see **Thermals P1** (Swim-Spa)



### Version 2.+1

- [ ] **Thermals P1** — Isolated single-node models
  - **Follow-up (1.26.0 P0 smoke, decision #11):** legacy RC / `thermal_control` models (SwimSpa, freezer, etc.) from `flexible_consumers` — not in 1.26.0 P3b
  - **Migrate existing consumers** — move prod entries from `config.json` → `flexible_consumers[]` into `house_profiles.json` (`profiles[].consumers[]`) where they belong in the planning model; keep live Loxone/MILP bindings explicit (no duplicate Hausprofil clutter); migration script or one-time cutover doc alongside new thermal schema (follow-up to **2.0 P6a** silent migration test)
  - Variable heat paths (against infinity); replaces single-path special case in `optimizer/thermal_model.py`
  - **Freezer** (former 0.+1 Prio2) — second isolated reference model; acceptance: calibration/backtest against historical Loxone CSV logs
  - Prerequisite for cost-shiftable house heating: **Thermals P1a** (below); RC SwimSpa path remains separate



### Version 2.+1

- [ ] **Thermals P1a — Haus Wärme MILP flex bridge** *(design 2026-07-13)*
  - **Problem:** `thermal_annual` („Haus Wärme“) is modeled as a **fixed** hourly PWM overlay (`thermal_daily_pwm_hourly_profile` → `thermal_hourly_overlay` → `expected_p_act`). Pulse **timing** is deterministic; MILP optimizes battery and other flex loads **around** it but cannot shift heating to cheaper hours. Production `waermepumpe` in `flexible_consumers[]` is a **separate** path (`daily_target_source: historical`) and is skipped when `flexible_consumers` is non-empty (`profile_manager` overlay gate).
  - **Goal:** Daily heating **energy** from the existing HDD/climate model (`daily_electric_kwh`); MILP chooses **when** to run 1–4 h ON pulses at `nominal_power_kw` to minimize cost (same semantics as other binary flex consumers).
  - **Prerequisite (done):** *Unified Open-Meteo solar* — shared Open-Meteo archive for HDD + solar-collector inputs ([Backlog-Erledigt.md](Backlog-Erledigt.md)); this chapter only adds MILP **pulse timing** flex (not climate/solar input alignment).
  - **Out of scope (Thermals P2+):** building RC model, room-temperature feedback, sub-hourly 0.5 h pulses, setpoint-only indirect control (see *Heat pump Prio3* below).
  - **Design — split demand vs schedule**
    - **Demand:** keep `daily_electric_kwh()` / `heating_params_from_thermal()` as daily kWh budget per calendar day (climate HDD, warm water, solar thermal, JAZ).
    - **Schedule:** remove fixed placement from baseload when MILP flex is active; MILP allocates binary ON slots instead of `thermal_daily_pwm_hourly_profile()`.
  - **Design — bridge** (`house_config/planning_flex_bridge.py`)
    - New `planning_thermal_to_milp(consumer) -> dict` (mirror `planning_consumer_to_milp` for generic):
      - `id`, `name`/`label`, `nominal_power_kw`, `min_power_kw` (= nominal), `signal_type: binary`, `optimizer_enabled: true`
      - `min_on_quarterhours: 4` (1 h minimum ON at hourly MILP resolution)
      - `daily_target_source: thermal_annual` (new resolver type)
      - `thermal_flex_window` (optional): default full day `{start_hour: 0, duration_h: 24}`; later restrictable (e.g. avoid night noise)
    - Extend `split_planning_generic_consumers` or add `split_planning_thermal_consumers(house_profile) -> list[dict]`; merge via existing `merge_flexible_consumers`.
    - Scenario resolution (`scenario_resolution.py`): append thermal MILP entries to `_planning_flex_consumers` alongside generic flex.
  - **Design — daily target** (`data/consumer_targets.py`)
    - New branch `daily_target_source == thermal_annual`: for slot date `D`, target kWh = `daily_electric_kwh(...)[day_index]` (day-of-year from climate series; backtesting uses slot calendar, live uses today).
    - Horizon spanning midnight: sum per calendar day inside window (same pattern as `planning_flex_daily_targets`).
  - **Design — MILP constraints** (`optimizer/milp_consumers.py` + new `optimizer/thermal_flex_context.py`)
    - Per calendar day within horizon: `sum(on[t] * nominal_kw) >= daily_target_kwh(day)` (existing delivery constraint, day-bounded indices).
    - **Max contiguous ON:** 4 h — new constraint on `consumer_on` runs (complement to `min_on_quarterhours`).
    - **Optional max pulses/day:** e.g. ≤ 4 runs to preserve PWM character (prevent single 8 h block when budget allows).
    - Values: only `0` or `nominal_power_kw` (binary flex; partial-hour tail only on last slot of a pulse if budget remainder < nominal — same as current PWM tail).
  - **Design — overlay / double-counting**
    - `house_profile_baseload_overlay` / `thermal_hourly_overlay`: **skip** `thermal_annual` consumers that are bridged to MILP (same mechanism as `skip_consumer_ids` for cons_data columns).
    - `profile_manager._apply_house_profile_baseload_overlay`: when thermal is MILP-flex, thermal kW comes from MILP plan in flex sum, not fixed overlay.
    - Backtesting `simulation/engine.py`: unchanged merge path — thermal energy in flex totals, not baseload adjustment.
  - **Design — house profile schema** (`house_profiles.schema.json`, Hauskonfigurator)
    - Optional on `thermal_annual` consumer: `optimizer_flex: true` (default `true` when `nominal_power_kw > 0`; `false` keeps current fixed PWM overlay for comparison/backward compat).
    - Optional `thermal_flex_window` object (same shape as generic `schedule` window fields).
  - **Design — live Loxone / prod migration**
    - Greenfield: single source in `house_profiles.json`; `flexible_consumers: []` — thermal flex via bridge only.
    - Prod cutover: migrate `waermepumpe` from `flexible_consumers[]` → house-profile consumer + retain `loxone_outputs`/`loxone_inputs` on bridged MILP entry (explicit binding table in migration doc); no duplicate IDs.
    - `house_config/migrate_runtime_entities.py`: map legacy `waermepumpe` → `thermal_annual` flex bridge when `house_profile_id` set.
  - **Design — tests & acceptance**
    - Unit: daily kWh preserved per day; pulse runs ∈ [1, 4] h; only 0 or nominal kW.
    - Backtesting with **dynamic** import tariff: MILP shifts heating away from expensive hours vs fixed PWM reference (same daily kWh).
    - Backtesting with **fixed** import tariff: Δ€ from heating timing ≈ 0 (sanity, aligns with SE fixed-tariff investigation).
    - Plausibility: optimized total kWh within tolerance; no baseload+flex double count.
    - Regression: `tests/test_price_pipeline_p3.py`, new `tests/test_thermal_flex_bridge.py`.
  - **Touches (estimate):** `planning_flex_bridge.py`, `scenario_resolution.py`, `consumer_targets.py`, `milp_consumers.py`, `thermal_flex_context.py` (new), `consumption_profiles.py` (overlay skip), `profile_manager.py`, `house_profiles.schema.json`, `ui/house_config_profile_form.py`, docs `flexible-verbraucher.md` (cross-link).
  - **Enables:** meaningful *Backtesting Tests — Test mit Standard-Setting (inkl. Haus Wärme)* (smoke follow-ups); replaces fixed P3b overlay path when `optimizer_flex: true`.



### Version 2.+1

- [ ] Define CSV data format for consumer annual demand (except house and EV) and provide import option (in addition to rated values). Annual profile from rated values can be compared graphically and in summary with measured profile.
- [ ] Set up debug page for Loxone communication showing read data with last update, whether data was sent to Loxone successfully (with value and timestamp — when silentmode==false)



### Version 2.+1

- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliances[].default_power_kw` from Loxone power markers (`loxone_power_name`) — reserved so far, no live use
  - Dishwasher power possibly via Hue



### Version 2.+1

- [ ] **Debug dump phase 2 — sharpen dump formats and reproduction**
  - Goal: a debug dump should make a case **traceable and as reproducible as possible** later without searching prod files again
  - Clearly separate dump types:
    - **Chart debug dump** for UI/display bugs
    - **Prod dump archive** for domain/optimizer-related failure cases
  - Per dump type define:
    - required files
    - optional additional files
    - manifest fields / schema
  - Evaluate whether a **replay/recalculation path** from a dump should be documented or partially automated
  - Add further inputs only if proven relevant for real failure cases



### Version 2.+1 — Epics **Adaptation** & **Thermals** (architecture first)

Recommended order: **SwimSpa case B** (optional precursor) → **Thermals P1a** (Haus Wärme MILP flex bridge) → **Thermals P1** (RC single-node models) → **Adaptation P1 → Adaptation P2 → Adaptation P3 → Thermals P2 → Thermals P3 → Adaptation P4**

- [ ] **Adaptation P1** — Generic adaptation model (skeleton)
  - Common structure for parameter adaptation of various forecast models:
    - Reference value (target for adaptation)
    - Variable parameters (with bounds)
    - Time horizon (e.g. 24 h for PV/freezer, 1 year for swim spa/house)
    - Start parameters from `config.json`; adaptation history **separate**; correct live parameters only when needed (rhythm oriented to horizon)
  - Target models (connect later): PV yield, thermal models, solar collector
  - **Precursor (done):** *Unified Open-Meteo solar* — shared archive bundle ([Backlog-Erledigt.md](Backlog-Erledigt.md))



### Version 2.+1

- [ ] **Adaptation P2** — PV adaptation (new approach) — first pilot on Adaptation P1
  - Replaces sidebar PV tuning (removed with UI Sunset-2-Sunset); see `runtime/pv_accuracy_log.csv`
  - Replace or integrate old `pv_tuner` path into Adaptation P1



### Version 2.+1

- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)



### Version 2.+1

- [ ] **Thermals P2** — Coupled single-node models
  - House ↔ heat storage ↔ solar system
  - House parameters from energy certificate (`C:\Users\joche\Documents\Hausbau\Hausbau_Köhler_Schreyögg\Energieausweis_komplett_EFH-Köhler_Dornbirn-2014.pdf`)
  - Prepare air conditioning as thermal consumer



### Version 2.+1

- [ ] **Thermals P3** — Thermal parameter adaptation (on Adaptation P1)
  - `heat_loss_kw_per_k` and further linear model parameters; horizon per consumer (24 h / 1 year)



### Version 2.+1

- [ ] **Adaptation P4** — UI visualization adaptation algos (after Adaptation P3 and Thermals P3)



### Version 2.+1

- [ ] Generic EV model — for better reusability



### Version 2.+1

- [ ] Better consumption optimization with temperature-control devices
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment via Loxone setpoint (after **Thermals P2**); distinct from **Thermals P1a** (direct enable/PWM flex from daily HDD budget)



### Version 2.+1

- [ ] Visualization of actual consumer behavior possibly with recommendations



### Version 2.+1

- [ ] **Optional: live planning horizon switchable via** `config.json` (`planning_horizon.mode`: `fixed_24h` | `sunrise_window`)
  - **Prerequisite:** Version 2.0 P4 rename done (`sunrise_window` in schema/code/docs)
  - After 2.0 rename: live only `sunrise_window` today; backtesting already supports both modes — live branching still to implement (`main.py`, `profile_manager`, UI chart, aWATTar window)
  - Mode `fixed_24h`**:** end-SOC behavior **fixed in mode** — economically equivalent to former `battery_end_soc_equals_start: true` (start SOC at horizon end), **or** introduce hard equality constraint via existing `battery_wear` penalty that appropriately "punishes" lower end SOC (choose one variant, not both in parallel)
  - Mode `sunrise_window`**:** unchanged **SOC_min at sunrise** (hard)
  - Extend spec, live tests for both modes



### Version 2.+1 — follow-ups (low priority; confirm after 2.0)

- [ ] **Recalculation "historical day" into backtesting** (dev-only)
  - Arbitrary calendar day from `cons_data_hourly.csv` + historical prices; implementation to clarify later (replaces sidebar mode "historical day")
- [ ] **Target/actual hint rules** — category "hint" once concrete non-critical cases identified (follow-up epic target/actual; after **Debug dump phase 2**)
- [ ] **Target/actual recalculation (backtesting)** — rule set batch-wise over historical JSONL / prod dumps; statistics per category (follow-up epic target/actual; after **Debug dump phase 2**)



## Packaging & Deployment

Recommended open order: **7e** → **7g**

- [x] **7a–7d** — pyproject, bootstrap, build pipeline, Streamlit external ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/dev data sync** — script runtime/ + CSVs; documented dev ↔ prod workflow
- [ ] **7g — Local dev stacks (staging, from 1.25)**
  **Scope:** Additional container stacks on **local dev PC** — **not** greenfield (**1.24.c**), **not** pytest fixture configs, **not** data sync (`7e`). `config/` remains untouched on image updates.
  **Phases:** 7g-a silent (prod Loxone) → 7g-b simulated (later).
  **Not a Version 2.0 gate** — P6a (NAS silent stack) done; 7g-a remains useful post-2.0 for local staging.
  **Acceptance:** silent stack reads productive Loxone instance, does not write (`loxone_silent_mode: true`); simulated stack only after Loxone simulator.
  - [ ] **7g-a — Silent stack** (prod Loxone, deploy-safe)
    - Own compose folder: separate `config/` + `runtime/`, distinct `container_name` and UI port
    - `runtime/local_settings.json`: `loxone_silent_mode: true` — read access to **productive Loxone instance**, no writes to miniserver/Huawei/consumers
    - Prod `config.json` as template or via `ENERGY_OPTIMIZER_CONFIG_PATH`; image updates (`pull`/`up -d`) do not overwrite existing `config/`
  - [ ] **7g-b — Simulated stack** (follow-up, after Loxone simulator)
    - Own stack without real Loxone connection; fully synthetic "house" (signals, consumers, possibly backtesting fixtures)
    - Prerequisite: Loxone simulator available — leave open until then



## Reference



### Log files (review 2026-06)


| File                                   | Status                     | Action                        |
| -------------------------------------- | -------------------------- | ----------------------------- |
| `runtime/optimization_history.jsonl`   | **canonical**              | Prod history                  |
| `runtime/earnie.log`                   | **active**                 | Rotating 5×5 MB               |
| `runtime/optimizer_run_state.json`     | **active**                 | Last main run                 |
| `runtime/live_optimization_debug.json` | **active**                 | App 24h debug                 |
| `runtime/system_history_log.csv`       | **legacy, read-only**      | Archive when JSONL sufficient |
| `runtime/pv_accuracy_log.csv`          | **read active, write off** | see epic **Adaptation P2**    |
| `backtesting_log.json`                 | **dev only**               | not for prod NAS              |


