# Szenario-Explorer — consumption model (Version 2.0)

Developer reference for SE / greenfield backtesting load paths.

## Two load paths

| Path | Source | Used for |
| ---- | ------ | -------- |
| **Baseline** | House profile default schedules and/or `cons_data_hourly.csv` | Reference €, SE “Referenz-Verbrauch”, UI dashed lines |
| **Optimized** | MILP output from `simulate_horizon` | Plausibility, SE solid lines, `backtesting_hourly.csv` consumption columns |

### Gesamtkosten column `Jahres Verbrauch [kWh]`

UI helper `_jahres_kwh_for_row` (`ui/backtesting_results_helpers.py`) uses **asymmetric** sources on purpose:

| Row | kWh source |
| --- | ---------- |
| `historical_reference` | Period sum of live `cons_data` `total_kw` (`reference_kwh_for_period`) |
| Scenario reference (`ref__*`) | Sum of window `historical_kwh` from parent scenario plausibility (`profile_spec` or logged) |
| Optimized scenario | Sum of window `optimized_kwh` |

So Historisch can differ from all other rows when meter totals ≠ house-profile spec. User-facing explanation: `docs/user-manual/Benutzer-Handbuch-Earnie.md` and `docs/ui/betriebsmodi.md`.

`consumption_source` on resolved scenario settings:

- `profile_spec` (default when `house_profile_id` is set) — optimization uses profile spec, not cons_data replay
- `logged_day` — prod replay from cons_data window sums

## MILP-flex registration from house profiles

Profile consumers are merged into `flexible_consumers` via `_planning_flex_consumers` in `house_config/scenario_resolution.py` (`collect_planning_flex_consumers`).

| Profile `type` | MILP-flex when | Bridge function | MILP mechanism |
| -------------- | -------------- | --------------- | -------------- |
| `generic` | `earnie_role: flex` | `planning_consumer_to_milp` | `generic_flex_window` |
| `generic` | `earnie_role: known` | — (fixed overlay only) | — |
| `generic` | `earnie_role: manual` | — (fixed overlay like known; recommendation UI only) | — |
| `ev` | `charging_schedule` present | `planning_ev_to_milp` | `charging_schedule` + deadline |
| `thermal_annual` | — | MILP when not CSV; CSV → fixed overlay | `thermal_annual` targets or overlay |
| `thermal_rc` | no `use_profile_csv` | `planning_thermal_rc_to_milp` | RC thermal control; `profile_spec` window target via modeled/climate kWh (`planning_thermal_rc_daily_targets`) |
| `thermal_rc` | `use_profile_csv` | — (CSV fixed overlay, not MILP) | — |

`split_planning_generic_consumers` puts **both** `known` and `manual` into the fixed baseload overlay. SE / live planning assume the user starts manuals at the recommended default schedule; `earnie_role: manual` still drives **Betrieb → Manuelle Geräte** only (not MILP shift).

Greenfield `config.json` keeps `flexible_consumers: []`; shiftable loads come from the house profile.

## UI flex discovery (Chart 1 / Sankey / MILP)

All three paths share one resolved flex list via `simulation.engine.resolved_flexible_consumers()`:

| Context | Resolution |
| ------- | ------------ |
| **MILP / backtesting matrix** | `_planning_flex_consumers` merged with `config.json` `flexible_consumers` (`merge_flexible_consumers`) |
| **Live cockpit / Sankey** | `resolved_flexible_consumers(config.get_resolved_runtime_settings())` when `house_profile_id` is set |
| **Backtesting Chart 1** | Snapshot `meta._flexible_consumers` (MILP run), else `flex_consumers_from_snapshot()` → scenario resolve |

Backtesting display bundles carry `flex_consumers` into Chart 1 via `chart_flex_consumers_context` so segments match the simulated scenario, not the live runtime profile.

If a `{name} (kW)` column has energy but is missing from the registry, Chart 1 falls back to discovering it from the dataframe (legacy snapshots / partial migration).

### EV bridge vs prod `flexible_consumers`

Bridged EV entries mirror prod shape (`signal_type: power`, `daily_target_source: config`, `charging_schedule.enabled: true`) but omit Loxone I/O. Capacity is read from `battery_capacity_kwh` on the consumer or `charging_schedule.battery_capacity_kwh` via `resolve_consumer_battery_capacity_kwh()` before falling back to Loxone.

### Greenfield test matrix (`mein_haushalt`)

| Consumer ID | Type | MILP-flex |
| ----------- | ---- | --------- |
| `standard` | generic (`start_shift_h: 6`) | yes |
| `waschmaschine` | generic (`start_shift_h: 8`) | yes |
| `ev` | ev | yes |
| `haus` | thermal_annual | no (fixed overlay) |

Scenarios `live` and `s3-no-battery` in `greenfield/config/backtesting_scenarios.json` both reference `mein_haushalt`.

## Reference € (backtesting)

`historical_reference` is built from the live scenario with **no battery and no PV** (`strip_assets_for_reference` in `house_config/entity_resolution.py`): profile load at live tariffs, direct grid balance, no flex scheduling.

Per-scenario mapping (`build_per_scenario_reference_costs`):

| Scenario hardware | Reference column |
| ----------------- | ---------------- |
| No PV (e.g. `s2-kein-pv`) | `historical_reference` (shared) |
| With PV (e.g. `live`, `s3-no-battery`) | `ref:<scenario_id>` with that scenario's PV |

Battery is never part of reference economics; PV follows the resolved scenario, not always live's PV.

## House-profile historical CSV (`profile_csv` / `use_profile_csv`)

Per-consumer historical power series live on the house profile (not live `path_historical_log`):

| Key | Effect |
| --- | ------ |
| `profile_csv` | Path to normalized `timestamp;power_kw` (≥12 months after import) |
| `use_profile_csv` | `true` → use CSV load instead of synthetic schedule/model **and** subtract that series from `total_profile_csv` when Hauskonfigurator residual helpers compute meter residual |

Scenario Explorer overlays and synthetic `cons_data` generation (`build_synthetic_dataframe_from_house_profile`, `hourly_kw_by_consumer_for_timestamps`) use the same **metric** Basislast as Hauskonfigurator Verbrauchsprofil (Modell) and MILP `profile_spec`: `baseload_kwh / 8760`. They do **not** use meter residual from `total_profile_csv` (that CSV remains for Ist-vs-Modell validation in the house configurator).

When synthesizing `cons_data`, `total_kw` = metric baseload + Σ(consumers).

## Related modules

- `house_config/planning_flex_bridge.py` — bridges, targets, consumption source
- `simulation/engine.py` — `resolved_flexible_consumers`, `flex_consumers_from_snapshot`, plausibility
- `ui/chart_consumer_stack.py` — Chart 1 stack order and flex discovery
- `ui/backtesting_display_bundle.py` — passes resolved flex into backtesting Chart 1
- `ui/backtesting_scenario_consumption.py` — baseline vs optimized charts
- `tests/fixtures/se_consumption/` — static mini house profiles + `tests/test_se_consumption_invariants.py` (profile_spec window ≈ hourly Historisch-style load; `thermal_pulse_tight` also covers MILP feasibility for 1 kW Haus+EV overnight)
