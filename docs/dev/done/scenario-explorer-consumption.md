# Szenario-Explorer — consumption model (Version 2.0)

Developer reference for SE / greenfield backtesting load paths.

## Two load paths

| Path | Source | Used for |
| ---- | ------ | -------- |
| **Baseline** | House profile default schedules and/or `cons_data.csv` | Reference €, SE “Referenz-Verbrauch”, UI dashed lines |
| **Optimized** | MILP output from `simulate_horizon` | Plausibility, SE solid lines, `backtesting.csv` consumption columns |

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
| `generic` | `earnie_role: known` | — (fixed overlay; CSV shape when `use_profile_csv`) | — |
| `generic` | `earnie_role: manual` | `planning_consumer_to_milp` | `generic_flex_window` (SE); Live = user day-plan only |
| `ev` | `charging_schedule` present | `planning_ev_to_milp` | `charging_schedule` + deadline |
| `thermal_annual` | — | MILP when not CSV; CSV → fixed overlay | `thermal_annual` targets or overlay |
| `thermal_rc` | no `use_profile_csv` | `planning_thermal_rc_to_milp` | RC thermal control; `profile_spec` window target via modeled/climate kWh (`planning_thermal_rc_daily_targets`) |
| `thermal_rc` | `use_profile_csv` | — (CSV fixed overlay, not MILP) | — |

`split_planning_generic_consumers` puts **known** into the fixed baseload overlay and **flex + manual** into MILP. Live does not overlay the default manual weekly schedule — only active user plans from **Betrieb → Manuelle Geräte**.

### SE Basislast path A vs B

| Condition | Basislast |
| --------- | --------- |
| `total_profile_csv` present **and** every controllable generic (`flex` + `manual`) has active `use_profile_csv` | **B:** hourly residual `total − Σ(accounted CSV series)`, clip ≥ 0; known CSV re-added as fixed overlay |
| otherwise, `baseload_distribution=monthly` and Gesamt-CSV resolvable | **A monthly:** per-calendar-month residual `max(0, Ist_m − Σ model consumers_m) / hours_m` + role overlays |
| otherwise | **A flat:** `baseload_kwh / 8760` + role overlays |

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
| `use_profile_csv` | `true` → use CSV load instead of synthetic schedule/model **and** subtract that series when residual/Basislast helpers run (HK + SE path B); role-specific SE/Live usage as in the Hauskonfigurator table |

Scenario Explorer overlays and synthetic `cons_data` generation use path **A** (flat `baseload_kwh / 8760`) unless the path-B gate is met. Meter residual from `total_profile_csv` is used only for path B and HK Ist helpers.

When synthesizing `cons_data`, `total_kw` = metric baseload + Σ(consumers).

## Related modules

- `house_config/planning_flex_bridge.py` — bridges, targets, consumption source
- `simulation/engine.py` — `resolved_flexible_consumers`, `flex_consumers_from_snapshot`, plausibility
- `ui/chart_consumer_stack.py` — Chart 1 stack order and flex discovery
- `ui/backtesting_display_bundle.py` — passes resolved flex into backtesting Chart 1
- `ui/backtesting_scenario_consumption.py` — baseline vs optimized charts
- `tests/fixtures/se_consumption/` — static mini house profiles + `tests/test_se_consumption_invariants.py` (profile_spec window ≈ hourly Historisch-style load; `thermal_pulse_tight` also covers MILP feasibility for 1 kW Haus+EV overnight)
