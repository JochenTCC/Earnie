🗺️ Project Roadmap & Backlog

Completed items → [Backlog-Erledigt.md](Backlog-Erledigt.md)

Open bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md)

## Research Items
- [ ] Review Smart Energy app for comparison
- [ ] Review other providers with flexible prices
- [ ] Adapt business plan
- [ ] **Outreach (not software):** Ask for interested parties in loxforum / reddit — post under “my project”; take interesting chart snapshots (loxforum admins contacted re. best place)

### Loxberry 4 Installation — Notes
- [x] Update from existing Loxberry to 4.0 worked
- [x] Installation of Docker Container plugin worked
- [x] Ernie stack commissioning worked and worker / UI are running!!!

## Feature Backlog

### Version 1.26.0 — Runtime entities & tariffs (live)

**Strategy:** Greenfield-first (1.24.c), then prod cutover, then legacy removal.
- **P0–P4:** implement and accept on `greenfield/` (ID-only `runtime_settings`; no flat battery/PV/tariff/geo duplicates) — **done**
- **P5:** prod migration + live acceptance (NAS or **7g-a** silent stack with prod `config/` copy).
- **P6:** remove legacy code paths and schema fields (breaking for unmigrated configs).

**Scope:** Live prod (`main.py`, Sunset-2-Sunset UI) uses the same reference resolution as backtesting (1.24). `runtime_settings` holds only selection IDs (+ optional `pv_system_id`). Geo/timezone from `house_profile_id` → `house_profiles.json`. Technical parameters from `batteries[]`, `pv_systems[]`, `config/tariffs.json`. **Out of scope:** full migration of live `flexible_consumers` to house profiles. **In scope (minimal):** thermal overlay from `house_profile_id` in live baseload (P2/P3 — define before coding).

**Phases:** P1 data model → P2 config.py resolution → P0 greenfield pilot (smoke ✅) → P3 price pipeline live (+ P3a/P3b) → P4 UI ✅ → P5 prod cutover → P6 legacy removal.

**Acceptance:** greenfield: live optimization + backtesting share one resolution path; prod: migrated `config.json` with IDs only; backtesting baseline unchanged; no flat-field fallbacks remain after P6.

**Decisions (locked 2026-07-11):**

| # | Topic | Decision |
|---|--------|----------|
| 1 | P0 timing | After P2 — config cleanup + checklist doc early; live smoke once `resolve_runtime_settings()` is wired |
| 2 | Fallback (until P6) | Greenfield: IDs required, no flat dupes; prod until P5: ID wins, else legacy flat fields |
| 3 | `battery_wear` | On selected `batteries[]` entry only after P1 — **no global fallback** |
| 4 | Import `monthly_table` | New type with `monthly_rates` (symmetric to export); `monthly_market` stays as spot-variant label |
| 5 | `awattar` surcharges | Move from top-level `config.json` into `tariffs.json` per import tariff (not global `awattar` block) |
| 6 | P5 migration | Script generates draft config → manual review before deploy |
| 7 | P5 acceptance | **7g-a** silent stack first (build as part of P5), then NAS |
| 8 | `flexible_consumers` | No full profile migration; minimal thermal bridge from `house_profile_id` (P2/P3) |
| 9 | `version.py` | Bump to 1.26.0 only after full P0–P6 cycle (explicit user approval) |
| 10 | Docs (P5) | Update [`docs/konfiguration/ueberblick.md`](docs/konfiguration/ueberblick.md) / [`preise.md`](docs/konfiguration/preise.md) in German — content only, no translation |
| 11 | Legacy thermal models (RC / `thermal_control`) | **Option A:** defer to **Thermals P1** (2.+1); 1.26.0 only minimal bridge via **P3b** (Haus Wärme on/off at `nominal_power_kw`) |

- [ ] **P5 — Prod cutover (migration, tests, docs)**
  - Migration script: prod flat values → draft `batteries[]` / `pv_systems[]` + tariff IDs in `tariffs.json`; `runtime_settings` stripped to IDs only; migrate geo/timezone into selected `house_profiles.json` entry — **manual review before deploy**
  - Migrate global `battery_wear` → selected `batteries[]` entry (in script output)
  - Build/use **7g-a** silent stack for acceptance (prod Loxone read-only) before NAS deploy
  - Tests in [`tests/test_house_config.py`](tests/test_house_config.py) + live resolution test
  - Docs (German, content update only): [`docs/konfiguration/ueberblick.md`](docs/konfiguration/ueberblick.md), [`preise.md`](docs/konfiguration/preise.md), sidebar note
  - Follow-up link: Version 1.+1 “Include tariffs.json in deploy”
- [ ] **P6 — Legacy removal (no fallbacks)**
  - Remove flat-field fallback in entity/tariff resolution
  - Remove global `battery_wear` and top-level `awattar` block support; require per-battery wear and per-tariff awattar fields
  - Deprecate/remove from schema: `runtime_settings` flat battery/PV/tariff fields, `feed_in_mode`, `k_push_cent`
  - Update [`config/config.example.json`](config/config.example.json) to ID-only `runtime_settings`


### Version 1.+1
- [ ] rename sunset_window to sunrise_window - and all belonging namings to avoid further irritation.
- [ ] Check tariffs.json for "completeness": are all data from "einspeisetarife*.json" from Gemini included?
- [ ] **Tariff plausibility check** before backtesting start
- [ ] Include tariffs.json in deploy
- [ ] Create plausibility test for tariffs.json that runs before deploy
- [ ] Expand README with motivation / benefits
  - Describe sensible order of use
  - Less technical background than hints for installation and configuration
- [ ] Build additional container for Windows as pure Python environment (if that makes sense)
- [ ] Evaluate running as "web app" in Streamlit Community Cloud

### Version 1.+1
- [ ] **EV MILP: optional follow-up work**

### Version 2.0 — Quality epic
- [ ] Thorough code review and refactoring
- [ ] Search for deprecated and unneccessary files and remove them
- [ ] Evaluate option for code coverage testing
- [ ] Evaluate option for automated UI testing

### Version 2.+1
- [ ] Offer backtesting with scenarios on Streamlit Community Cloud to generate leads and possibly as affiliate source (when switching electricity provider or contacting PV installers)

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
- [ ] Define CSV data format for consumer annual demand (except house and EV) and provide import option (in addition to rated values). Annual profile from rated values can be compared graphically and in summary with measured profile.
- [ ] Set up debug page for Loxone communication showing read data with last update, whether data was sent to Loxone successfully (with value and timestamp — when silentmode==false)

### Version 2.+1 — Decouple test config
- [x] **Stage 1 — Standard test config in `conftest.py`**
  - `ENERGY_OPTIMIZER_CONFIG_PATH` → `tests/fixtures/backtesting/config.json` (enforce, except `ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1`)
  - `ENERGY_OPTIMIZER_OFFLINE=1` as test default; `config.reinit_config()` at conftest start
  - Backtesting fixture config extended with `chart_color_index`
- [x] **Stage 1b — fix broken tests**
  - `test_config_charge_immediate.py`: inline `tmp_path` config instead of implicit prod values
  - `test_matched_baseline.py`: EV consumer as inline fixture instead of `config.get_flexible_consumers()`
- [ ] **Stage 2 — generalize `activate_test_config()`** (derive from `activate_backtesting_fixtures`; purpose-specific mini-configs under `tests/fixtures/config/`)
- [ ] **Stage 3 — separate test types** (config loader vs. domain vs. UI patch; no bare `config.get_*()` without fixture)
- [ ] **Stage 4 — marker `requires_live_config`** for NAS/prod integration runs (`ENERGY_OPTIMIZER_TEST_USE_LIVE_CONFIG=1`; `@requires_loxone` already uses this switch)
- [ ] **Stage 5 (optional) — config only at edges** (pure functions with `consumers`/`battery_params` as parameters)

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

Cross-phase validation: **recalculation "historical day"** (0.+1, dev-only) and existing thermal backtests.

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
  - **Swim spa:** second heat path into ground (lookup `bodentemperaturen_nach_monat`):
    - 1: 6.5, 2: 5.0, 3: 4.0, 4: 5.5, 5: 8.5, 6: 11.5, 7: 14.0, 8: 16.0, 9: 17.5, 10: 15.5, 11: 12.5, 12: 9.5 (°C)
  - **Freezer** (former 0.+1 Prio2) — second isolated reference model
  - Acceptance: calibration/backtest against historical Loxone CSV logs

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
- [ ] Add configuration page for easy editing of `config.json` and scenarios

### Version 2.+1
- [ ] Design what-if assistants for backtesting:
  - would Ernie pay off (with aWATTar)?
  - would (more) battery pay off?
  - query consumers and generate consumer profiles from them
- [ ] Reminder at month start for feed-in price (email from Loxone!)

### Version 2.+1
- [ ] **Optional: live planning horizon switchable via `config.json`** (`planning_horizon.mode`: `fixed_24h` | `sunset_window`)
  - Currently live only `sunset_window` (schema/code); backtesting already knows both modes — live branching still to implement (`main.py`, `profile_manager`, UI chart, aWATTar window)
  - Mode **`fixed_24h`:** end-SOC behavior **fixed in mode** — economically equivalent to former `battery_end_soc_equals_start: true` (start SOC at horizon end), **or** introduce hard equality constraint via existing **`battery_wear`** penalty that appropriately "punishes" lower end SOC (choose one variant, not both in parallel)
  - Mode **`sunset_window`:** unchanged **SOC_min at sunrise** (hard)
  - Extend spec, live tests for both modes

### Version 2.+1 (Still needed???)
- [ ] **Recalculation "historical day" into backtesting** (dev-only)
  - Arbitrary calendar day from `cons_data_hourly.csv` + historical prices; implementation to clarify later (replaces sidebar mode "historical day")
- [ ] **Target/actual hint rules** — category "hint" once concrete non-critical cases identified (follow-up epic target/actual)
- [ ] **Target/actual recalculation (backtesting)** — rule set batch-wise over historical JSONL / prod dumps; statistics per category (follow-up epic target/actual)


## Packaging & Deployment

Recommended open order: **7e** → **7g**

- [x] **7a–7d** — pyproject, bootstrap, build pipeline, Streamlit external ([container.md](docs/einrichtung/container.md))
- [ ] **7e — Prod/dev data sync** — script runtime/ + CSVs; documented dev ↔ prod workflow
- [ ] **7g — Local dev stacks (staging, from 1.25)**

  **Scope:** Additional container stacks on **local dev PC** — **not** greenfield (**1.24.c**) and **not** pytest fixtures (`Version 2.+1 — Decouple test config`) and **not** data sync (`7e`). `config/` remains untouched on image updates.

  **Phases:** 7g-a silent (prod Loxone) → 7g-b simulated (later).

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

| File | Status | Action |
|------|--------|--------|
| `runtime/optimization_history.jsonl` | **canonical** | Prod history |
| `runtime/energy_optimizer.log` | **active** | Rotating 5×5 MB |
| `runtime/optimizer_run_state.json` | **active** | Last main run |
| `runtime/live_optimization_debug.json` | **active** | App 24h debug |
| `runtime/system_history_log.csv` | **legacy, read-only** | Archive when JSONL sufficient |
| `runtime/pv_accuracy_log.csv` | **read active, write off** | see epic **Adaptation P2** |
| `backtesting_log.json` | **dev only** | not for prod NAS |
