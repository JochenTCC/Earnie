# Scenario Exploration — consumption model (Version 2.0)

Developer reference for SE / greenfield backtesting load paths.

## Two load paths

| Path | Source | Used for |
| ---- | ------ | -------- |
| **Baseline** | House profile default schedules and/or `cons_data_hourly.csv` | Reference €, SE “Referenz-Verbrauch”, UI dashed lines |
| **Optimized** | MILP output from `simulate_horizon` | Plausibility, SE solid lines, `backtesting_hourly.csv` consumption columns |

`consumption_source` on resolved scenario settings:

- `profile_spec` (default when `house_profile_id` is set) — optimization uses profile spec, not cons_data replay
- `logged_day` — prod replay from cons_data window sums

## MILP-flex registration from house profiles

Profile consumers are merged into `flexible_consumers` via `_planning_flex_consumers` in `house_config/scenario_resolution.py` (`collect_planning_flex_consumers`).

| Profile `type` | MILP-flex when | Bridge function | MILP mechanism |
| -------------- | -------------- | --------------- | -------------- |
| `generic` | `schedule.start_shift_h > 0` | `planning_consumer_to_milp` | `generic_flex_window` |
| `generic` | `schedule.start_shift_h == 0` | — (fixed overlay only) | — |
| `ev` | `charging_schedule` present | `planning_ev_to_milp` | `charging_schedule` + deadline |
| `thermal_annual` | — | — | Fixed overlay (`house_profile_baseload_overlay`) |

Greenfield `config.json` keeps `flexible_consumers: []`; shiftable loads come from the house profile.

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

## Related modules

- `house_config/planning_flex_bridge.py` — bridges, targets, consumption source
- `simulation/engine.py` — `build_historical_matrix_for_slots`, plausibility
- `ui/backtesting_scenario_consumption.py` — baseline vs optimized charts
