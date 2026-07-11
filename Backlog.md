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

## Feature Backlog

### Version 2.0

Branding (Earnie rename) → [Backlog-Erledigt.md](Backlog-Erledigt.md).

**Status (2026-07-11):** P1–P5 done (see [Backlog-Erledigt.md](Backlog-Erledigt.md)). Greenfield smoke test completed — follow-ups in [Backlog-Bugfixes.md](Backlog-Bugfixes.md) and below.

Recommended order: **P6** prod NAS cutover → **P7** README / evaluations.

Critical path: **P6**. Smoke-test bugs → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

**Decisions (2026-07-11):**


| Topic                            | Decision                                                                                                                                                                              |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `EARNIE_UI_MODES` key            | Hard rename `backtesting` **→** `scenario_exploration` — no alias; update compose, launch configs, docs, tests in same PR (P2)                                                        |
| Scenario id `runtime_settings`   | **Remove in 2.0** — live baseline is a normal scenario entry (default id `live`) selected via `live_scenario_id` in `config.json`; update scripts/tests/fixtures in same release (P2) |
| Battery without PV               | **Allowed** — battery still required for MILP / planning readiness; PV optional (zero PV forecast when `pv_system_id` unset) (P1)                                                     |
| **7g-a** before P6               | **Skip for 2.0** — direct NAS cutover after P5; 7g-a remains in Packaging backlog, not a 2.0 gate                                                                                     |
| `**sunrise_window` rename (P4)** | Hard rename `sunset_window` **→** `sunrise_window` — no alias; internal symbols renamed; prod deploy only with P6 config migration                                                    |


- [ ] **Version 2.0 P6 — Prod NAS cutover**
  - Apply migrated config per `[migrated/MIGRATION_REVIEW.md](migrated/MIGRATION_REVIEW.md)` and `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)` (1.26.0 P5)
  - **Direct NAS cutover** after P5 — no 7g-a gate for 2.0; live acceptance on prod NAS
  - Propose `version.py` → `2.0.0` only after P6 acceptance (user approval required)

- [ ] **Version 2.0 P7 — Documentation & evaluations**
  - Expand README with motivation / benefits — sensible order of use; less technical background than install/configuration hints
  - Build additional container for Windows as pure Python environment (if that makes sense) — spike vs local venv; go/no-go note
  - Evaluate running Scenario-Exploration as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility

### Version 2.0 — smoke-test follow-ups (non-blocking for P5/P6)

- [ ] **Scenario-Exploration without PV** — optimization/backtesting path incomplete when `pv_system_id` unset (P1 allows battery-only; simulation/MILP gaps remain — defer to **Thermals** / **Adaptation** epics unless blocking prod cutover)

### Version 2.+1 — Quality epic / post-migration cleanup

After 2.0 release: dead code, obsolete tests, and leftover patches from pre-1.26.0 data model (1.26.0 P6 removed runtime fallbacks; this epic mops up the rest)

- [ ] Evaluate option for code coverage testing and identification of deprecated code / tests (especially due to substantial data model change) / obsolete patches because of legacy data model
- [ ] Thorough code review and refactoring
- [ ] Search for deprecated and unneccessary files and remove them
- [ ] Evaluate option for automated UI testing

### Version 2.+1

- [ ] Define CSV data format for consumer annual demand (except house and EV) and provide import option (in addition to rated values). Annual profile from rated values can be compared graphically and in summary with measured profile.
- [ ] Set up debug page for Loxone communication showing read data with last update, whether data was sent to Loxone successfully (with value and timestamp — when silentmode==false)

### Version 2.+1

- [ ] **SwimSpa case B — follow-up review historical power & Loxone separation**
  - Check whether historical SwimSpa power logs (`thermal_control.history_logs.power_csv` = `..._SwimSpa_Leistung_...csv`, source `Ernie_Swim-Spa-P_act`) also contain the **filter share** (case B). If yes: assess impact on **thermal model calibration** (`heat_loss_kw_per_k` etc.) — filter (~0.18 kW) would be misinterpreted as heating power.
  - **Fundamental question:** Should heating/filter separation happen **directly in Loxone** (separate heating power marker without filter) instead of software-side via `subtract_consumer_ids`? Advantage: consistent live **and** historical data at the source.
  - Reference: case B correction (live actual) already implemented; thermal calibration see **Thermals P1** (Swim-Spa)

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

Recommended order: **Adaptation P1 → Adaptation P2 → Adaptation P3 → Thermals P1 → Thermals P2 → Thermals P3 → Adaptation P4**

- [ ] **Adaptation P1** — Generic adaptation model (skeleton)
  - Common structure for parameter adaptation of various forecast models:
    - Reference value (target for adaptation)
    - Variable parameters (with bounds)
    - Time horizon (e.g. 24 h for PV/freezer, 1 year for swim spa/house)
    - Start parameters from `config.json`; adaptation history **separate**; correct live parameters only when needed (rhythm oriented to horizon)
  - Target models (connect later): PV yield, thermal models, solar collector

### Version 2.+1

- [ ] **Adaptation P2** — PV adaptation (new approach) — first pilot on Adaptation P1
  - Replaces sidebar PV tuning (removed with UI Sunset-2-Sunset); see `runtime/pv_accuracy_log.csv`
  - Replace or integrate old `pv_tuner` path into Adaptation P1

### Version 2.+1

- [ ] **Adaptation P3** — Adaptation algorithm (PV pilot)
  - Concrete update loop on Adaptation P2; thermal models remain **linear** (thermal adaptation only in Thermals P3)

### Version 2.+1

- [ ] **Thermals P1** — Isolated single-node models
  - **Follow-up (1.26.0 P0 smoke, decision #11):** legacy RC / `thermal_control` models (SwimSpa, freezer, etc.) from `flexible_consumers` — not in 1.26.0 P3b
  - Variable heat paths (against infinity); replaces single-path special case in `optimizer/thermal_model.py`
  - **Freezer** (former 0.+1 Prio2) — second isolated reference model; acceptance: calibration/backtest against historical Loxone CSV logs

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
  - [ ] Heat pump (Prio3) — only indirect control via setpoint adjustment (after **Thermals P2**)

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
  **Not a Version 2.0 P6 gate** — NAS cutover proceeds directly after P5; 7g-a remains useful post-2.0 for staging.
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


