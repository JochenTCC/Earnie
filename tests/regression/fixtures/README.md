# Shared regression fixtures

Recorder roots referenced by L1 `case.yaml` (`recorder.root`).

| Path | Role |
|---|---|
| `seed_recorder/` | R0 historical seed cycles (Nov / Jan / Feb windows) rewritten into recorder format |
| `negative_prices_recorder/` | Synthetic cycle with forced negative `k_act` slots |
| `heating_rod_fuel_recorder/` | Synthetic Live cycle for `REG-S-heating-rod-fuel`: the seed cycle of 2026-02-28 12:00 (window from 2026-02-27 12:00) with the example house of the HA Lab rod pack (data model 6: gas boiler, 500 l store, 3 kW rod; EV and pool dropped, lat/lon 47.5 / 9.5). Made Live: row 0 `live_snapshot`, the rest `forecast`, timestamp = window start. Recorded inputs added by hand: store T_eq 45 °C as a push read, `thermal_readings`, outdoor forecast from the Open-Meteo archive (47.5 / 9.5, from 2026-02-27 12:00) |
| `open_meteo/` | Frozen Open-Meteo climate the L1 replays read (thermal flex context, lat/lon 47.5 / 9.5); re-record see `tests/regression/climate_fixture.py` |

**Privacy scrub (P1):** house label anonymized, lat/lon rounded to 0.5°, `cons_data.csv` replaced by a stub (L1 replay uses the frozen matrix, not the load CSV). Prefer live `runtime/recorder/` cycles when available; re-scrub before committing.
