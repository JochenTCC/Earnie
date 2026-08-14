# Configuration — Overview

The central file is `earnie_env/config/config.json`. [`share/config/config.example.json`](../../share/config/config.example.json) serves as the starting point (bootstrap copies missing files). See also [Save / Load](speichern-laden.md) and [Private House Config](../einrichtung/private-env.md).

## Schema and Editor Help

At the top of `config.json`:

```json
"$schema": "./config.schema.json"
```

In Cursor/VS Code, **hover descriptions** from [`share/config/config.schema.json`](../../share/config/config.schema.json) appear for many fields. More detailed context is in the following chapters of this documentation.

## Main Blocks


| Block                                           | Purpose                                                                                                                         |
| -------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `system`                                          | Timeouts for HTTP and the optimization loop                                                                                   |
| `market_prices`                                   | Strategy for missing future prices (`forecast` / `mirror`) — see [Prices](preise.md)                                          |
| `ui`                                               | Streamlit port, refresh intervals, optional dev pages                                                                          |
| `loxone_blocks`                                   | Optionally empty; mapping now only via `plant.ehal_bindings` / consumer `ehal_bindings` (EHAL-Com)                            |
| `live_scenario_id`                                | ID of the **live scenario** in `backtesting_scenarios.json` (default: `live`)                                                 |
| `earnie_env/config/components.json`               | Technical parameters for storage and PV (`batteries[]`, `pv_systems[]`; referenced via IDs)                                    |
| `earnie_env/config/tariffs.json`                  | Runtime tariff catalog (import/feed-in); seeded from the public [`share/config/tariffs.json`](../../share/config/tariffs.json) |
| `earnie_env/config/house_profiles.json`           | Location (geo/timezone), grid usage energy price, planning consumers (EV, heat pump, washing machine, …); referenced via `house_profile_id` |
| `earnie_env/config/backtesting_scenarios.json`    | **All** scenarios (live + variants); uniform `settings` format                                                                |
| `scenario_explorer_conf`                          | Scenario Explorer / backtesting: `cons_data.csv`, price source; time range derived from `cons_data` months                    |
| `flexible_consumers`                              | Legacy overlay (usually empty); live consumers are in `house_profiles.json`                                                    |
| `appliance_recommendation`                        | Global star ratings/thresholds for manual devices (no device definitions)                                                      |
| `planning_horizon`                                | MILP horizon (`sunrise_window` for live)                                                                                        |


Template for scenarios: [`backtesting_scenarios.example.json`](../../share/config/backtesting_scenarios.example.json).

## Scenarios (Live and Scenario Explorer)

- `live_scenario_id` in `config.json` selects the live scenario (default ID: `live`).
- `backtesting_scenarios.json` contains **all** scenarios in the same format (`id`, `label`, `settings` with entity references or — for what-if — flat parameters).
- **Live operation** (`main.py`, **Sunset-2-Sunset** mode) and **Scenario Explorer** resolve the same live scenario via `[house_config/scenario_resolution.py](../../house_config/scenario_resolution.py)`.
- Additional scenarios in the same file are only used for comparison in Scenario Explorer; they do not change production operation.



## `scenario_explorer_conf`


| Field                          | Meaning                                                                       |
| ------------------------------- | -------------------------------------------------------------------------------- |
| `path_cons_data`               | Hourly consumption/PV baseline (maintained by `main.py`); SE overall time range   |
| `path_price`                   | Optional: historical exchange prices (Energy-Charts CSV)                          |
| `cons_data_retention_months`   | How long hourly values are retained                                              |
| `cons_data_write_mode`         | Write mode (`hourly`)                                                             |
| `price_source`                 | `api` = live prices; other values for historical prices from CSV                  |
| `price_provider`               | e.g. `awattar`                                                                     |
| `price_range`                  | `last_12_months`: 12 calendar months up to the last **complete** month in `cons_data` (defined backwards; days chronological) |
| `energy_charts_bzn`            | Bidding zone for the Energy-Charts CSV (e.g. `DE-LU`)                             |

**Three CSV levels (don't mix them up):**

1. **`path_cons_data`** — runtime fuel for live and Scenario Explorer
2. **House-profile CSVs** (`total_profile_csv` / `pv_profile_csv` / `profile_csv`) — planning / actual-vs-model (see [Historical Power Profile CSV](verbrauchs-csv.md))
3. **`path_consumption` / `path_production`** — removed (data model v3); formerly raw Loxone-pair CSVs, only for time-range bounds

Details on prices: [Prices & aWATTar](preise.md).


## Scenario Configurator (Live Scenario)

In the **Configuration** section, the **Scenario Configurator** maintains the live scenario and additional variants. Scenarios are chosen from a **list**; ↑/↓ next to it change the **order** of the non-live scenarios (live stays on top) for the display in Scenario Explorer. Entities (house profile, battery, PV, tariffs) are chosen via dropdown (`battery_id`, PV, tariffs, house profile). Per scenario, **active for Scenario Explorer** (`enabled`, default true) controls whether the variant is included in the SE calculation. **Own reference without optimization** (`own_reference`) controls whether a separate non-optimized reference is calculated for the scenario; if not set, Earnie's heuristic applies (own reference for a differing tariff/`pv_kwp`, battery variants share the live reference). Before the tariff dropdowns there is a shared **country** filter (`land`: AT/DE/CH, **always set**, no "all"; preset from the house profile's location) for import and feed-in, plus separate **type** filters. For the feed-in **type**, `monthly_table` appears as **monthly price**. A region filter is not yet available. After choosing a tariff, the catalog parameters appear read-only (including `supplier_id` and the approximate monthly fee). IDs are saved in the respective scenario in `backtesting_scenarios.json`. The live scenario's **name** (`live_scenario_id` in `config.json`, default ID: `live`) is fixed and cannot be renamed or removed.

## Further Reading

- [Save / Load](speichern-laden.md)
- [PV & Battery](batterie-pv.md)
- [Flexible Consumers](flexible-verbraucher.md)
- [Historical Power Profile CSV](verbrauchs-csv.md)
- [Prices & aWATTar](preise.md)
- [Loxone Signals](../referenz/loxone-signals.md)
