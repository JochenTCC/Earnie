# Cloud POC study — status and next steps

Status: **in progress** (POC verified 2026-10-23; multi-scenario study not started).
Code: `studies/poc_cloud/` (branch `study/poc-cloud`, commit `1c2baaa`).
Cloud run results: branch `study/cloud-results` (`studies/poc_cloud/results/cloud/`).

## Goal

Prove that a backtest/scenario study can run **offline in a cloud sandbox from frozen
inputs**, as the prerequisite for an automated multi-scenario study. The POC is
deliberately minimal: one synthetic house, one scenario, one year.

## What the POC does today

Entry point (from the repo root, as a module):

```bash
PYTHONUTF8=1 python -m studies.poc_cloud.run_poc --out studies/poc_cloud/results/cloud
```

| Aspect | State |
| --- | --- |
| House | Synthetic, from public example data (`example_efh`, `awattar_at`, 5 kWh battery, 10 kWp PV, consumers heat pump / EV / washer / dryer / dishwasher); `annual_kwh` raised to 20040 so the consumers fit |
| Scenarios | `live` plus the two automatic references `historical_reference` and `ref:live` |
| Period | 2025-01-01 … 2025-12-31, 365 daily windows, `horizon_mode=sunrise_window`, `price_strategy=perfect` |
| Prices | Frozen day-ahead CSV, zone AT (`cache/prices_AT_2025.csv` + manifest). The column is `Day Ahead Auktion (AT)` (named after the zone) |
| Weather | Frozen Open-Meteo archive bundles (`cache/open_meteo/`), copied to `data/cache/open_meteo` by the runner |
| Consumption | Synthetic `cons_data.csv` (`scripts.generate_cons_data --source synthetic`, 8760 rows) |
| Network | Blocked via dead proxy (`127.0.0.1:9`) + `EARNIE_OFFLINE=1`; a cache miss fails loudly (ProxyError) instead of fetching live data |
| Parallelism | 3 workers (historical, reference, live) |
| Output | `summary.json` (totals, monthly EUR, CBC event summary, plausibility), `backtesting.csv`, CBC event log, window snapshots, annual invoices |
| UI | None (no Streamlit) |

### Verification so far (2026-10-23)

| Run | Machine | Python | Wall time | historical_reference | ref:live | live | `strict_slow` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Local, online | Windows, 24 cores | 3.14.3 | ~575–596 s | 3023.1622 | 1787.2117 | 1411.9958 | 77 |
| Local, offline clean clone | Windows, 24 cores | 3.14.3 | ~575–596 s | 3023.1622 | 1787.2117 | 1412.0008 | 78 |
| **Cloud, offline** | Ubuntu 24.04, 4 vCPU, 15 GiB | 3.13.16 | 578 s | 3023.1622 | 1787.2117 | 1412.0149 | 82 |

Findings:

- Both reference totals are identical; `live` differs by +0.019 EUR (0.0014 %) from the online
  run and +0.014 EUR from the offline run. This is within solver-timing noise
  (`cbc_strict_time_limit_sec = 3` is wall-clock, so a slower machine hits more
  `strict_slow` events and may pick slightly different plans).
- The PuLP CBC binary bundled in the wheel (`pulp/solverdir/cbc/linux/i64/cbc`) works on Linux
  without extra setup. `tzdata` (needed for `Europe/Vienna`) is installed through
  `requirements.txt`. No line-ending or permission problems.
- Setup needs network (`pip install`); the study run itself does not.

### Known limits (not a study result)

- Synthetic house and consumption: EUR values say nothing about a real house.
- One scenario, one year, one price zone: no scenario comparison yet. The `ref:live` vs. `live`
  gap (~375 EUR) is only the optimisation effect for this one setup.
- Results depend slightly on machine speed (see above).
- The run writes an untracked `pack/runtime/usage_ping.json` (`consent: unset`) as a side effect.
- `EHAL push: no value for 'sens_absent_mode'` warnings flood the log (offline, no live sensor).
- Weather cache keys are exact date ranges; the current calendar year is capped at "yesterday",
  so the runner aliases the frozen file to today's name (only January 2026 is used).

## Next steps

Ordered by priority.

1. **Close the verification gaps**
   - Compare monthly values: the local `monthly_eur` of the reference runs is not stored in
     the repo; add the local reference `summary.json` (or its monthly block) to the study
     folder and compute the max absolute monthly difference vs. the cloud run.
   - Triage the 5 `consumption_tolerance` windows (diff 3.5 kWh each): 2025-01-04, 01-11,
     01-18, 12-20, 12-27, all Saturdays at 09:00. Check whether they also appear in the local
     run and which flexible consumer shifts 3.5 kWh; decide bug / intended / test data
     (like `.cursor/skills/regression-triage/`).
2. **Make the result reproducible and comparable**
   - Decide how to handle the wall-clock CBC limit in the cloud: pin machine class, or raise /
     deterministically configure `cbc_strict_time_limit_sec`, and define an acceptance
     tolerance (e.g. relative deviation of totals) instead of exact equality.
   - Persist machine info (nproc, RAM, Python, OS) in `summary.json` / run metadata.
   - Suppress or fix the side-effect file (`usage_ping.json`) and the `sens_absent_mode` log noise
     for study runs (no silent workaround — decide with the maintainer).
3. **Automate the cloud run**
   - Setup script / environment image with the venv, so the run is one command; run on a
     machine with more cores to check scaling beyond 3 workers.
   - Define where results are stored (separate results branch vs. artifact) so the working
     tree stays clean and the stop hook does not flag untracked files.
4. **Build the multi-scenario study**
   - Several scenarios (battery sizes, tariffs, PV configurations) in
     `backtesting_scenarios.json`, one reference per scenario.
   - Aggregated comparison output (table per scenario, delta vs. reference).
   - Optional: second price zone / year, replace synthetic consumption with real or
     HouseSim data.
5. **Documentation**: once stable, move the study procedure to `docs/workflow/` and note
   the frozen-input refresh procedure (`fetch_prices.py`, weather cache rebuild with
   `--allow-network`).
