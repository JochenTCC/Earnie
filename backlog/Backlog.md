🗺️ Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items

- [ ] **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
  - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)
  - Evaluate running Scenario-Exploration as "web app" in Streamlit Community Cloud — secrets, no Loxone, demo feasibility
- [ ] Add a predictive model for Grundlast with logged Grundlast from the past. Research for Models (AI?). Take date / average temperature / week day / and other factors into account


## Feature Backlog


## Real Version 2.0 — legacy data model removed

### Version 2.0

After **real** 2.0 release: dead code, obsolete tests, and leftover patches from pre-1.26.0 data model (1.26.0 P6 removed runtime fallbacks; this epic mops up the rest)


### Version 2.+1 — Quality epic / post-migration cleanup

- [ ] Evaluate option for code coverage testing and identification of deprecated code / tests (especially due to substantial data model change) / obsolete patches because of legacy data model
- [ ] Thorough code review and refactoring (with proper KPIs)
- [ ] Search for deprecated and unnecessary files and remove them
  - Code for migration from V 1.x to 2.0 is not needed anymore
- [ ] Evaluate option for automated UI testing
- [ ] **Documentation & evaluations** *(former 1.93 P7 / former backlog 1.99 docs)*



### Version 2.+1

- [ ] Make main.py controllable from streamlit.app (Checks must be included if main.py is runnin already, if necessary change spec / doc and put it in one container as deamon or so)
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

- [ ] Make appropriate information accessible to user about where differences between optimized SOC and BL SOC Ziel come from to give him explanation (prove plausability)
- [ ] Enhance data model to nested structures. E.g. pool can consist of multiple "inner" consumers or house consists also of multiple "inner" consumers
- Consumer role model (`earnie_role`: known / flex / manual) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § Generic `earnie_role` (2026-07-15); nested inner consumers remain open
- [ ] Check if removing constraint for SOC at end of horizon changes simulation resulst in backtesting


### Version 2.+1

- [ ] **Recommendation mode smart/adaptive devices** (follow-up to recommendation mode manual devices)
  - Adaptive re runtime/energy per run; smart devices instead of manual input
  - Adaptation algo maintains `appliance_recommendation.default_power_kw` from Loxone power markers (`loxone_inputs.power_name`) on house-profile generics — reserved so far, no live use
  - Use Loxone power markers also for Sankey-Diagram for further differentation of defined consumers
  - Dishwasher power possibly via Hue


### Version 2.+1 — Epics **Adaptation** & **Thermals** (architecture first)

Recommended order: **Adaptation P1 → Adaptation P2 → Adaptation P3 → Thermals P2 → Thermals P3 → Adaptation P4** (precursors **Consumers P1**, **Thermals P1**, **Thermals P1a** → **1.95–1.97** ✓; **1.99** P6b ✓)

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
  - Sidebar PV tuning removed (UI S-2 P1 + 2026-07-15 code path) → [Backlog-Erledigt.md](Backlog-Erledigt.md) § PV tuning removal; see `runtime/pv_accuracy_log.csv`
  - Replace or integrate old `pv_tuner` path into Adaptation P1 (`pv_tuner.py` counter delta only)



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


