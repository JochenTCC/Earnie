# Completed Items

Archive of completed work. Open todos → [Backlog.md](Backlog.md) · Bugfixes → [Backlog-Bugfixes.md](Backlog-Bugfixes.md).



## EV: urgent rule, prod dump, PWM
Related topics — prioritize and work through together.

- [x] **Urgent rule observability review** (by approx. **2026-07-12**, after prod acceptance)
  - Constraint removed → evaluate `urgent_rule_observability` in log + `optimization_history.jsonl` (`role`: expected `redundant`)
  - Acceptance: consistently `redundant` over several charge cycles → close review, simplify observability logging if applicable
- [x] **PWM for EV charging** — only for currents < A_min; otherwise minimum charge amount per h (count down meter, reset on each charge → at zero charge charge five minutes at minimum current)


### Version 1.93 — Unified Open-Meteo solar (2026-07-13)

PV (`pv_kw`) and Solar-Kollektor (Haus Wärme) share the **same Open-Meteo archive weather** on the **same calendar hours** — no static `heating_climate_default.json` fixture, no `2023-01-01 % 8760` slot mapping, no measured Loxone PV in backtesting/synthesis paths. Commit `575c610`.

**Decisions:**


| Topic | Decision |
| ----- | -------- |
| PV source (backtesting + synthetic `cons_data`) | **Open-Meteo only** |
| Open-Meteo API failure | **Fail hard** — no fixture/synthetic fallback on this path |
| Hauskonfigurator annual preview | **Last full archive calendar year** at profile lat/lon |


- [x] **Step 1 — Bundle + `heating_need` hourly path** — `OpenMeteoClimateBundle`, `irradiance_wm2_to_thermal_kwh`, `daily_electric_kwh(..., hourly_collector_wm2=…)`; tests with mocked HTTP
- [x] **Step 2 — cons_data synthesis + backtesting overlay** — [`data/modeled_climate.py`](data/modeled_climate.py), [`data/cons_data_house_profile.py`](data/cons_data_house_profile.py), [`scripts/generate_cons_data.py`](scripts/generate_cons_data.py), slot-aligned thermal in [`house_config/planning_flex_bridge.py`](house_config/planning_flex_bridge.py) / [`data/consumption_profiles.py`](data/consumption_profiles.py); Open-Meteo PV in [`simulation/engine.py`](simulation/engine.py) when `scenario_params` set
- [x] **Step 3 — Hauskonfigurator preview + cache** — `thermal_annual_kwh_from_archive()`; JSON cache under `data/cache/open_meteo/`; WP metric caption with reference year
- [x] **Tests** — [`tests/test_open_meteo_solar_archive.py`](tests/test_open_meteo_solar_archive.py), [`tests/test_modeled_climate.py`](tests/test_modeled_climate.py), [`tests/test_heating_need_solar.py`](tests/test_heating_need_solar.py), [`tests/test_cons_data_calendar_alignment.py`](tests/test_cons_data_calendar_alignment.py); offline mock [`tests/fixtures/open_meteo_mock.py`](tests/fixtures/open_meteo_mock.py)

**Smoke verification (manual):** Phase A complete → *Smoketest Phase A — Open-Meteo solar* below.

**Deferred to other chapters:** **Thermals P1a** (MILP pulse timing, **1.98**) · **P6b** (live `main.py` Loxone `cons_data` append cutover, **1.94**)


### Version 1.93 — Scenario Exploration consumption model (2026-07-13)

Baseline vs optimized load separation for SE / greenfield backtesting. Spec: [`docs/spec/scenario-exploration-consumption.md`](docs/spec/scenario-exploration-consumption.md).

- [x] **Step 1 — Targets & matrix input** — `consumer_daily_targets_kwh` from `planning_flex_daily_targets`; baseload from house-profile overlay; `consumption_source=profile_spec` default for greenfield/SE
- [x] **Step 2 — Plausibility & reference** — plausibility vs profile-spec totals; `compute_historical_reference_costs` with scenario tariffs; `build_per_scenario_reference_costs` + `reference_by_scenario`
- [x] **Step 3 — UI** — baseline (dashed) vs optimized per scenario; consumption debug Δ kWh (`ui/backtesting_scenario_consumption.py`)
- [x] **Step 4 — Greenfield flex registration** — `standard`, `waschmaschine`, `ev` MILP-flex documented; scenarios `live` / `s3-no-battery` in greenfield matrix
- [x] **Window-aware targets** — partial-day generic/EV flex at 07:00 anchors (`generic_flex_target_kwh_for_window`, `planning_ev_daily_targets`); tests [`tests/test_generic_flex_window_targets.py`](tests/test_generic_flex_window_targets.py)
- [x] **Tests** — [`tests/test_planning_matrix_profile_spec.py`](tests/test_planning_matrix_profile_spec.py), [`tests/test_consumption_display_integration.py`](tests/test_consumption_display_integration.py), backtesting smoke extensions

**Enables:** meaningful battery/PV scenario comparison; remaining plausibility gaps → smoke-test Phase B in [`Backlog-Erledigt.md`](Backlog-Erledigt.md).


### Version 1.93 — smoke-test follow-ups (2026-07-14)

Greenfield smoke **2026-07-12**; backtesting iteration **2026-07-13**; chapter closed **2026-07-14**. Related smoketest phases A–C → sections above in this archive.

- [x] **Scenario-Exploration without PV** — optimization/backtesting path complete when `pv_system_id` unset (battery-only MILP/simulation gaps closed on top of P1 optional-PV baseline)
- [x] **EV nominal voltage for power calculation** — configurable per EV consumer (`charging_schedule.nominal_power_voltage_v` / `nominal_power_phases`, house profile + `flexible_consumers`); shared helper [`settings/ev_power.py`](settings/ev_power.py) for live (`integrations/loxone_client.py`) and planning (`house_config/planning_flex_bridge.py`); default 230 V / 1 phase when unset; schemas, Hauskonfigurator UI, [`docs/referenz/loxone-signale.md`](docs/referenz/loxone-signale.md); tests [`tests/test_ev_power.py`](tests/test_ev_power.py)

Components (`components.json` sidecar) → *Version 1.93 Components* above.


### Smoketest backtesting — greenfield runs (2026-07-13)

- [x] **Jan 2025 `fixed_24h` run** — `live` + `s3-no-battery`, 31 windows; `reference_by_scenario` populated; optimization < reference € on `awattar_at` import
- [x] **cons_data + Open-Meteo cache** — greenfield synthesis regenerated; cache entry under `data/cache/open_meteo/`


### Smoketest Phase B — fixed tariffs & plausibility (2026-07-13)

Greenfield matrix: `greenfield/config/backtesting_scenarios.json` — `live`, `s2-kein-pv`, `s3-no-battery`, `s1-kein-pv-keine-battery`.

- [x] **Fixed-tariff scenario matrix in greenfield** — `live` (full), `s2-kein-pv` (no PV), `s3-no-battery` (no battery), `s1-kein-pv-keine-battery` (no PV, no battery) with `fixed_25ct` / `fixed_37ct` in `greenfield/config/backtesting_scenarios.json`; run `--horizon-mode fixed_24h`
  - Created all scenarios in local greenfield env
  - Made test backtesting calculation (January 2025)
  - Finding: `s2-kein-pv` / `s1-kein-pv-keine-battery` show higher costs than baseline that is with PV --> Take PV out of baseline
  - Notice: "Zeitverschiebung (Energie ≈ Spec)" - what does that mean? --> More precise wording
- [x] **Bulk classify** — per scenario: plausibility ok/total, Δ€ vs matched reference, deviation kinds; tool: `scripts/analyze_plausibility_failures.py`
- [x] **Structural flex under-delivery (`s2-kein-pv` Jan 2 & 7)** — Phase 1 done: rolling `min_on` continuation in MILP. Spec: [`docs/spec/backtesting-plausibility-s2-kein-pv-jan-2-7.md`](docs/spec/backtesting-plausibility-s2-kein-pv-jan-2-7.md#phase-1-implementation-2026-07-13)


### Smoketest Phase B — Variable tariff scenario (2026-07-13)

- [x] **Check scenario results**
  - [x] one deviation - to be checked (5.10.25)
    - Fenster: 2025-10-04 07:00 – 2025-10-05 07:00 · Szenario: S2-kein-PV · Art: CBC strict (langsam) · Δ kWh (Soll/Ist): —
    - Fenster: 2025-10-04 07:00 – 2025-10-05 07:00 · Szenario: Live · Art: CBC strict (langsam) · Δ kWh (Soll/Ist): —
    - Issues arise from very flat and low price line
  - [x] Chart 1 — house-profile flex consumers not shown separately (**investigated 2026-07-13**)
    - **Calculation OK** — snapshot/matrix columns (`Standard (kW)`, `Waschmaschine (kW)`, `EV (kW)`) and plausibility targets correct; `meta._flexible_consumers` populated
    - **UI gap** — Chart 1 uses `get_flexible_consumers(optimizer_only=True)`; bridged generics fail `consumer_has_daily_target()` → only EV rendered; hidden flex misattributed in flow-balance down-stack (thermal `haus` correctly in Grundlast)
    - **Fix** — **1.97 Consumers P1** (with **Thermals P1** migration, **1.96**); not automatic after storage consolidation alone


### Smoketest Phase C — polish follow-ups (2026-07-13)

- [x] **Live scenario default** — `Detaillierte Simulationsansicht` wählt `live_scenario_id`, wenn am Tag keine Abweichung markiert ist (`ui/backtesting_deviation_list.py`)
- [x] **Hauskonfigurator Speichern** — sticky Speichern-Leiste + doppeltes Speichern vor Vorschau-Charts (Hausprofil); sticky auf PV/Batterien (`ui/house_config_sticky_save.py`)
- [x] **Loxone Ist-SOC E-Auto** — optionales `charging_schedule.loxone.actual_soc_name` (z. B. `Ernie-SOC-Ist-EAuto`); Vergleich mit berechnetem Session-SOC; bei Ziel-SOC keine weitere Ladung (`optimizer/ev_soc_tracking.py`, `optimizer/delivery_tracking.py`)


### Smoketest Phase C — SE layout polish (2026-07-13)

- [x] Remove Referenz-Jahresverbrauch (nicht optimiert) charts from SE
- [x] Remove Optimierter Verbrauch vs. Profil-Baseline charts from SE
- [x] Move Monatlicher Kostenvergleich directly below Gesamtkosten
- [x] Move Abweichungsliste to the bottom of SE
- [x] Add Referenz and Ohne Optimierung to Gesamtkosten table


### Smoketest Phase A — Open-Meteo solar (2026-07-13)

Manual acceptance on greenfield venv (:8511); implementation in *Unified Open-Meteo solar* above.

- [x] **Regenerate `cons_data` + Open-Meteo cache** — `data/cache/open_meteo/` populated (greenfield 2026-07-13)
- [x] **Backtesting smoke** — Jan 2025 `fixed_24h`, scenarios `live` + `s3-no-battery` (31 windows; optimization cheaper than reference on `awattar_at`)
- [x] **July 2024 calendar alignment** — spot-check `cons_data_hourly.csv`: `pv_kw` / `haus_kw` peaks on 2024-07 hours (no modulo drift)
- [x] **Solar-Kollektor** — `solar_thermal_area_m2` > 0 lowers summer midday `haus_kw` vs 0 m²
- [x] **Hauskonfigurator WP preview** — caption shows Open-Meteo archive year; collector area reduces estimated kWh/a
- [x] **Fail-hard (offline)** — internet disabled before `cons_data` generation: `requests.ConnectionError` on `archive-api.open-meteo.com` (DNS `getaddrinfo failed`); no fallback to `heating_climate_default.json`; surfaces at config reload via `thermal_annual_kwh_from_archive()` during profile normalization


### cons_data PV via Open-Meteo Solar Archive (2026-07-13, superseded)

Superseded for SE/backtesting/synthesis by *Unified Open-Meteo solar* above. Legacy `build_open_meteo_pv_lookup` fallback curve remains only on old cons_data paths.

- [x] **Backtesting cons_data PV** — initial `data/open_meteo_solar_archive.py` + `scripts/generate_cons_data.py` integration
- [x] **Tests** — `tests/test_open_meteo_solar_archive.py` (extended in unified chapter)


### Smoketest bugfix — Hausprofil Bezeichnung (2026-07-12)

- [x] **Bezeichnung** empty when switching Scenario-Exploration → Hauskonfigurator — greenfield smoke 2026-07-12
- [x] **Fix:** `_sync_profile_session` re-seeds scoped widget state when keys are dropped after page navigation (`_profile_widget_state_missing` in `ui/house_config_profile_form.py`)
- [x] **Tests:** `tests/test_planning_editors.py` (`test_sync_profile_session_reseeds_when_widget_keys_missing`, `test_seed_profile_widget_state_uses_existing_annual_kwh`)


### Smoketest UX — Szenarieneditor (2026-07-12)

- [x] **Move "Hausprofil" to top of Szenarieneditor** — field order in `ui/pages/page_scenario_editor.py` (Hausprofil before Batterie/PV/Tarife)
- [x] **Enable saving new scenarios** — session-scoped widget keys + live-scenario template for `— neu —`; duplicate-ID guard; select switches to saved scenario (`ui/scenario_form_helpers.py`, `ui/pages/page_scenario_editor.py`)
- [x] **Tests:** `tests/test_scenario_form_helpers.py`, `tests/test_planning_editors.py` (`test_upsert_scenario_appends_new_entry`)


### Smoketest UX — Szenarien-Explorer copy (2026-07-12)

- [x] **Rename user-visible "Backtesting" → "Szenarien-Explorer"** — `ui/pages/page_backtesting.py`, `ui/backtesting.py` (page title, buttons, status, warnings, log captions); file/script/module names unchanged


### Smoketest UX — remove Auflösung testen (2026-07-12)

- [x] **Remove button "Auflösung testen"** — removed from `ui/pages/page_scenario_editor.py`; `ui/scenario_runtime_form.py` already absent (unified editor); entity resolution unchanged on save and in `tests/test_house_config.py`, `tests/test_config_runtime_resolution.py`


### OFFLINE gated by Live-Konfiguration (2026-07-12)

- [x] **Greenfield/planning stays offline until Live-Konfiguration complete** — `is_effective_offline()` in `runtime_store/env_vars.py` (explicit `EARNIE_OFFLINE` / auto gate via `is_live_configuration_complete()`); `dotenv_io` uses effective offline for setup blocking / config credential requirement, explicit offline only for sidebar deferral bypass; worker `main.py` waits on `is_planning_offline_gated()`; `config.py` default credential requirement aligned
- [x] **Acceptance:** greenfield without `OFFLINE=1` env behaves offline until entity refs saved on Live-Konfiguration; after save, Loxone paths active (deferred sidebar, worker proceeds when planning ready)
- [x] **Tests:** `tests/test_env_vars.py`, `tests/test_dotenv_io.py`, `tests/test_setup_readiness.py`, `tests/test_greenfield_bootstrap.py`


### Bugfix Greenfield Loxone credential sidebar (2026-07-12)

- [x] **Greenfield: Loxone credential sidebar disappears before credentials saved** — greenfield smoke 2026-07-11; re-opened and **verified 2026-07-12**
- [x] **Root cause:** `scripts/run_backtesting.py` set `ENERGY_OPTIMIZER_OFFLINE=1` at **import** time when Scenario-Exploration loaded; next rerun `loxone_setup_deferred()` returned false → sidebar expander hidden
- [x] **Fix:** `OFFLINE` only when backtesting runs as `__main__` + explicit flag in `ui/backtesting_runner._subprocess_env()`; `render_deferred_loxone_sidebar()` from `app.py` (decoupled from setup notices); hardened `loxone_setup_deferred()` / explicit empty `flexible_consumers` check in `ui/setup_readiness.py`
- [x] **Tests:** `tests/test_setup_progress.py`, `tests/test_setup_readiness.py`, `tests/test_backtesting_ui_helpers.py` (`test_run_backtesting_module_import_does_not_force_offline`)
- [x] **Acceptance:** greenfield — navigate Scenario-Exploration ↔ Szenarieneditor ↔ Hauskonfigurator before `.env` save; expander **"Loxone-Zugang (Live / Silent-Modus)"** persists until credentials saved



### Version 1.93 Components — `components.json` sidecar (2026-07-12)

Completes entity-catalog split from 1.26.0 / 1.93 P2: `batteries[]` and `pv_systems[]` moved from `config.json` into `config/components.json` (sidecar next to `tariffs.json`, `house_profiles.json`). Scenarios keep referencing `battery_id` / `pv_system_id` only. Hard cutover — startup error if legacy keys remain in `config.json`; no alias/fallback.

- [x] **Components P1 — Sidecar infrastructure** — `config/components.schema.json`, `components.minimal.json`, `components.example.json`; `[house_config/components_store.py](house_config/components_store.py)`; `[runtime_store/persist_paths.py](runtime_store/persist_paths.py)` `resolve_components_json_path()`; `[runtime_store/bootstrap.py](runtime_store/bootstrap.py)` `_bootstrap_components_json()`
- [x] **Components P2 — Config load & scenario resolution** — `config.py` `components_path`, `get_batteries()` / `get_pv_systems()` from sidecar; `_reject_legacy_config_blocks`; `[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`; `[ui/setup_readiness.py](ui/setup_readiness.py)`; `batteries` / `pv_systems` removed from `config.schema.json`, `config.minimal.json`, `config.example.json`
- [x] **Components P3 — UI & editors** — `[ui/house_config_io.py](ui/house_config_io.py)` `upsert_battery` / `upsert_pv_system`; help strings in `[ui/config_forms.py](ui/config_forms.py)`
- [x] **Components P4 — Migration & fixtures** — `[scripts/migrate_components_sidecar.py](scripts/migrate_components_sidecar.py)`; `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)` writes components sidecar; `silent-migration-test/config/` + fixtures updated
- [x] **Components P5 — Tests, debug dumps, docs** — `tests/test_components_store.py`, `tests/test_persist_paths_sidecars.py`, planning/setup/runtime resolution tests; `[runtime_store/debug_dump_inputs.py](runtime_store/debug_dump_inputs.py)`; user docs `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[docs/konfiguration/batterie-pv.md](docs/konfiguration/batterie-pv.md)`, `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`
- [x] **Acceptance** — greenfield bootstrap creates empty `components.json`; Hauskonfigurator persists battery/PV there; live + Scenario-Exploration resolve entity IDs; battery-only (no PV) setup passes readiness; startup fails clearly if legacy keys remain in `config.json`



### Bugfix EV urgent constraint removed (2026-07-12)

- [x] **EV: urgent constraint removed** — MILP: separate `urgent >= target` constraint removed; deadline still enforced via `eligible` slots until completion time
- [x] Observability retained (`role` post-hoc); ISO deadline parsing added
- [x] Regression: `eauto_urgent_deferred_cheap_hours_2026-06-28`, new `eauto_urgent_deferred_cheap_hours_2026-07-09`; `xfail` removed
- [x] **Prod acceptance** — charge cycle with deadline 07:45 uses cheap night hours (02–04); `urgent_rule_observability.eauto.role == redundant`
- [x] **Scenario-Exploration: cons_data ID mismatch after regenerate** (greenfield smoke 2026-07-11)
  - Fix: `expected_cons_data_consumer_ids()` uses raw `config.json` IDs or full house-profile set (not `_planning_flex_consumers` merge); meta `consumer_ids` aligned on save



### Version 1.93 P6a — Parallel NAS stack (silent trial) (2026-07-12)

- [x] **Parallel stack** — validated `silent-migration-test/config/` + `runtime/` deployed to new NAS folder (`docker/earnie-2.0/`); legacy `docker/earnie/` unchanged (rollback)
- [x] **Migration review** — `[silent-migration-test/config/MIGRATION_REVIEW.md](silent-migration-test/config/MIGRATION_REVIEW.md)` and entity IDs checked; migration via `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)` (1.26.0 P5 + 1.93 P6a)
- [x] **Compose** — distinct container names, UI port ≠ 8501 (8503), image pinned to 2.0.x
- [x] **Silent mode** — `runtime/local_settings.json`: `{"loxone_silent_mode": true}`; legacy prod worker kept running (no dual writes)
- [x] **Acceptance** — `validate_tariffs --check-catalog`, `startup_checks`, worker/UI on new stack; guide: [Silent Migration Test Stack](docs/einrichtung/silent-migration-test.md)
- [x] **Scope split** — non-silent live cutover deferred to **1.94 P6b** (not a real 2.0 release gate)



### Version 1.93 P5 — Tariffs & deploy gate (2026-07-11)

- [x] **Tariff plausibility** — `[house_config/tariff_plausibility.py](house_config/tariff_plausibility.py)`: Normalisierung, JSON-Schema, Szenario-Referenzen; CLI `[scripts/validate_tariffs.py](scripts/validate_tariffs.py)` (`earnie-validate-tariffs`)
- [x] **Runtime gates** — Scenario-Exploration UI + `[scripts/run_backtesting.py](scripts/run_backtesting.py)`; Worker-Start `[scripts/startup_checks.py](scripts/startup_checks.py)` (`EARNIE_STRICT_TARIFF_VALIDATE` in Prod-Compose)
- [x] **Deploy gate** — `[scripts/build_container.py](scripts/build_container.py)` prüft vor `--push`; `[tools/convert_dach_tariffs.py](tools/convert_dach_tariffs.py)` `--check` für DACH-Vollständigkeit
- [x] **Catalog** — DACH-Quellen abgedeckt; `fixed_37ct` (Greenfield-Beispiel) in `[config/tariffs.json](config/tariffs.json)`
- [x] **Deploy docs** — `[docs/einrichtung/container.md](docs/einrichtung/container.md)`, `[docker-compose-synology.yml](docker-compose-synology.yml)`, `[docker-compose-loxberry.yml](docker-compose-loxberry.yml)`: `tariffs.json` Sidecar + Strict-Validate
- [x] **Tests** — `tests/test_tariff_plausibility.py`, `tests/test_validate_tariffs_cli.py`, Erweiterung `tests/test_startup_checks.py`



### Version 1.93 P4 — `sunrise_window` rename (2026-07-11)

- [x] **Hard rename** — `sunset_window` → `sunrise_window` in schema, config templates, fixtures, CLI `--horizon-mode`, live `planning_horizon.mode`; no alias
- [x] **Internal symbols** — `SUNRISE_WINDOW`, `is_sunrise_planning_horizon`, `build_sunrise_window_matrix`, `compute_sunrise_planning_at_anchor`, `log_supports_sunrise_chart_view`, `VIEW_MODE_SUNRISE`
- [x] **Docs** — `[docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)`, `[docs/konfiguration/batterie-pv.md](docs/konfiguration/batterie-pv.md)`
- [x] **Out of scope** — live `planning_horizon.mode` branching (`fixed_24h` | `sunrise_window`) remains **2.+1**; historical backtesting log filenames unchanged



### Version 1.93 P3 — Configuration UI restructure (2026-07-11)

- [x] **Nav sections** — `Planung` (Hauskonfigurator, Szenarieneditor) + `Echtzeit-Umgebung` (`[ui/navigation.py](ui/navigation.py)`); raw JSON editor not in main nav
- [x] **Echtzeit-Umgebung page** — `[ui/pages/page_live_environment.py](ui/pages/page_live_environment.py)`: `live_scenario_id` picker, resolved snapshot, comfort form from `[ui/config_forms.py](ui/config_forms.py)`
- [x] **Onboarding hints** — `[ui/setup_readiness.py](ui/setup_readiness.py)` sidebar copy aligned to new page names and order
- [x] **Tests & docs** — `tests/test_navigation_setup.py`, `tests/test_setup_readiness.py`; `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` acceptance table
- [x] **Acceptance** — greenfield smoke: onboarding → live selection → Scenario-Exploration unlock (follow-ups → [Backlog-Erledigt.md](Backlog-Erledigt.md) *Version 1.93 — smoke-test follow-ups*)
- [x] **Batterien tab** — entity CRUD moved to Hauskonfigurator (`[ui/pages/page_house_config.py](ui/pages/page_house_config.py)`); Szenarieneditor scenario CRUD only; onboarding copy + tests updated



### Version 1.93 P1 — Optional consumers (2026-07-11)

- [x] **Haus Wärme optional** — `thermal_annual` not mandatory (`[house_config/profiles_store.py](house_config/profiles_store.py)`, Hauskonfigurator)
- [x] **PV optional** — `[ui/setup_readiness.py](ui/setup_readiness.py)`, `[ui/planning_pv_form.py](ui/planning_pv_form.py)`
- [x] **Battery without PV** — battery required for MILP / `is_planning_ready()`; unset `pv_system_id` → zero PV forecast
- [x] **Optimizer/simulation tolerance** — `[house_config/entity_resolution.py](house_config/entity_resolution.py)`, `[config.py](config.py)`, `[house_config/baseload.py](house_config/baseload.py)`, `[house_config/planning_flex_bridge.py](house_config/planning_flex_bridge.py)`
- [x] **Tests** — greenfield bootstrap, setup readiness, house profiles without thermal/PV



### Version 1.93 P2 — Unified scenario model (2026-07-11)

- [x] **Live baseline as normal scenario** — `live_scenario_id` in `config.json` (default `live`); unified resolution in `[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`; `config.py` rejects `runtime_settings` block
- [x] **UI mode rename** — `backtesting` → `scenario_exploration` (`[ui/mode_selector.py](ui/mode_selector.py)`, `[ui/navigation.py](ui/navigation.py)`, compose, VS Code launch); user-facing label **Scenario-Exploration**
- [x] **Szenarieneditor** — unified editor (`[ui/pages/page_scenario_editor.py](ui/pages/page_scenario_editor.py)`); removed orphaned `ui/scenario_runtime_form.py`; live scenario via `[ui/house_config_io.py](ui/house_config_io.py)`
- [x] **Templates & schema** — `config.example.json`, `backtesting_scenarios.example.json` (`live` entry), `config.schema.json` without `runtime_settings`
- [x] **Scripts & tests** — dev scripts default to `live`; backtesting tests use scenario id `live`; `[tests/config_fixtures.py](tests/config_fixtures.py)`
- [x] **Docs (DE)** — `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[docs/ui/betriebsmodi.md](docs/ui/betriebsmodi.md)`, greenfield/container/betrieb, PV/preise specs
- [x] **Tests** — 143 passed locally (P2 subset); `migrate_runtime_entities` output update deferred to **1.93 P6a**



### Earnie rename (2026-07-11)

- [x] **Version 1.93 — branding** — UI/docs Ernie→Earnie; Loxone signal names (`Ernie_`*) unchanged in production config
- [x] **Packaging** — `pyproject` package `earnie`; CLI `earnie-`* with legacy `ernie-`* aliases
- [x] **Env vars** — canonical `EARNIE_`* with `ENERGY_OPTIMIZER_`* fallback (`runtime_store/env_vars.py`)
- [x] **Docker** — `ghcr.io/jochentcc/earnie-energy` image and `earnie-`* container names; dual-tag transition (`ernie-energy` alias)
- [x] **Runtime paths** — log file `earnie.log`; NAS path docs `docker/earnie`
- [x] **GitHub** — rename repository to `Earnie` on GitHub (Settings → General), then update remotes: `git remote set-url origin https://github.com/JochenTCC/Earnie.git` *(manual step — repo still* `Energy-Optimizer` *until renamed on GitHub)*



### Version 1.26.0 — Runtime entities & tariffs (release) (2026-07-11)

- [x] **Release 1.26.0** — Greenfield-first P0–P4, prod migration P5, legacy removal P6; live + backtesting share ID-only `runtime_settings` resolution; `version.py` → 1.26.0
- [x] **Acceptance** — greenfield smoke; migration draft + manual review path; no flat-field fallbacks; per-tariff aWATTar; `battery_wear` on selected battery only



### Version 1.26.0 P6 — Legacy removal (2026-07-11)

- [x] **P6 — Legacy removal (no fallbacks)**
  - Removed flat-field fallback in entity/tariff resolution (`house_config/entity_resolution.py`, `config.py` `_lookup_runtime_value`)
  - Removed global `battery_wear` and top-level `awattar` block support; pricing via `tariffs.json` only; API URL from `import_tariff_id` → `land` (`house_config/awattar_api.py`)
  - Schema: ID-only `runtime_settings`; removed deprecated flat fields from `config.schema.json`
  - Updated `config/config.example.json`, `config.minimal.json`, greenfield fixture, backtesting fixture to ID-only `runtime_settings`



### Version 1.26.0 P5 — Prod cutover (migration, tests, docs) (2026-07-11)

- [x] **Migration script** — `[house_config/migrate_runtime_entities.py](house_config/migrate_runtime_entities.py)`, CLI `[scripts/migrate_runtime_entities.py](scripts/migrate_runtime_entities.py)` (`ernie-migrate-runtime`): flache `runtime_settings` → Entwurf mit ID-only refs, `batteries[]`/`pv_systems[]`, Geo auf `house_profiles.json`, `battery_wear` auf Batterie-Eintrag, aWATTar-Felder in Tarife; `MIGRATION_REVIEW.md` — manuelle Prüfung vor NAS-Deploy
- [x] **Tests** — `tests/test_house_config.py`: Migration, Auflösungs-Parität, CLI-Entwurf
- [x] **Docs (DE)** — `[docs/konfiguration/ueberblick.md](docs/konfiguration/ueberblick.md)`, `[preise.md](docs/konfiguration/preise.md)`: ID-only `runtime_settings`, Migration, Konfigurations-UI
- [x] **Backlog** — P5 ohne 7g-a (NAS-Abnahme); Follow-up: Version 1.+1 „Include tariffs.json in deploy“



### Version 1.26.0 P4 — UI live configuration (2026-07-11)

- [x] **Runtime entity UI** — `[ui/config_forms.py](ui/config_forms.py)`, `[ui/scenario_runtime_form.py](ui/scenario_runtime_form.py)`: ID dropdowns (battery, PV, tariffs, house profile); resolved PV/battery/tariff read-only; `[ui/pages/page_config.py](ui/pages/page_config.py)` expander renamed
- [x] `update_runtime_settings()` — IDs only in `[config.py](config.py)`; rejects flat PV/battery and geo fields
- [x] `save_runtime_scenario_refs()` — entity IDs only; strips legacy geo from `runtime_settings` (`[ui/house_config_io.py](ui/house_config_io.py)`)
- [x] **Geo on house profile** — `latitude`/`longitude`/`timezone_name` resolved from `house_profile_id` (`[house_config/scenario_resolution.py](house_config/scenario_resolution.py)`); removed from greenfield `runtime_settings`
- [x] **Timezone derivation** — `timezonefinder` + `[house_config/geo_timezone.py](house_config/geo_timezone.py)`; no manual timezone entry in Hauskonfigurator; optional geo override in Szenarieneditor “Weitere Szenarien”
- [x] **Tests** — `tests/test_config_runtime_resolution.py`, `tests/test_geo_timezone.py`; greenfield ID-only keys in `tests/test_greenfield_bootstrap.py`
- [x] **Docs** — `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` acceptance table updated



### Version 1.26.0 P3 — Price pipeline live (2026-07-11)

- [x] **Import pricing live** — shared `import_brutto_cent_for_slots` / `enrich_slots_import_prices` in `data/backtesting_prices.py`; live matrix + historical day via `profile_manager.py`; reference costs in `simulation/engine.py`
- [x] **Parity test** — same tariff IDs → identical import cent/kWh live vs backtesting (`tests/test_price_pipeline_p3.py`)
- [x] **P3a — Backtesting window** — `resolve_simulation_window()` snaps start to Monday of week with `(today − 12 months)`; documented in `ui/backtesting_time_ranges.py`
- [x] **P3b — Minimal thermal bridge** — `thermal_on_off_hourly_profile` in `data/heating_need.py`; on/off at `nominal_power_kw` in `data/consumption_profiles.py`; `house_profile_baseload_overlay` (generic + thermal) in `house_config/planning_flex_bridge.py` for live + backtesting
- [x] **Tests** — `tests/test_price_pipeline_p3.py`



### Version 1.26.0 P0 — Greenfield onboarding deferrals (2026-07-11)

- [x] **Deferred runtime params** — incomplete Greenfield planning no longer crashes `import config`; PV/battery/tariff params load after Szenarieneditor; `main.py` waits until planning complete (`config.py`, `main.py`, `ui/config_forms.py`, `tests/test_config_runtime_resolution.py`)
- [x] **Deferred Loxone credentials** — `.env` entry no longer blocks UI/worker during planning; optional sidebar form + Merker test when going live (Silent-Modus) or verifying aliases (`runtime_store/dotenv_io.py`, `ui/setup_dotenv.py`, `ui/setup_progress.py`, `app.py`, `main.py`)
- [x] **Tests** — `test_config_runtime_resolution.py`, `test_dotenv_io.py`, `test_greenfield_bootstrap.py`



### Version 1.26.0 P2 — Central resolution in config.py (2026-07-11)

- [x] `resolve_runtime_settings()` — unified live + backtesting baseline in `house_config/scenario_resolution.py`
- [x] `_load_dynamic_params()` — loads PV/battery/tariff/geo from resolved dict (ID wins, legacy flat fallback)
- [x] `get_battery_wear_cent_per_kwh()` — from `_battery_wear` on selected `batteries[]` entry; global fallback only without `battery_id`
- [x] `get_backtesting_scenarios()` — baseline via same `_resolve_runtime_settings_dict()` path
- [x] **Flex bridge** — `get_flexible_consumers()` merges `_planning_flex_consumers`; live baseload overlay via `fixed_generic_hourly_overlay` in `profile_manager.py`
- [x] `get_feed_in_settings()` — uses resolved runtime incl. `_monthly_fixed_tariffs`
- [x] **Tests** — `tests/test_config_runtime_resolution.py`



### Version 1.26.0 P1 — Data model & schema (2026-07-11)

- [x] **Schema** — `config.schema.json`: `battery_wear` on `battery_entity`, `house_profile_id` + deprecated flat `runtime_settings`; `tariffs.schema.json`: import `monthly_table`, per-tariff aWATTar surcharges
- [x] `battery_wear` **on** `batteries[]` — normalized in `house_config/entity_resolution.py`; resolved as `_battery_wear` (P2 wires MILP)
- [x] **Import** `monthly_table` — `tariffs_store.py`, `data/tariff_pricing.py`, `data/backtesting_prices.py`
- [x] **aWATTar surcharges per tariff** — import `awattar` + export `dynamic_epex` fields in `tariffs.json` / examples; legacy `config.json` awattar block still fallback until P6
- [x] **Example configs** — `config.example.json`, `tariffs.example.json`, greenfield battery/tariffs, backtesting fixture
- [x] **Tests** — `test_tariff_pricing.py`, `test_house_config.py`



### Version 1.26.0 P0 — Greenfield pilot (strict target config) (2026-07-11)

- [x] **ID-only** `runtime_settings` — `greenfield/config/config.json` and `config/config.minimal.json` stripped of flat PV/battery/tariff duplicates; IDs only (geo/timezone on house profile since P4)
- [x] **Sunset-2-Sunset on greenfield** — `ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting` in `docker-compose-greenfield.yml` and VS Code Greenfield launch
- [x] **Acceptance checklist** — Live-path smoke steps in `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)` (execution blocked until **1.26.0 P2**)
- [x] **Tests** — `tests/test_greenfield_bootstrap.py`: ID-only runtime_settings assertions for minimal template and greenfield config



### Bugfix EV absence vs. live control (2026-07-10)

- [x] **EV unplugged: no charge setpoint to Loxone** — With `anticipated` + `plugged_in: false`, `_effective_consumer_power_kw` suppresses output; `booking_power_kw` books no fictitious energy (v1.24.3)
- [x] `available_from` **during actual absence** — Same-day late return does not count as immediately available; overnight window preserved (`resolve_absent_availability`)
- [x] **Tests** — `test_charging_context`, `test_delivery_tracking`, `test_loxone_client`; reference dump `chart_debug_20260710_111939`



### Version 1.25.0 — UI follow-up close-out (2026-07-10)

- [x] **Backtesting UI — explain time ranges** — Caption + expander in `ui/backtesting_cons_data.py` and `ui/backtesting.py` (`ui/backtesting_time_ranges.py`): `cons_data_retention_months` vs. `price_range` simulation window vs. sliced reference consumption vs. Hauskonfigurator 8760 h
- [x] **PV in consumption UI** — `pv_kw` as own trace **PV-Erzeugung** (not in consumption stack); monthly line + weekly line in `ui/consumption_display/charts.py`; test `test_cons_data_bundle_pv_not_in_stack`



### Version 1.25.0 — UI follow-up decisions & clarifications (2026-07-10)

**Scope:** Close-out of planning notes from `Backlog.md` § Version 1.25.0 UI follow-up; implementation in 1.25.a–1.25.f.

#### Decisions recorded

- [x] **Consumption UI data mode (Mode A):** House configurator = actual CSV vs. model; backtesting = `cons_data` only (historical); scenario editor = modeled house profile only — no actual-vs-model on backtesting/scenario editor
- [x] **Monthly view timeline:** dropped — timeline only ISO week, hourly
- [x] **Weekly view timeline:** ISO week, hourly; navigation ←/→; datetime X-axis, lines per consumer
- [x] **Deviation detail:** full cockpit Chart1/2 in 24h and SA_0–SA_2 (1.25.f)
- [x] **Monthly cost table:** dataframe table dropped; Plotly monthly chart remains
- [x] **Total costs:** compact annual table (all scenarios incl. reference) instead of metric columns alone
- [x] **Δ vs. reference:** cost change (`scenario € − reference €`); negative = cheaper, positive = more expensive



#### Clarifications resolved

- [x] **"Non-optimized annual consumption"** — reference/`cons_data` (historical without optimization), not non-optimized scenarios
- [x] **Test run (1 month):** consumption UI limited to test month (`nav_bounds` + sliced `cons_data`)
- [x] **Scenario editor:** modeled house profile of assigned profile only (no `cons_data`, no CSV actual) — per Mode A
- [x] **Total cost table columns:** Scenario | Annual kWh | Annual € | Δ vs. reference



#### Delivered code state (at close-out)

- [x] `ui/consumption_display/` (three modes); backtesting page: cons_data section, total cost table, deviation list with Chart1/2 (1.25.f), window snapshots (`backtesting_window_snapshots.jsonl`), horizon-mode UI (`fixed_24h` / `sunset_window`), reference consumption, monthly cost chart
- [x] Plausibility false positives with house profile fixed (bugfix → `Backlog-Erledigt.md` § Bugfix — Backtesting plausibility)



### Version 1.26.0 P2b — Smoketest follow-ups (UX) (2026-07-11)

- [x] **Hauskonfigurator:** modeled consumption chart without Jahres-Verbrauchs-CSV (`ConsumptionDisplayMode.MODELED_PROFILE`; scenario-editor pattern in `ui/house_config_profile_form.py`)
- [x] **ISO week jump:** week number only — year inferred from data range (`ui/consumption_display/navigation.py`: `parse_iso_week_number_only`, `resolve_iso_week_jump_target`)
- [x] **New PV-Anlage / Solarkollektor:** inherit profile `default_pv_tilt` / `default_pv_azimuth` (18°/0° fallback; PV profile picker updates tilt/azimuth via `on_change`)



### SE Abweichungs-Kalender — polish (2026-07-13)

- [x] **Calendar navigator:** single-month view with Zurück/Vor; color-coded deviation days; on-demand Chart1/2 (`ui/backtesting_deviation_calendar.py`, `ui/backtesting_deviation_list.py`)
- [x] **Snapshot cache:** on-demand windows appended to `backtesting_window_snapshots.jsonl` (`append_window_snapshot`)
- [x] **diag_single_window:** CLI command + optional run from detail expander (`ui/backtesting_diag_single_window.py`)
- [x] **Scenario picker:** radio list with deviation markers; single scenario detail/charts
- [x] **Spec:** `docs/spec/backtesting-deviation-calendar.md`



### Version 1.25.f follow-ups — deviation list & week navigation (2026-07-10)

- [x] **Deviation dedup:** `dedupe_critical_cases_by_window()` — per `(scenario_id, window_anchor)` keep most critical (`milp_no_optimal` > `strict_slow` > `strict_fallback` > `consumption_tolerance`)
- [x] **Row selection → Chart1/2:** `st.dataframe` single-row selection replaces separate selectbox (`ui/backtesting_deviation_list.py`)
- [x] **ISO week jump:** direct KW entry (`12/2025`, `KW 12/2025`, `2025-W12`) in `ui/consumption_display/navigation.py`
- [x] **Tests:** `test_backtesting_critical_cases.py`, `test_backtesting_deviation_list.py`, `test_consumption_display.py`



### Version 1.25.f — Chart1/2 detail for deviations (2026-07-10)

**Scope (after 1.25.e smoketest ✅):** full — 24h + SA_0–SA_2 with cockpit Chart1/2; window snapshots for failed windows + on-demand fallback.

- [x] **Persistence:** `simulation/backtesting_snapshots.py` — JSONL sidecar `backtesting_window_snapshots.jsonl` (`chart_rows`, `matrix`, `meta`, `horizon_mode`, scenario ID)
- [x] **Engine:** snapshot collection on plausibility failure and on-demand paths (`simulation/engine.py`)
- [x] **Adapter:** `ui/backtesting_display_bundle.py` — `build_backtesting_display_bundle` / `load_backtesting_display_bundle` → `OptimizationDisplayBundle`
- [x] **UI:** `ui/backtesting_deviation_list.py` — `render_optimization_chart1/2` below deviation list; toggle 24h | SA_0–SA_2 (disabled when log `fixed_24h`)
- [x] **Fallback:** on-demand re-simulation of a window when no snapshot exists
- [x] **Tests:** `test_backtesting_display_bundle.py`, `test_backtesting_snapshots.py`, `test_backtesting_snapshot_collector.py`, `test_backtesting_deviation_list.py`, `test_backtesting_ui_helpers.py`

**Manual acceptance**

- [x] Select deviation → Chart1 energy balance (PV, battery, consumer stack, zones per scope)
- [x] Chart2 cost lines target/actual
- [x] Toggle 24h ↔ SA_0–SA_2



### Version 1.25.e — Smoketest backtesting `sunset_window` (2026-07-10)

**Purpose:** Verify `sunset_window` backtesting (Now→SA₂) is stable — prerequisite for Chart1/2 SA zones (1.25.f).

**Result: ✅ stable** — June 2025, 30 windows, plausibility 30/30 both modes, no CBC aborts. Sunset ~0.37 € higher than `fixed_24h` on scenario `fixture_5kwh_fixed` (10.74 € vs 10.37 €); reference 36.03 €. Protocol: `backtesting_logs/smoketest_125e/protocol.md`.

- [x] **CLI smoketest:** `scripts/run_backtesting.py --horizon-mode sunset_window --start-month <M> --end-month <M>` — exit 0, `"horizon_mode": "sunset_window"` in log, plausibility/CBC without unexpected aborts
- [x] **UI:** `--horizon-mode` on `build_backtesting_command` / run controls (`ui/backtesting_runner.py`)
- [x] **Document result:** ✅ stable — full 1.25.f scope approved

**Manual acceptance**

- [x] Smoketest protocol: command, config path, month, duration, exit code, `horizon_mode` in log
- [x] No blocker for 1.25.f full scope



### Bugfix — Backtesting plausibility (deviation list overfilled) (2026-07-10)

**Trigger:** Manual acceptance **1.25.d** — deviation list ~934 entries; `runtime_settings` failed in every window (`optimized_flex_kwh = 0` despite historical flex target values).

**Root cause:** For house-profile backtesting (`flexible_consumers: []`), consumer columns were missing from the profile DataFrame; `delivered_flex_kwh_from_rows` and `resolve_horizon_consumer_targets_kwh` only considered config consumers; planning target values incorrectly overwrote cons_data history on days without flex consumption.

- [x] **Diagnosis:** Greenfield runtime; flex-only failure pattern (`diff_kwh = 0`, `flex_diff > 0`, `optimized_flex = 0`) verified
- [x] `data/profile_manager.py`**:** House-profile consumers from `cons_data` (`expected_cons_data_consumer_ids`) into profile format
- [x] `simulation/engine.py`**:** Flex/baseload from cons_data (MILP scope); `_flexible_consumers` in meta; no planning-target fallbacks when cons_data = 0
- [x] `optimizer/targets.py` **+** `optimizer/simulation.py`**:** `flexible_consumers` parameter for horizon limits and flex delivery
- [x] `scripts/analyze_plausibility_failures.py`**:** Time range from log `meta.period`
- [x] **Regression:** `tests/test_baseload_validation.py` (planning flex plausibility)

**Manual acceptance**

- [x] Greenfield backtesting recalculated; deviation list without systematic filling of all windows
- [x] Acceptance 1.25.d “clean run” completed



### Version 1.25.d — Deviation list (cost comparison) (2026-07-10)

- [x] Unified list of notable cases (basis: `extract_critical_cases()` — plausibility + CBC events)
- [x] Columns: window, scenario, type, Δ kWh (target/actual)
- [x] Selecting an entry → detail area (placeholder until 1.25.f)
- [x] Reference scenario: no deviation list

**Manual acceptance**

- [x] Run with deviations: sorted list; selection highlights window + scenario
- [x] Clean run: empty list / info notice (after plausibility bugfix)
- [x] Chart “window end”: placeholder (plausibility chart) until 1.25.f, no cockpit Chart1/2



### Version 1.25.c — Backtesting page layout (2026-07-10)

Target order: cons_data (status/generation/consumption UI) → scenarios + run buttons → total cost table → reference consumption → monthly cost chart (without dataframe/hourly chart).

- [x] Page order (`ui/backtesting.py`, `ui/backtesting_cons_data.py`, `ui/backtesting_results_helpers.py`)
- [x] Removed: scenario/month selectbox, hourly cost chart, monthly dataframe in cost comparison
- [x] Test-run caption + `nav_bounds` for calendar-week navigation
- [x] Total cost table with Δ as cost change (`scenario € − reference €`)
- [x] Consumption UI in cons_data section and in results (log period, period-appropriate subheader)
- [x] Synthetic `cons_data` from house profile when `flexible_consumers` empty (`data/cons_data_house_profile.py`)
- [x] Warning when `{verbraucher_id}_kw` missing or only 0
- [x] Tests: `test_backtesting_results_helpers.py`, `test_cons_data_house_profile.py`

**Manual acceptance**

- [x] Full run: no scenario/month selectbox, no hourly cost chart
- [x] Total cost table with reference + scenarios + Δ
- [x] Test run: charts/navigation only test month; consumers visible in timeline



### Version 1.25.b — Consumption UI on three pages (2026-07-10)

- [x] **House configurator** — `render_consumption_comparison_panel` via core, mode `csv_validation`
- [x] **Backtesting** — `render_cons_data_section`: keep status/generation, visualization via core (`cons_data`)
- [x] **Scenario editor** — section “Consumption profile (model)” for runtime house profile, mode `modeled_profile`

**Manual acceptance**

- [x] Three pages: same layout, navigation, legend colors
- [x] Scenario editor without actual data; backtesting without model comparison



### Version 1.25.a — Consumption UI core (2026-07-10)

- [x] **Three modes** in `ui/consumption_display/`: `csv_validation`, `cons_data`, `modeled_profile`
- [x] **Monthly overview:** separate bar per consumer; sum = total consumption; baseload as residual on its own track
- [x] **Timeline:** ISO calendar week, hourly; navigation ←/→ (no month toggle; follow-up: datetime X-axis, lines per consumer)
- [x] **Data layer:** `build_modeled_hourly_kw_by_consumer()` in `data/consumption_profiles.py`
- [x] **Tests:** `tests/test_consumption_display.py`, `tests/test_consumption_display_integration.py`

**Manual acceptance**

- [x] House configurator + CSV: monthly bars actual vs. model; calendar-week navigation; consumers + baseload visible in weekly timeline
- [x] Synthetic `cons_data`: stacked monthly bars sum ≈ `total_kw`
- [x] ←/→ calendar week: correct ISO week boundaries; readable hourly timeline



### Version 1.25.0 — Backtesting with house configuration (2026-07-10)

- [x] **House configurator** — optional annual total consumption CSV (format check: monthly bars + hourly timeline)
- [x] **Scenario editor** — subpage under configuration; house configurator only consumers + PV; battery/tariffs in scenario editor; default scenario runtime (required before backtesting/operation); additional scenarios with different batteries/tariffs
- [x] **Backtesting from configuration** — data from house configuration + scenarios; load run when fingerprint matches, otherwise recalculate
- [x] **Consumption data (**`cons_data_hourly.csv`**)** — visualization, synthetic generation (`scripts.generate_cons_data`), consumer ID match status, backtesting start disabled without valid file
- [x] **cons_data plot** — navigation like annual CSV; column timelines `total_kw` / `baseload_kw` / `pv_kw`
- [x] **Backtesting runner** — test run (one month), progress bar (`--progress-file`), grouped scenario bars in monthly cost comparison
- [x] **Sidecar paths** — `tariffs.json` / `house_profiles.json` / `backtesting_scenarios.json` next to per-ENV `config.json` (`persist_paths`)
- [x] **Fingerprint** — tariff specs and aWATTar pricing block in scenario fingerprint; export tariff alias `awattar_sunny_float` → `dynamic_epex`
- [x] **Tests** — `test_backtesting_cons_data`, `test_backtesting_charts`, `test_backtesting_plausibility_charts`, `test_backtesting_ui_helpers`, `test_persist_paths_sidecars`

**Manual acceptance (Greenfield, Streamlit :8511 or container :8502)**

- [x] Greenfield reset; only house configurator + configuration visible; sidebar shows missing steps
- [x] **House configurator** — save thermal house profile + PV system; optionally upload annual CSV → monthly bars and hourly timeline (actual vs. model)
- [x] **Scenario editor** appears after house profile + PV — create battery, save runtime (battery, tariffs, house profile, geo)
- [x] **Backtesting** appears after complete runtime scenario — configured scenarios displayed
- [x] **Consumption data (**`cons_data_hourly.csv`**)** — without valid file: section with notice, **Start backtesting** button disabled
- [x] Button **Generate consumption data (synthetic)** — `runtime/cons_data_hourly.csv` + `.meta.json` with data rows
- [x] Monthly bars and calendar-week hourly timeline (actual vs. model) in consumption data section
- [x] Consumer ID match status — matches current config (green) or warning on mismatch or missing meta file
- [x] Button **Start backtesting** — run completes successfully; costs, months, plausibility and hourly chart visible
- [x] After change to runtime/scenario — warning “Run does not match configuration” + **Recalculate**
- [x] Merge PR #4



### Bugfix runtime scenario save (2026-07-09)

- [x] **KeyError on empty entity lists** — safe ID resolution in `scenario_form_helpers.py`; disabled selectboxes for empty PV/battery lists in runtime and scenario editor
- [x] **PV/battery form state** — seed widget state from saved values (`planning_pv_form.py`, `planning_battery_form.py`)
- [x] **Tests** — `tests/test_scenario_form_helpers.py`, extension `tests/test_planning_editors.py`



### hausconfig: solar thermal, profile location (2026-07-09)

- [x] **Solar thermal collector** — heating need model with solar thermal in `data/heating_need.py`; validation charts and tests (`tests/test_heating_need_solar.py`)
- [x] **Profile location** — `latitude`/`longitude` and PV defaults at profile level (`house_profiles.schema.json`, `house_config_profile_form.py`)
- [x] **Consumption validation** — extended charts and tests for thermal profile with solar thermal



### Bugfix native filter window log spam (main.py) (2026-07-09)

- [x] `filter_contexts` **once per run** — `main.py` resolves before `get_consumer_remaining_kwh` and passes through to MILP, remaining-target adjustment and `calculate_optimization_savings`
- [x] **Horizon simulation** — `simulate_horizon` / `_simulate_single_hour_optimizer` / `calculate_optimization_savings` accept prebuilt `filter_contexts`; no repeated Loxone read per MILP hour
- [x] **Logging** — INFO “native filter window Start=…” only at `resolve_filter_context`, not on every indirect call
- [x] **CBC log spam** — `record_cbc_event` no longer logs per slot during active collection (`begin_cbc_event_collection`); `simulate_horizon` summarizes at end as one INFO line (`summarize_cbc_events`); live MILP in `main.py` unchanged at INFO
- [x] **Tests** — `TestFilterContextCaching` in `tests/test_filter_context.py`; CBC suppression/summary in `tests/test_cbc_events.py`



### Bugfix UI bugs 1.23.1 (2026-07-09)

- [x] **Ranking table compact on mobile** — 3 columns (checkbox before time, quality, delta); cost column removed (`ui/pages/page_devices.py`)
- [x] **Cockpit Chart 1/2 legend** — variant A (unified collapsible): `showlegend=False`, `margin.b` ≈ 55, HTML `<details>` on all viewports (`ui/chart_legend_mobile.py`, `ui/charts.py`)
- [x] **Rated power/runtime with active plan** — input fields and save button disabled with notice text
- [x] **SOC BL target bridge at zone boundaries** — `bridge_left=(index > 0)` in `add_baseline_soc_traces`
- [x] **Price curve continuous** — single trace instead of segmented HV lines (`add_price_on_soc_axis_trace`)
- [x] **Manual appliances hatching** — stable patterns per `appliance_id` (`manual_appliance_pattern_shape` in `ui/chart_colors.py`)



### Bugfix mobile legend cockpit (Chart 1/2) (2026-07-09)

- [x] **Mobile legend cockpit (Chart 1/2)** — Plotly legend hidden below 768px via CSS; colored `<details>` as replacement (mobile only). Desktop: Plotly legend only, no expander (`ui/chart_legend_mobile.py`). Prod acceptance confirmed.



### Bugfix Sankey SwimSpa/filter case B (total meter) (2026-07-09)

- [x] **Sankey + Chart 1 SwimSpa/filter (total meter case B)** — fix **v1.24.1**: Sankey/live UI load flex power when `optimizer_run_state` stale (>120 s) with `filter_contexts` + `slot_datetime` (`fetch_live_flex_kw_for_ui` in `data/live_consumption.py`); filter inference as in `main.py`. Prod acceptance: native window 10–14 — two Sankey flows (SwimSpa + SwimSpa filter), filter power correctly assigned, no misleading target/actual mismatch color at target 0. Reference dumps: `chart_debug_20260708_114712`, `chart_debug_20260709_120500`.



### Version 1.24.g — monthly_float feed-in tariff (OeMAG reference curve) (2026-07-09)

- [x] **Schema** — export type `monthly_float` in `tariffs.schema.json`; `oemag_monthly_feed_in_rates` + `monthly_float_reference_cent_kwh` in `backtesting_scenarios.schema.json`
- [x] **Pricing pipeline** — `data/monthly_float_rates.py` (OeMAG scaling); `tariff_pricing.export_cent_kwh`; `get_backtesting_feed_in_settings()` builds scaled monthly table at runtime
- [x] **Catalog & converter** — `tools/convert_dach_tariffs.py` from `einspeisetarife_dach_erweitert.json`; 5 `monthly_float` export tariffs in `config/tariffs.json`
- [x] **OeMAG reference data** — 12 months Jul 2025–Jun 2026 in `backtesting_scenarios.example.json`; `fixed_monthly_feed_in_rates` (aWATTar-SUNNY) unchanged
- [x] **Tests & docs** — `tests/test_monthly_float_rates.py`; extension of `test_tariff_pricing` / `test_house_config`; `docs/konfiguration/preise.md`



### Version 1.24.f — DACH tariff catalog & pricing model (backtesting) (2026-07-09)

- [x] **P1 — Schema & pricing functions** — `tariffs.schema.json` (DACH types + `catalog_as_of`); `house_config/tariffs_store.py` (`_import_tariff_spec`, `_export_tariff_spec`, scenario specs); `data/tariff_pricing.py` (`import_cent_kwh` / `export_cent_kwh`, legacy `awattar`/`dynamic_epex`)
- [x] **P2 — Backtesting pipeline & market zones** — `data/data_loader.py` (AT / `DE-LU` / CH); tariff-aware pricing in `simulation/engine.py`, `data/backtesting_prices.py`, `data/feed_in_prices.py`
- [x] **P3 — DACH converter & catalog** — `tools/convert_dach_tariffs.py`; `config/tariffs.json` with 44 tariffs (`catalog_as_of=2026`)
- [x] **P4 — Planning UI** — `ui/planning_tariff_form.py`, `ui/pages/page_scenario_editor.py` (type labels, country/currency/notes, `catalog_as_of`, DE grid-fee override)
- [x] **P5 — Tests & docs** — `tests/test_tariff_pricing.py`, extension of `tests/test_house_config.py`; `docs/konfiguration/preise.md`



### Version 1.24.e — Planning editors & house configurator UX (2026-07-09)

- [x] **P1 — Config drift** — `should_show_config_drift()` suppresses notice during `needs_planning_onboarding()`; empty `flexible_consumers` ignored in drift check
- [x] **P2 — House configurator UX** — auto IDs (`house_config/id_slug.py`); type label “Haus Wärme”; building classes with HWB; optional `hwb_kwh_m2`
- [x] **P3 — Planning configuration** — PV/battery/tariff tabs in house configurator; bootstrap `tariffs.json` from `tariffs.example.json`; tariff selection → `runtime_settings.import/export_tariff_id` (no tariff editor)
- [x] **P4 — Tests & docs** — `tests/test_planning_editors.py`; setup/navigation/drift adjustments; `[greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`



### Version 1.24.d — Greenfield onboarding (minimal config + UI unlock) (2026-07-09)

- [x] **P1 — Minimal bootstrap** — `config.minimal.json` + empty templates for `house_profiles`, `tariffs`, `backtesting_scenarios`; bootstrap uses minimal instead of example files; `config.example.json` remains reference
- [x] **P2 — Runtime UI gating** — `ui/setup_readiness.py`, `ui/setup_progress.py`, `ui/navigation.py`: after Loxone setup only house configurator + configuration until planning complete
- [x] **P3 — Backtesting unlock** — unlock with thermal house profile + PV + battery + import/export tariff; scenario editor locked for now (follow-up)
- [x] **Tests + docs** — `tests/test_setup_readiness.py`, `tests/test_navigation_setup.py`; `[greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`



### Version 1.24.c — Greenfield dev stack (2026-07-09)

- [x] **P1 — Greenfield compose** — `docker-compose-greenfield.yml` with `greenfield/config` + `greenfield/runtime`, container `ernie-greenfield-`*, UI port **8502**, Loxone verify off
- [x] **P2 — Acceptance helpers** — checklist in `[docs/einrichtung/greenfield-dev-stack.md](docs/einrichtung/greenfield-dev-stack.md)`; smoke test `tests/test_greenfield_bootstrap.py` (without fixture snapshot `tests/fixtures/greenfield/`)
- [x] **Follow-up during walkthrough** — `Dockerfile`: `share/config/` extended with tariff, house profile and backtesting scenario templates (bootstrap on empty volume)



### Version 1.24.0 — House configurator UX & EV profile (2026-07-09)

- [x] **P1 — Data model** `ev` — type `ev` in `house_profiles.schema.json` and `house_config/profiles_store.py`; planning subset from live `eauto` without `loxone`; `house_profiles.example.json` with EV as `ev`
- [x] **P2 — UI add/remove** — `ui/house_config_profile_form.py` (tab in `page_house_config.py`): `st.session_state` consumer list, “Add consumer” / “Remove”, type dropdown incl. “E-Auto” with conditional fields
- [x] **P3 — Annual and hourly profile** — `house_config/ev_profile.py` (`estimate_ev_annual_kwh`, `ev_hourly_kw_for_day`); `baseload.py` and `data/consumption_profiles.py` with window-based `ev` branch
- [x] **P4 — Tests** — `tests/test_house_config.py`: normalization, annual kWh, hourly profile only in charging window, `build_hourly_kw_profile`
- [x] **P5 — Tariff list date in UI** — implemented with **1.24.f** (`catalog_as_of` in `planning_tariff_form.py` and `page_scenario_editor.py`)



### Version 1.24.b — LOC refactoring top 3 (2026-07-09)

- [x] **Epic 1 —** `optimizer/milp.py` (~991 → ~170) — `milp_consumers.py`, `milp_horizon.py`, `milp_result.py`; `_derive_control_from_milp` → `optimizer/battery.py`; re-exports for tests
- [x] **Epic 2 —** `config.py` (~1543 → ~720) — package `settings/` (`json_io`, `flexible_consumers`, `appliances`, `scenarios`, `system_settings`); `config.py` as orchestrator facade
- [x] **Epic 3 —** `ui/charts.py` (~2822 → ~400) — `chart_slot_axis`, `chart_trace_segments`, `chart_soc`, `chart_cumulative`, `chart_decorations`, `chart_consumer_stack`; thin facade + re-exports



### Version 1.24.a — House configurator and scenarios (2026-07-09)

- [x] **P1 — Battery & PV as entities** — `batteries[]` / `pv_systems[]` in `config.json`; scenario selects one ID each; backward compatible with flat `runtime_settings`
- [x] **P2 — Electricity tariffs** — `config/tariffs.json` with import/export tariffs; scenario references `import_tariff_id` / `export_tariff_id`
- [x] **P3 — Consumers & baseload** — `config/house_profiles.json`; generic, thermal, baseload with 5% lower bound
- [x] **P4 — Composite scenario** — `backtesting_scenarios.json`; resolution in `config.py` for `simulation/engine.py`
- [x] **P5 — UI** — house configurator (`page_house_config.py`) and scenario editor (`page_scenario_editor.py`)



### Bugfix Chart 1 PV line = actual (forecast_pv after overlay) (2026-07-08)

- [x] **Log** `forecast_pv_kw` **before live overlay** — `main.py` stores Forecast.Solar value, not `consumption_snapshot.pv_kw`; chart line vs. actual bars distinguishable
- [x] **NaN** `PV-Ist` **in MILP rows** — flow balance falls back to forecast (`chart_flow_balance.py`)



### UI S-2 — Chart 1 PV line continuous (2026-07-08)

- [x] **PV forecast line continuous** — one yellow line (`CHART_PV_LINE_COLOR`) over gray/neutral/green; overlay “PV-Prognose (Log)” removed
- [x] **Data model** — `PV-Prognose (kW)` = forecast; `PV-Ist (kW)` only for flow-balance bars in log
- [x] Tests + `docs/ui/charts.md`



### Manual appliances — Chart 1 cockpit (follow-up phase 5) (2026-07-08)

- [x] **Dedicated named traces in Chart 1 flex stack** — planned appliances from `appliance_schedules.json` as flex bars (washing machine, dryer, …), not only in `expected_p_act`/`Grundlast`; `apply_appliance_schedules_to_chart_rows` + `_finalize_chart_rows_for_display`
- [x] **Shared color, appliance-specific hover** — `COLOR_MANUAL_APPLIANCE` / `flex_bar_chart_color`; stack order in `ordered_active_consumers_for_stack`
- [x] **Live cache on plan checkbox** — `invalidate_live_optimization_cache()` on “Manuelle Geräte” after saving/deleting plan



### Version 1.23 — Manual appliances, consumer analysis & charts (2026-07-08)

- [x] **Appliance parameters in config.json** — `update_appliance_defaults()`, save form on “Manuelle Geräte”
- [x] **Star thresholds** — combined k_act/percent rule; config block `appliance_recommendation` + UI expander
- [x] **PV actual + forecast in gray area** — column `PV-Prognose-Log (kW)`, muted chart trace
- [x] **Mobile legend** — CSS + expander below Chart 1/2 (`ui/chart_legend_mobile.py`)
- [x] **Manual appliance planning → optimization** — `appliance_schedules.json`, matrix injection on `expected_p_act`, checkbox in recommendation table (immediate adoption); SMB fallback on write
- [x] **Consumer analysis Swimspa** — temperature actual/target + filter autonomous/Ernie (`page_consumer_analysis.py`)
- [x] **Version 1.23.0** — minor bump



### Bugfix Chart 1 SoC current hour before now + BL target (2026-07-08)

- [x] **Chart 1: SoC before now without MILP constant** — ramp first MILP quarter-hour → now from log extrapolation (`_current_hour_soc_ramp_before_now`, `_soc_from_history_extrapolation`); test `test_soc_intra_hour_ramp_before_now_replaces_flat_milp_head`
- [x] **Chart 1: SoC BL target not in gray area** — BL target trace only from log boundary, no bridge into gray; test `test_baseline_soc_trace_starts_at_history_boundary_not_in_gray`
- [x] **Chart 1: BL target and SoC meet at now** — shared anchor `soc_at_now` from log data; test `test_baseline_soc_meets_optimized_soc_at_now`
- [x] **Live acceptance confirmed**
- [x] **Version 1.22.5** — patch bump



### Bugfix savings manual appliances (2026-07-08)

- [x] **Delta to best time instead of savings** — column/caption “Delta to best time (€)” (`cost − cheapest`); sign `+`/`-`; red when positive, green when negative (`ui/pages/page_devices.py`, `tests/test_page_devices_display.py`)
- [x] **Rated power always editable** — `number_input` for all `power_source`; `default_power_kw` from config only as default/hint caption
- [x] **Version 1.22.2** — patch bump



### Bugfix charging_context timezone-aware live (2026-07-08)

- [x] **Streamlit TypeError naive/aware datetime** — `_align_like` in `optimizer/charging_context.py`; config windows (`car_available_from_hour`, Loxone FertigUm) aligned to timezone-aware matrix slots; tests timezone-aware horizon
- [x] **Version 1.22.1** — patch bump



### Loxberry container multi-arch (2026-07-08)

- [x] **7f — Loxberry container** — multi-arch build (`--target all`) via buildx; `docker-compose-loxberry.yml`; go/no-go in README and `container.md`; Dockerfile platform-neutral
- [x] **Version 1.22.0** — minor bump



### Bugfix Chart 1 SoC current hour (2026-07-08)

- [x] **Chart 1: extrapolate SoC after now until end of hour** — no horizontal step in neutral MILP area of current hour; ramp now → `_soc_tail_y_from_row` (`ui/charts.py`, `chart_now` passed through); live acceptance confirmed; test `test_soc_intra_hour_ramp_replaces_flat_milp_tail`
- [x] **Version 1.21.5** — patch bump



### Bugfix version display sidebar (2026-07-08)

- [x] **Version display at top of sidebar** instead of cockpit title — `app.py` (`_render_sidebar_version`), `version` parameter removed from `render_page_title_with_help`
- [x] **Version 1.21.1** — patch bump



### Bugfix Chart 2 gray/neutral bridge (2026-07-08)

- [x] **Chart 2: cost and consumption connected at gray|neutral boundary** — forecast curves accumulate from actual sum (`_bridged_forecast_cumulative_series` in `ui/charts.py`); metrics BL target / optimized / savings unchanged horizon SA₀→SA₂; tests `test_bridged_forecast_cumulative_continues_from_history`, `test_chart2_prognose_bridges_at_history_boundary`
- [x] **Version 1.21.4** — patch bump



### UI menu structure & recommendation mode manual appliances (2026-07-07)

Spec: [docs/spec/ui-menu-structure.md](docs/spec/ui-menu-structure.md). `### Version 1.21` feature block completed together.

- [x] **Menu structure as sidebar replacement** (`st.navigation` + `st.Page`) — `app.py` as router, `ui/pages/`; existing modes (cockpit, backtesting, price forecast dev) as pages (env gating preserved); raw JSON config editor (`page_config.py`); mockup pages (scenario editor, house configurator, consumer analysis); backtesting/price forecast controls moved to page body
- [x] **Recommendation mode manual appliances** — `optimizer/appliance_recommendation.py` (pure start-time/cost logic: ranking of start hours in 6-h horizon by grid import cost, 1–5 stars linear, savings vs. immediate) + tests
- [x] `ui/pages/page_devices.py` — per appliance (washing machine, dryer, dishwasher) rated power + runtime → start-time recommendation; advisory only, no Loxone switch signal
- [x] **Config** `appliances` **block** — `config.get_appliances()` + normalization, schema + `config.example.json`; `default_power_kw` as rated power for cost evaluation (required for `power_source=loxone`), `loxone_power_name` reserved for later adaptation algo
- [x] **Version 1.21.0** — minor bump



### Optimize Swimspa filter usage (2026-07-07)

Spec: [docs/spec/swimspa-filter.md](docs/spec/swimspa-filter.md). Goal: cost-optimal **supplementary** filter runtime; `Sollstunden` (debt in h) long-term → 0; native duty cycle independent.

- [x] **Code phases 1–4** — `loxone_remaining_hours`, `filter_context`/MILP blocking, schema/`config.example.json`/docs, live parser + `verify_swimspa_filter_live` / `patch_swimspa_filter_config`
- [x] **Live acceptance (user)** — prod `config.json` patched; formats `filter1hour` and `Sollstunden` confirmed on miniserver
- [x] **Deviation rules SwimSpa filter (S8–S10)** — `swimspa_filter_should_run_missing`, `swimspa_filter_runs_unexpectedly` (only outside native window), `swimspa_filter_over_nominal`; new predicates `power_ist_without_soll`, `slot_outside_native_filter_window`, `ist_power_above_nominal`; native window logged as `filter_contexts` in `optimization_history.jsonl`
- [x] **Actual power heating/filtering checked separately + case B corrected** — separate Loxone markers/keys/charts confirmed; heating meter `Ernie_Swim-Spa-P_act` measures incl. filter → `subtract_consumer_ids` subtracts filter share from heating actual (no double counting in `flex_sum_kw`/`baseload_kw`); `patch_swimspa_filter_config` extended idempotently. Follow-up (historical logs / Loxone separation) as separate 1.+1 item
- [x] **Version 1.20.0** — minor bump



### Chart 1 forecast saturation PV & baseload (2026-07-07)

- [x] **Chart 1: forecast saturation reduced for PV and baseload too** — zone logic extended from flex consumers to `PV` and `Grundlast`; history remains fully saturated, neutral and green area use same saturation factor as flex; regression tests for color derivation and zone-specific buckets added
- [x] **Version 1.19.0** — minor bump



### Debug dump preparatory work (2026-07-07)

- [x] **Reproducible repro inputs for debug dumps centralized** — shared collection in `runtime_store/debug_dump_inputs.py`; `chart_debug_capture` and `archive_prod_dump` now secure active `config.json`, `deviation_rules.json`, optional `local_settings.json`, relevant env overrides and resolved paths
- [x] **Explicitly configured additional files included in dumps** — price forecast model (`forecast_model_path`) and `cons_data_hourly.csv` archived when active reference present; focused tests for ZIP and prod dump archive added



### Consumer colors P1 — NAS deploy cleanup (2026-07-07)

- [x] **Reverted temporary local** `chart_color_index` **test** — local `config/config.json` removed; NAS path `ENERGY_OPTIMIZER_CONFIG_PATH=\\DS-KO-DO-2\docker\energy_optimizer\config\config.json` authoritative again, local override no longer active



### Consumer colors P2 — Zone-dependent saturation (2026-07-07)

- [x] **P2 — Zone-dependent saturation (Chart 1 flex bars only)** — history full palette; neutral + forecast shared `CONSUMER_CHART_SATURATION_MUTED` (0.6); slot → zone via `chart_zone_kind_for_slot_start`; flex color per slot/bucket; legend full color (`legendonly`); Sankey unchanged; tests and `docs/ui/charts.md`
- [x] **Version 1.18.0** — minor bump



### Consumer colors P1 — 8-color palette & chart_color_index (2026-07-07)

- [x] **P1 — Fixed 8-color palette &** `chart_color_index` — `CONSUMER_PALETTE` (H 260→40, S=90, L=50); `color_from_hsl()` with optional alpha; base colors as `_HSL_`* + `_ALPHA_`*; `consumer_chart_color()` central for Chart 1 (`chart_flow_balance`) and Sankey; `chart_color` removed, schema/`config.example.json` with indices SwimSpa=0, E-Auto=2, Wärmepumpe=7; tests and `docs/ui/charts.md`



### Centralize chart colors (2026-07-07)

- [x] **Phases 1–4** `ui/chart_colors.py` — single source for zones, energy balance bars, Chart 1 lines/overlays, Chart 2 costs, Sankey, flex palette, legacy control-command bars; `chart_flow_balance`, `charts`, `sankey`, `sankey_produktiv`, `planning_window` consumers only
- [x] **Version 1.17.3** — patch bump



### Bugfix Chart 1 zones & bar X (2026-07-07)

- [x] **Bars invisible in green zone SA₀→SA₁** — `ChartSlotAxis.at()` ignored `slice(start, end)`; extrapolation bars landed at chart start instead of green zone (`ui/charts.py`); regression tests
- [x] **Zone colors gray/green centralized & more contrast** — `ui/chart_colors.py` with `hsl`, `blend_hsl`, `rgba_from_hsl`, `CHART_ZONE_HISTORY_FILL`, `CHART_ZONE_FORECAST_FILL`; forecast deliberately yellow-green (H≠120) instead of material green; connection `data/planning_window.py`
- [x] **Version 1.17.2** — patch bump (two bugfixes)



### Chart 1 up/down energy balance (2026-07-06)

- [x] **Better visualize discharge lock** — yellow-black striped band below SoC (`ui/charts.py`)
- [x] **Up/down bars** instead of battery/consumer bars — basis `ui/chart_flow_balance.py`, `ui/flow_balance_allocate.py`
- [x] **Color palette grid & battery** — grid blue, battery flows muted (HSL in `ui/chart_colors.py`); scenarios A–I, `docs/ui/charts.md`
- [x] **PV surplus & full battery** — SoC edge correction (MILP); scenario I; prod log: actual `battery_kw` from `consumption_snapshot` → `Ist Batterie-Leistung (kW)` (`runtime_store/history_timeline.py`)
- [x] **Grid and baseload lines removed** — display only via up/down bars (`ui/charts.py`)
- [x] **SoC timeline** — shared color optimized + “SoC BL Ziel” via `_HSL_SOC` in `ui/chart_colors.py`
- [x] **Version 1.17.0** — minor bump after completed Version-0.+1 block Chart 1



### UI S-2 cold start & price forecast logging (2026-07-06)

- [x] **Initial UI rendering (SA-2-SA)** — cold start ~112 s → ~7 s: archive EU feature fetch for future slots skipped (`_archive_covers_slot_range` in `data/price_forecast_live.py`); JSONL in-memory cache in `runtime_store/optimization_history.py`
- [x] **Terminal warning EU features (Open-Meteo 400)** — `print()` replaced by `logging`; expected live case only `logger.debug`, API errors as compact `logger.warning` without full URL



### Price forecast (EU weather & generation) epic completed (2026-07-06)

- [x] **Price forecast (EU weather & generation):** correlation model for green zone (no day-ahead until SA₂) instead of mirroring — wind + solar at EU level; spec [price-forecast-renewables.md](docs/spec/price-forecast-renewables.md)
- [x] **Phase 0:** scope defined (AT day-ahead, EU countries, OLS, acceptance)
- [x] **Phase 1:** dataset pipeline `data/eu_market_features.py`, `scripts/build_price_training_dataset.py`, `data/cache/price_training_*.csv`
- [x] **Phase 2:** OLS + walk-forward; **extended** (+ EU load/residual load) via `enrich_price_training_dataset` + `compare_price_forecast_features`; bias correction (non-peak P90)
- [x] **Phase 3:** UI eval (`ui/price_forecast.py`); live in `resolve_market_slots` (`data/price_forecast_live.py`, `data/profile_manager.py`); `config.market_prices.missing_price_strategy` (`mirror`  `forecast`, default **forecast**)
- [x] **Annual comparison 2025:** `run_price_strategy_backtests` (333 windows, `sunset_window`, all scenarios); report `backtesting_logs/price_strategy_compare/comparison.md` — forecast vs. mirroring marginal (±0.1–0.6%), go-live with `forecast`
- [x] **Rolling bias recalibration** — deferred; static P90 bias correction at training remains active for live



### Price forecast backtesting annual comparison (2026-07-06)

- [x] **Backtesting annual comparison (infrastructure):** green zone in `sunset_window` — day-ahead cutoff, mirroring vs. OLS (`data/backtesting_prices.py`, `resolve_market_slots` forecast); `--price-strategy` / `--output-dir` in `run_backtesting`; orchestrator `run_price_strategy_backtests` + `compare_price_strategy_backtests`; tests



### Price forecast UI via config.json (2026-07-06)

- [x] **Extra UI page for price model activatable via config.json** — `ui.price_forecast_page_enabled` (default: `false`); without `ENERGY_OPTIMIZER_UI_MODES` only Sunset-2-Sunset + backtesting, price forecast (dev) optional via config; env variable still takes precedence (`ui/mode_selector.py`, `config.py`, schema/example, tests `tests/test_mode_selector.py`)



### Bugfixes: test fixtures & heat pump (2026-07-06)

- [x] **Test data executable on fresh checkout** — prod dump fixtures added (`.gitignore` exceptions, `scripts/complete_prod_dump_fixtures.py`), thermal CSV fixtures (`tests/fixtures/thermal/`), smoke tests on `tests/fixtures/historical/cons_data_hourly.csv`; **551 passed** (commit `71a4764`)
- [x] **Heat pump restored in** `config.json` — entry `flexible_consumers[id=waermepumpe]` from production backup (`config_back.json`, commit `3b7fa1c`): `Ernie_WP_Freigabe`, `Ernie_WP_P_act`, historical daily target, `chart_color` `#ff9800`; also `config.example.json`
- [x] **Target/actual notice: heat pump did not start** — rule `waermepumpe_enable_no_start` (category notice), docs/scenario S5, seed script and tests



### Chart 1 stacked flex consumers (2026-07-06)

- [x] **Chart 1: variable flex consumers as stacked negative bars** — one bar per slot (same X position as battery, `barmode=overlay`, stacking via `base`); sort by horizon energy SA₀…SA₂, cache until next SA₀; colors via `flexible_consumers.chart_color` in `config.json`; tests `tests/test_chart_consumer_stack.py` (`ui/charts.py`, `config.py`)
- [x] **Version 1.15.0** — minor bump after completed Version-0.+1 item; rule `.cursor/rules/versioning.mdc` (minor vs. patch)



### UI S-2 nav & help icons mobile (2026-07-06)

- [x] **Compact S-2 navigation** — `←` / `Heute` / calendar icon / `→` in `st.container(horizontal=True)`; date selection in popover (only SA₀ days with log); `Heute` and cycle logic in `ui/s2_navigation.py`, `ui/chart_context.py`, `ui/history_navigation.py`
- [x] **Mini help icons** — material icon + tertiary popover instead of `?` button; horizontal layout without extra row on mobile; CSS in `ui/styles.py` (`inject_help_hint_css`); `ui/help_hint.py`, `ui/countdown.py`



### Discharge lock: grid trickle charging (2026-07-06)

- [x] **Bugfix: SOC rose when holding from grid (05.07. ~22–23 h)** — prod log (`runtime-prod/runtime.zip`): PV=0, `battery_plan_kw=0`, measured ~0.2 kW charging + grid import; cause `target_soc_percent=100` with Huawei control command 1; fix: at `MODE_ENTLADESPERRE` `target_soc = current_soc` (`optimizer/milp.py`); test `test_entladesperre_target_soc_matches_current_soc`



### Migration script removed (2026-07-05)

- [x] `scripts.migrate_persist_layout` **deleted** — one-time migration config/ + runtime/ no longer needed; script, test, `ernie-migrate-layout` entrypoint and doc references removed



### Chart 1 target/actual markers NAS (2026-07-05)

- [x] **Bugfix: Chart 1 target/actual markers missing on NAS despite same** `optimization_history.jsonl` — cause missing `config/deviation_rules.json` (and templates) on NAS config volume; without rules file `deviation_timeline` suppresses all events silently. Fix: files manually copied to NAS; bootstrap creates `deviation_rules.example.json`, `deviation_rules.schema.json` and `deviation_rules.json` from image template; Dockerfile `share/config/` extended (`runtime_store/bootstrap.py`)



### UI S-2 Chart 2 savings text (2026-07-05)

- [x] **UI S-2 Chart 2: savings text annotations in both segments** — `show_cost_summary` no longer tied to `not split_mode`; annotations (`BL Ziel`, `Optimiert`, `Ersparnis`) in SA₀→SA₁ and SA₁→SA₂ with full-horizon values from `_cost_totals_from_savings`; test `test_chart2_s2_split_mode_shows_cost_summary_annotations` (`ui/charts.py`)



### Chart 2 actual cost log area (2026-07-05)

- [x] **Bugfix Chart 2: actual cost in gray log area constantly 0 €** — `entry_to_chart_row` uses `consumption_snapshot.grid_kw` for grid import when snapshot present instead of target balance (PV + `battery_plan_kw`); `_netzbezug_kw_from_entry` in `runtime_store/history_timeline.py`; regression test `test_build_chart_history_uses_snapshot_grid_kw_for_slot_cost`



### UI Chart 1 SoC bridge log/MILP (2026-07-05)

- [x] **Bugfix Chart 1: SoC gap gray → neutral (log/MILP boundary)** — `add_optimized_soc_trace` incorrectly disabled `bridge_left` at `history_slot_count`; bridge point like neutral→green active again; test `test_soc_trace_bridges_at_history_boundary` (`ui/charts.py`)



### UI Chart PV time base (2026-07-05)

- [x] **PV power correctly positioned on X-axis** — cause: smooth linear interpolation between slot starts let PV rise before sunrise (raw hourly data from slot start was plausible); fix: PV anchors at **slot center** (`_LINE_ANCHOR_SLOT_CENTER` in `_add_pv_trace`, `ui/charts.py`); regression test `test_chart1_pv_center_anchor_avoids_early_morning_ramp`; S-2 nav between Chart 1/2 extracted from fragment (`StreamlitFragmentWidgetsNotAllowedOutsideError`, `ui/live_mode.py`)



### UI fragment refresh (2026-07-05)

- [x] **UI: fragment refresh separately configurable** — `ui/fragment_refresh.py`; Charts 1+2 **60 s** (`ui/live_mode.py`), Sankey/countdown **10 s** (`ui/sankey.py`, `ui/countdown.py`); optional `config.json` → `ui.fragment_refresh_charts_sec` / `ui.fragment_refresh_status_sec` or env `ENERGY_OPTIMIZER_UI_FRAGMENT_CHARTS_SEC` / `ENERGY_OPTIMIZER_UI_FRAGMENT_STATUS_SEC`; schema/example, tests `tests/test_fragment_refresh.py`



### Historical tests & energy balance (2026-07-05)

- [x] **stderr warning** `Keine historischen Daten in cons_data_hourly` — `profile_manager.get_historical_day_data`: `cons_data_hourly.csv` missing or empty (date in message = requested day, typically today via `consumer_targets` in live UI); output via `print()` → stderr; fallback baseload 0.5 kW/h, consumer daily targets 0; remedy: maintain `runtime/cons_data_hourly.csv` (`main.py` or `scripts/generate_cons_data.py`)
- [x] **Pre-commit / validate historical test suite** — catch-up after `--no-verify` (commit `8721df2`): `pytest tests` incl. 25× `test_historical_24h_consistency` green; pre-commit hook usable again for code changes
- [x] `runtime/cons_data_hourly.csv` regenerated from Loxone logs (≥12 months retention)
- [x] **Test fixture** `tests/fixtures/historical/cons_data_hourly.csv` + `scripts/extract_historical_fixtures.py` (isolated from runtime)
- [x] `test_historical_24h_consistency.py`**:** fixture path, parametrized consistency runs green
- [x] **Bugfix** `simulate_horizon`: `finalize_chart_row_energy` after each hour — grid import consistent with rounded flex columns (Δ 8 W on case `2026-03-21_high_pv`)
- [x] **Test suite inventory (optional / env, no blocker):** Loxone integration (`test_loxone_integration.py`, 5× skip without env), thermal CSV fixtures (`tests/fixtures/thermal/` missing, 2× skip) — deliberately left open unchanged



### UI main.py sync (2026-07-05)

- [x] **Clarify duplicate UI wait time after main.py run**
  - Cause: fixed 60-s phase (`delay`) without `completed_at` check, then up to 120 s grace (`wait_main`) — felt like waiting twice
  - Fix: early exit on sync in current slot; max. 60+30 s wait; UNC read fix in `run_state`; unified UI notice; tests `tests/test_schedule.py`
- [x] **UI: main.py sync faster after run** — fallback **15+15 s** (`optimizer/schedule.py`); display “next sync at latest in X s” instead of full fallback countdown (`sync_ui_countdown_seconds`, `ui/main_py_sync.py`); 15-s poll fragment `poll_main_py_sync_if_pending` + footer (`ui/countdown.py`, `app.py`); config `ui.main_sync_poll_sec` / env `ENERGY_OPTIMIZER_UI_MAIN_SYNC_POLL_SEC`; tests `tests/test_schedule.py`, `tests/test_main_py_sync_ui.py`



### UI Sunset-2-Sunset epic completed (2026-07-05)

- [x] Prod cockpit **Sunset-2-Sunset** (`ENERGY_OPTIMIZER_UI_MODES=sunset2sunset,backtesting`); replaces realtime, historical day, production archive
- [x] Phases 1–3 UI + follow-up layout; phase 4 P4a–P4c (operating modes docs, deployment cross-references, navigation tests); P4d dropped
- [x] Spec [docs/spec/ui-sunset2sunset.md](docs/spec/ui-sunset2sunset.md) **v0.7.0**; app version **1.14.0**

- Follow-ups (standalone in Backlog): target/actual deviation, backtesting recalculation, price mirroring, optional layout/mobile



### UI Sunset-2-Sunset — Phase 4 P4d dropped (2026-07-05)

- [x] **P4d** removed — dedicated missing-slots tests dropped; coverage via existing chart/table tests (spec §6)



### UI Sunset-2-Sunset — Phase 4 P4c navigation tests (2026-07-05)

- [x] **P4c** `tests/test_s2_navigation.py`: `segment_navigation_label`, `max_sunrise_cycle_offset`, `build_live_chart_context` (segment/cycle window, zone_reference, max_cycle ↔ nav); spec §4



### UI Sunset-2-Sunset — Phase 4 P4b deployment & cross-references (2026-07-05)

- [x] **P4b** `docker-compose-synology.yml` confirmed (`sunset2sunset,backtesting`); `betrieb.md`, `container.md`, `docs/README.md`, `charts.md`, `ueberblick.md`, `preise.md`, `batterie-pv.md`; spec status phases 1–3 completed



### UI Sunset-2-Sunset — Phase 4 P4a operating modes docs (2026-07-05)

- [x] **P4a** `docs/ui/betriebsmodi.md` per spec v0.6.2: Sunset-2-Sunset (prod), backtesting (dev); SA₀→SA₁/SA₁→SA₂, navigation, panels, metrics now→SA₂; dropped modes; env var `sunset2sunset,backtesting`



### UI Sunset-2-Sunset — Follow-up layout (2026-07-05)

- [x] **Layout-a** navigation compact between Chart 1 and Chart 2; segment label in Chart 1 heading (`ui/history_navigation.py`, `ui/charts.py`, `ui/simulation_results.py`, `ui/live_mode.py`)
- [x] **Layout-b** help “?” (`ui/help_hint.py`, `st.popover`): zones (Chart 1), Chart 2 actual/forecast, sync wait time, mode scope at page title; version as caption next to title
- [x] **Data basis** expander in footer below separator, before optimization cadence (`ui/countdown.py`, `app.py`)
- [x] **H2/H6/H7** deliberately unchanged (no “current hour” notice; table/energy comparison expanders unchanged)
- [x] Docs: `docs/ui/charts.md`, spec §7.1 in `docs/spec/ui-sunset2sunset.md`



### UI Sunset-2-Sunset — Phase 3 charts & metrics completed (2026-07-05)

- [x] **Phase 3 (P3a–P3d)** — Chart 2 actual/forecast, SA markers, legacy cleanup prod UI, metrics horizon now→SA₂; details in sub-items below



### UI Sunset-2-Sunset — Phase 3 P3d metrics horizon now→SA₂ (2026-07-05)

- [x] **P3d** savings/cost metrics and energy comparison over full matrix (now→SA₂), not chart segment; labels “(24h)” removed; `[:24]` cleaned up for baseload/profile targets (`ui/chart_context.py`, `ui/simulation_results.py`, `ui/charts.py`, `optimizer/targets.py`, `data/consumer_targets.py`); tests `test_horizon_targets.py`, `test_chart_context.py`



### UI Sunset-2-Sunset — Phase 3 P3c legacy paths removed (2026-07-05)

- [x] **P3c** `history_offset_days`, production archive navigation, mode “Historischer Tag” and `render_historical_`* removed from prod UI; S-2 only `render_s2_navigation` (`ui/history_navigation.py`, `ui/live_mode.py`, `app.py`, `ui/mode_selector.py`); `ui/historical.py` deleted; tests `test_mode_selector.py`



### UI Sunset-2-Sunset — Phase 3 P3a Chart 2 actual/forecast (2026-07-05)

- [x] **P3a** Chart 2: “actual so far” (log) and “optimized forecast” (MILP) separated, no bridge at log/MILP boundary; matrix index fix for SA₁→SA₂; matched baseline over full matrix (`ui/chart_context.py`, `ui/charts.py`, `optimizer/simulation.py`); tests `test_chart2_s2_split.py`, `test_chart_context.py`



### UI Sunset-2-Sunset — Phase 3 P3b SA markers (2026-07-05)

- [x] **P3b** vertical markers SA₀/SA₁/SA₂ in chart (anchors only in visible window); **now** only live segment SA₀→SA₁ (`ui/charts.py`, `ui/simulation_results.py`); tests `test_chart_ui_bugs.py`



### UI Sunset-2-Sunset — Chart display (2026-07-05)

- [x] **SOC jumps / missing log slots (spec §6)** — orange vrect in chart and table rows for `SLOT_MISSING`; visible SoC gaps at log/MILP boundary (no false bridge point) and neutral→green (extrap start); no more UTC offset on SoC/price X
- [x] **SoC gap at neutral→green transition** — extrapolated segment without bridge point (`bridge_left` incorrectly disabled for entire MILP); fix: only at log/MILP boundary (`abs_start == history_slot_count`); test `test_soc_trace_bridges_extrapolation_start`
- [x] **No line style/opacity change in green zone** — dotted price line and 50% opacity extrapolated traces removed (marking only green background, spec §5)
- [x] **SoC/price time reference in chart** — Plotly X for SOC and price traces incorrectly created as `datetime64[ns, UTC]` (+2 h offset in CEST, looked like missing lines to axis edge); fix: `_chart_time_series()` in `ui/charts.py`; test `test_soc_and_price_traces_align_with_slot_datetimes`
- [x] **Gray/green zone at X-axis edges** — variable slot duration in `ChartSlotAxis`; zones on display slots (`ui/simulation_results.py`); window edge SA₀/SA₁ via `x_range(range_start=chart.start)`; full gray zone for past cycles (`is_live_segment=False`)
- [x] **15-min → 1-h mixed axis** — price hourly HV step at slot boundaries; bar width per slot (`_bar_widths_ms`); zones/vrect on `display_ctx.slot_datetimes`
- [x] **SU marker removed** — only now + SA (SOC)
- [x] **Tests:** `tests/test_chart_ui_bugs.py`, `tests/test_chart_mixed_resolution_traces.py` (time reference, zones, extrap bridge, mixed axis)



### UI Sunset-2-Sunset — Navigation SA cycles (2026-07-04)

- [x] **Symmetric cycle navigation** — `ui/s2_navigation.py` (pure state logic); `ui/history_navigation.py`: “Vor →” at `cycle_offset > 0` one cycle toward live, at `cycle_offset == 0` switch SA₁→SA₂; cycle back sets segment to SA₀→SA₁ — **in prod fundamentally ok** (2026-07-04)
- [x] **Crash on cycle back fixed** — missing SoC in history window (`TypeError` in `_soc_tail_y_from_row`); baseline SoC from `history_only`; `None`/NaN-safe SoC lines (`ui/charts.py`, `ui/simulation_results.py`)
- [x] **Tests:** `tests/test_s2_navigation.py`, `test_soc_tail_y_returns_none_for_missing_soc`



### Simulation table & data basis UI (2026-07-04)

- [x] **Freeze header and time column** — scrollable HTML table with CSS freeze panes (`ui/simulation_table_view.py`); orange rows via Pandas Styler
- [x] **Data basis notice as expander** — collapsed only production log path, expanded full merge/runtime text
- [x] **Layout:** simulation table directly below chart, before energy comparison
- [x] **Tests:** `test_simulation_results_table`, `test_production_log_source`



### UI Sunset-2-Sunset Phase 2 — fill past (2026-07-04)

- [x] **Data layer v0.6.1:** `build_chart_history`, `build_chart_display_context` — 15-min production log (no hold-forward in live chart), MILP tail (1 h or 15-min target from x:15)
- [x] **Chart + table:** shared merge path (`display_ctx`), target from `consumer_powers_kw`; data basis notice (runtime path, merge status)
- [x] **Simulation results table:** log/MILP mix, data source column, `st.table`, flex kW columns moved forward; orange for missing log slots
- [x] **Chart vs. table gray area:** deviation was display type (`st.dataframe`, column mix-up); `chart_key` for live chart
- [x] **Production log:** `k_push_act`, feed-in compensation and `sofort_laden` in table rows; TZ fix for `completed_at` lookup
- [x] **Tests:** `test_chart_history`, `test_simulation_results_table`, `test_production_log_source`
- [x] **Diagnosis:** `scripts/_diag_swimspa_nas.py` (NAS `optimization_history.jsonl`)



### Dev environment NAS production log (2026-07-04)

- [x] **VS Code launch “Streamlit app.py (NAS Produktiv-Log)”** — `ENERGY_OPTIMIZER_RUNTIME_DIR` and `ENERGY_OPTIMIZER_CONFIG_PATH` to NAS paths (`.vscode/launch.json`)
- [x] **Local production runtime cleaned up** — accidental use of local logs excluded; historical EV baseline test skips without local `cons_data`



### UI Sunset-2-Sunset Phase 1 (2026-07-04)

- [x] **Phase 1 — Mode & window:** `mode_selector`, `app.py`, sidebar without adaptive PV tuning; Sunset-2-Sunset mode in UI
- [x] **Phase 1b — MILP until SA₂ (spec correction):** `compute_planning_window` — horizon end sunrise SA₂; tests and spec adjusted



### Live chart IndexError cumulative costs (2026-07-04)

- [x] **IndexError in production UI fixed** (`_segment_connected_line_xy`, cumulative costs/consumption)
  - Cause: hourly cost lists shorter than sunrise→sunrise chart window (matrix vs. `display_df`)
  - `align_hourly_values_to_chart_slots` in `ui/chart_context.py`; padding in `ui/charts.py`
  - Release **1.13.1**



### Cursor session conclusion (2026-07-04)

- [x] **Automate two-phase session conclusion**
  - Phase 1: maintain `Backlog.md`, commit and push all open changes (ask about local/temporary files)
  - Phase 2: optionally build Docker image and push to ghcr.io (`python -m scripts.build_container --push`)
  - Skill: `.cursor/skills/session-abschluss/SKILL.md`; rule: `.cursor/rules/session-abschluss.mdc`
  - Hook: `docker push` requires explicit confirmation (`.cursor/hooks/approve_docker_push.py`)
  - Trigger: “end session”, “backlog sync”, “commit and push”



### Configuration dev/prod (2026-07-04)

- [x] **Central** `config.json` **addressable via NAS path**
  - Path via `ENERGY_OPTIMIZER_CONFIG_PATH` (in `.env`, see `.env.example`); dev example: `\\DS-KO-DO-2\docker\energy_optimizer\config\config.json`
  - Fallback unchanged: `config/config.json` → legacy `config.json` in project root
  - Docker/Synology: volume `./config` → `config/config.json` in container
- [x] `loxone_silent_mode` **moved to local file**
  - Machine-specific: `runtime/local_settings.json` (template `runtime/local_settings.example.json`)
  - Optional: `ENERGY_OPTIMIZER_LOCAL_SETTINGS_PATH`; bootstrap creates missing file
  - Removed from central `config.json` / schema / example; remaining key there → clear error message
  - Tests: `tests/test_local_settings.py`



### Sunset planning horizon + SOC_min at sunrise (2026-07-04)

- [x] **Main feature completed** (branch `feature/sunset-planning-horizon`, merged)
  - Spec: [docs/spec/planning-horizon-sunset.md](docs/spec/planning-horizon-sunset.md)
  - Window: now→SA₁ + SA₁→SA₂; hard SOC boundary at next sunrise; then free until SA₂
  - Replaces `battery_end_soc_equals_start` in live operation
  - Backtesting: EV `ready_by_hour` anchor; `--horizon-mode fixed_24h|sunset_window`
  - Decision: **live** `sunset_window`; **backtesting reference** `fixed_24h` (10 kWh dyn. ~779 € vs. sunset ~784 €/yr; earlier sunset advantage was plausibility artifact)
- [x] **Phase 1:** `data/planning_window.py` + tests
- [x] **Phase 2:** generalize matrix/prices/PV, MILP SOC anchor
  - Day-ahead for variable window length (`resolve_market_slots`); aWATTar fetch until SA₂
  - Price mirroring: same time of day, up to 7 days back; aWATTar lookback for mirror sources
  - Timezone alignment planning slots ↔ aWATTar (`Europe/Vienna`)
  - Loxone verify: missing EV completion time only **warning** (not connected)
- [x] **Phase 3:** `main.py`, live simulation — **live run verified 2026-07-04**
- [x] **Phase 4:** UI sunrise→sunrise with zone colors — **verified 2026-07-04** (replaced by epic **UI Sunset-2-Sunset**: SA₀→SA₁/SA₁→SA₂, new zone logic)
  - UI live: sunrise→sunrise; zones gray (past) / neutral (now→SA) / green (remainder)
  - `ui/chart_context.py`: chart window, row alignment, cost sum only over sunrise→sunrise
  - Live navigation ←/→; button **Produktiv-Archiv** for 24h history (Sankey/countdown disabled there)
  - Placeholder slots in chart: NaN-safe helpers in `ui/charts.py`
  - Debug snapshot: `slot_datetime` (pandas Timestamp) JSON-serializable; persist after chart render
  - Sankey **energy flow (live)** unchanged below charts in `app.py`
- [x] **Phase 5:** backtesting comparison fixed_24h vs sunset_window — **completed 2026-07-04**
  - CLI `--horizon-mode`; log field `period.horizon_mode`; backtesting default `fixed_24h`
  - No rolling re-optimization in backtesting (1× MILP per anchor step; spec section 4.2)
  - Sunset path in `simulation/engine.py` (MILP now→SA₂, 24h output/step)
  - Performance: sunset matrix truncated to 24 h before `simulate_horizon` (full SA₂ matrix would be ~36–39 MILP/step)
  - Annual backtest 2025 both modes; plausibility sunset **333/333** after baseload overlay fix
  - **Baseload overlay** in `build_sunset_window_matrix`: 24h `expected_p_act` from step matrix
  - Diagnosis scripts: `scripts/diagnose_sunset_plausibility.py`, `scripts/debug_sunset_matrix_alignment.py`
  - Annual run log: `backtesting_logs/horizon_compare_2025_full_sunset_window_v3.log`
  - Cost comparison: reference 1,195 €; fixed_24h 10 kWh dyn. 779 €; sunset 784 € (savings vs. historical 416 € or 411 €)



### Config cleanup planning horizon (2026-07-04)

- [x] `battery_end_soc_equals_start` **removed** (NAS config, schema, example, `get_battery_params`, test fixtures)
  - Terminal SOC only via `terminal_soc_percent` (backtesting `fixed_24h`) or sunrise anchor (live `sunset_window`)
  - No separate config parameter anymore



### Epic target/actual (2026-07-05)

- [x] **Target/actual deviation in Chart 1** — notice / warning / error icons in gray production log area
  - Spec [docs/spec/soll-ist-abweichung.md](docs/spec/soll-ist-abweichung.md) v0.2 · rules `config/deviation_rules.json`
  - P1–P4: facts, rule engine, slot evaluation, chart markers, scenario catalog S1–S7, [docs/ui/charts.md](docs/ui/charts.md)
  - Dev test: `scripts/seed_deviation_test_log.py`, VS Code launch **Streamlit app.py (Deviation-Test)**



### Consumption history live (2026-07-04)

- [x] **First step** of consumption history in live mode (production archive, 96×15 min) — full integration → epic **UI Sunset-2-Sunset**



### EV MILP (2026-07-04)

- [x] **Hybrid delivery / preset rest:** experimentally discarded (annual backtest 2025)



### Optimization & feed-in (2026-07-03)

- [x] **Battery degradation as penalty factor in MILP objective**
  - `optimizer/battery_wear.py`, config block `battery_wear`; throughput model (2.5 ct/kWh at 5 kWh: 1500 € / 6000 cycles / 50% cycle-related)
  - Annual backtest 2025: ~33 €/yr less net benefit vs. without wear; savings ~416 € (10 kWh dynamic) — parameters **plausible**
- [x] **Monthly fixed feed-in tariffs in backtesting**
  - `fixed_monthly_feed_in_rates` in `backtesting_scenarios.json`; tariff = calendar month of hour
  - `get_backtesting_feed_in_settings()`; edge window Dec 2024 added
  - Annual backtest 2025: **333/333** plausibility (log `backtesting_logs/backtesting_2025_wear_monthly.log`)



### Backtesting & CBC (2026-07-03)

- [x] **Baseload validation (backtesting)**
  - `simulation/baseload_validation.py`; separate plausibility baseload + flex + total
  - `scripts/analyze_plausibility_failures.py`
- [x] **EV MILP (phases 1–4)**
  - Phases 1–4: logged_day binary, preset, live mode A/B, tie-break; config `eauto_milp`
  - Annual backtest 2025 (phases 3+4): 303/333 plausibility, 10 kWh dynamic 774.51 € (`backtesting_logs/backtesting_2025_phase34.log`)
- [x] **UTF-8 for backtesting logs**
- [x] **CBC two-stage solver** (`cbc_gap_rel`, strict timeout 3 s)
- [x] **CBC gap diagnosis** (`scripts/bench_cbc_gaps.py`, `analyze_benchmark_window.py`)
- [x] **Backtesting urgent / time window** (logged_day without urgent constraint)
- [x] `run_backtesting` **parallelized** (`--workers N`)
- [x] **Dynamic feed-in (Awattar SUNNY Spot)** + MILP `k_push_act` from matrix



### Older milestones (brief)

- [x] MILP optimization (PV/consumption), NAS deployment, Sankey/UI, versioning
- [x] Flexible consumers (EV, SwimSpa, HP), historical simulation, 24 h test suite
- [x] EV: variable power, PV follow, event trigger, SOFORT-LADEN, Loxone debug
- [x] Charts (savings, feed-in), silent mode, 24h horizon, refactoring
- [x] Thermal models (Swim-Spa prio1, HP indirect), dynamic feed-in (preliminary stage)
- [x] Packaging 7a–7d (pyproject, bootstrap, build, Streamlit external)