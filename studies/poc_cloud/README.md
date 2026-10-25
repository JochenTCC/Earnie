# Cloud POC study

One synthetic house, one scenario (`live`), calendar year 2025, fully offline and
without the Streamlit UI. Purpose: prove that a backtest/scenario study can run in a
cloud sandbox from frozen inputs, before building the automated multi-scenario study.

## Layout

| Path | Role |
| --- | --- |
| `pack/config/` | House pack: public example data (`example_efh`, `awattar_at`, 5 kWh battery, 10 kWp PV), migrated to the current data model |
| `pack/runtime/cons_data.csv` | Synthetic hourly consumption for 2025 (`scripts.generate_cons_data --source synthetic`) |
| `cache/prices_AT_2025.csv` | Frozen day-ahead prices, zone AT (see `.manifest.json`) |
| `cache/open_meteo/` | Frozen Open-Meteo archive bundles (copied into `data/cache/open_meteo_utc` by the runner) |
| `fetch_prices.py` | One-off online step that writes the price CSV |
| `run_poc.py` | Offline runner: installs the weather cache, runs the backtest, writes `summary.json` |

## Run

```powershell
$env:PYTHONUTF8='1'
.venv\Scripts\python.exe -m studies.poc_cloud.run_poc --out studies/poc_cloud/results/run
```

The runner points HTTP(S) at a dead proxy, so a cache miss fails loudly instead of
fetching live data. `--allow-network` disables that guard (cache building only).

## Known constraints

- **Price CSV column name:** the CSV loader reads the column of the scenario's market zone
  (`Day Ahead Auktion (AT)` for zone AT) and fails loud when it is missing.
- **Weather cache keys:** Open-Meteo bundles are keyed by exact date range. The current
  calendar year is capped at the last archive day, so its file name would change daily; the
  runner pins that day with `EARNIE_OPEN_METEO_AS_OF=2026-10-22` (the end date of the frozen
  2026 file). Re-harvesting needs a new pin.
- **Solver timing:** `cbc_strict_time_limit_sec` is wall-clock. A slower machine can
  hit more `strict_slow` events and produce slightly different plans.
- **Synthetic house:** `annual_kwh` was raised to 20040 because the example's consumers
  (heat pump, EV, appliances) exceed the example's 4500 kWh/a.
