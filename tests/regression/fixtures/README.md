# Shared regression fixtures

Recorder roots referenced by L1 `case.yaml` (`recorder.root`).

| Path | Role |
|---|---|
| `seed_recorder/` | R0 historical seed cycles (Nov / Jan / Feb windows) rewritten into recorder format |
| `negative_prices_recorder/` | Synthetic cycle with forced negative `k_act` slots |
| `open_meteo/` | Frozen Open-Meteo climate the L1 replays read (thermal flex context, lat/lon 47.5 / 9.5); re-record see `tests/regression/climate_fixture.py` |

**Privacy scrub (P1):** house label anonymized, lat/lon rounded to 0.5°, `cons_data.csv` replaced by a stub (L1 replay uses the frozen matrix, not the load CSV). Prefer live `runtime/recorder/` cycles when available; re-scrub before committing.
