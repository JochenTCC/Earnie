🗺️ Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)


## Feature Backlog


Scenario Exploration consumption model → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-13). Spec: [`docs/spec/scenario-exploration-consumption.md`](docs/spec/scenario-exploration-consumption.md).

Version **1.93** (unified scenario model) → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-14). **Live cutover (P6b)** → **1.99**.

Recommended order: **1.95–1.96** legacy flex / thermal migration (**1.97** ✓) → **1.99** P6b live cutover → propose `version.py` → **`2.0.0`** (user approval; **real** 2.0 — legacy data model gone).

Critical path: **1.95–1.96** (especially **Consumers P1** + **Thermals P1**) before **1.99** P6b prod cutover — **1.97** ✓ → [Backlog-Erledigt.md](Backlog-Erledigt.md). Open bugs → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).

**Implementation plan (1.95–1.99):** [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md) — prod consumer matrix, phased deliverables, acceptance, NAS cutover runbook. Track progress there; chapters below are index only.


### Version 1.95

- [ ] **Thermals P1** — Isolated single-node models + NAS prod consumer migration (Phases **1.95a–c** in plan) — core bridge landed → [Backlog-Erledigt.md](Backlog-Erledigt.md) (migrate_flex, SwimSpa 1.94, silent stack)
  - Freezer reference model + CSV backtest (second `thermal_rc` fixture)
  - **Gate:** Chart/Sankey parity → **Consumers P1 (1.96)** before prod cutover


### Version 1.96

- [ ] **Consumers P1** — Unified flex discovery (planning model → Chart 1 / Sankey) — Phase **1.96** in plan (P1a–P1d)
- [ ] **1.96d prod migration** — run `migrate_flex_consumers` on NAS/silent stack; confirm `appliances[]` retired in prod config (code → [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — suggested next steps)

### Execution of plan [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md)

Silent local abnahme stack → [Backlog-Erledigt.md](Backlog-Erledigt.md) (2026-07-14).

Manual validation (dynamic tariff, fixed tariff Δ€, SE `live`) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — manual validation (2026-07-14).

Suggested next steps (SE progress, diag tooling, 1.96d code, cutover runbook) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — suggested next steps (2026-07-14).

### Version 1.99 — Live cutover (former P6b)

- [ ] **P6b** — Non-silent NAS live cutover — Phase **1.99** in plan. **Prerequisite:** your sign-off after manual validation ([Backlog-Erledigt.md](Backlog-Erledigt.md) § NAS migration plan — manual validation); runbook [`docs/einrichtung/nas-live-cutover-1.99.md`](docs/einrichtung/nas-live-cutover-1.99.md). Open migration: **1.95** / **1.96** / **1.96d prod**.
- [ ] Set up debug page for Loxone communication showing read data with last update, whether data was sent to Loxone successfully (with value and ++++++++++++++++++++++++++++++++++++++++timestamp — when silentmode==false)
- [ ] File structure hygiene
  - Own directory for docker container stuff
  - Own directory for backlog stuff
  - Check if .py files in main directory should be kept there or move it to any subfolder also

## Real Version 2.0 — legacy data model removed

### Version 2.0

**Goal:** Legacy data model gone — see plan end state and [`docs/spec/nas-consumer-migration-1.95-1.99.md`](docs/spec/nas-consumer-migration-1.95-1.99.md).

**Prerequisite chain:** **1.93** ✓ → **1.95–1.96** (+ **1.96d prod**) → **1.99** P6b → propose `version.py` **`2.0.0`** (user approval). **1.97** ✓ → [Backlog-Erledigt.md](Backlog-Erledigt.md).

- [ ] Expand README with motivation / benefits — sensible order of use; less technical background than install/configuration hints

After **real** 2.0 release: dead code, obsolete tests, and leftover patches from pre-1.26.0 data model (1.26.0 P6 removed runtime fallbacks; this epic mops up the rest)


### Version 2.+1 — Quality epic / post-migration cleanup

- [ ] Evaluate option for code coverage testing and identification of deprecated code / tests (especially due to substantial data model change) / obsolete patches because of legacy data model
- [ ] Thorough code review and refactoring (with proper KPIs)
- [ ] Search for deprecated and unnecessary files and remove them
- [ ] Evaluate option for automated UI testing

- [ ] **Documentation & evaluations** *(former 1.93 P7 / former backlog 1.99 docs)*

  - Build additional container for Windows as pure Python environment (if that makes sense) — spike vs local venv; go/no-go note
  - Evaluate running Scenario-Exploration as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility


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


### Version 2.+1

- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
  - Consumers can be marked as "controlled by Earnie" or just "known by Earnie"

### Version 2.+1

- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliance_recommendation.default_power_kw` from Loxone power markers (`loxone_power_name`) on house-profile generics — reserved so far, no live use
  - Dishwasher power possibly via Hue


### Version 2.+1 — Epics **Adaptation** & **Thermals** (architecture first)

Recommended order: **Adaptation P1 → Adaptation P2 → Adaptation P3 → Thermals P2 → Thermals P3 → Adaptation P4** (precursors **Consumers P1**, **Thermals P1**, **Thermals P1a** → **1.95–1.97**; **P1a** ✓ Erledigt; before **1.99** live cutover / real 2.0)

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
  - **Prerequisite:** **1.93 P4** rename done (`sunrise_window` in schema/code/docs)
  - After **1.93 P4** rename: live only `sunrise_window` today; backtesting already supports both modes — live branching still to implement (`main.py`, `profile_manager`, UI chart, aWATTar window)
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
  **Not a real Version 2.0 gate** — P6a (NAS silent stack) done; 7g-a remains useful post-**2.0** for local staging.
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


