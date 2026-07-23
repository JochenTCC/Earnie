# SE calculation test plan (Version 2.3)

Executable matrix for Scenario Explorer (SE) consumption: Live house profile, CSV / Basislast axes, seasonal months, actual vs non-optimized reference kWh.

Related: [scenario-explorer-consumption.md](scenario-explorer-consumption.md), [betriebsmodi.md](../ui/betriebsmodi.md), [verbrauchs-csv.md](../konfiguration/verbrauchs-csv.md).

## Baseline

| Item | Value |
| ---- | ----- |
| Env | `earnie_env` (`EARNIE_ENV_PATH`) |
| Live scenario | `live` |
| House profile | `example_efh` |
| Controllables without CSV | `waschmaschine`, `trockner`, `geschirrspueler` (`manual`) |
| SE Basislast path | **A** (B-gate false — manuals lack active CSV) |
| Seasonal months | **2025**-01, 04, 07, 10 |
| Scenario scope | **Live only** (other scenarios stripped in cell overlay) |

Inventory and B-gate:

```text
python -m scripts.se_calc_test_matrix --inventory
```

## Metrics compared

| Label | Source |
| ----- | ------ |
| **Actual total** | Period sum of `cons_data` `total_kw` (`reference_kwh_for_period`) |
| **Non-optimized Live-ref** | Plausibility `consumption_totals.historical_kwh` for `live` (`profile_spec`) |
| **Optimized Live** | Plausibility `consumption_totals.optimized_kwh` |

Primary focus: actual vs Live-ref (meter may differ from model — document Δ%). Secondary: optimized ≈ Live-ref (timing-shift allowed).

Optional QC when `total_profile_csv` is set: monthly sum of house Gesamtverbrauch CSV vs `cons_data` (not SE row identity).

## Matrix (path A)

Overlays are **temporary** files under `earnie_env/runtime/se_calc_test/cells/` (never permanent edits to live `house_profiles.json`).

| Cell | `total_profile_csv` | Consumer `use_profile_csv` | Expected Basislast | Intent |
| ---- | ------------------- | -------------------------- | ------------------ | ------ |
| M0 | as Live (present) | all off | **A** | Baseline |
| M1 | cleared | all off | **A** | No meter residual possible |
| M2 | present | thermal+EV with files on (`wp_heating`, `ev`, `swimspa`) | **A** | CSV overlays under A; manuals still block B |
| M3 | present | known+CSV only if files exist; else **skip** | **A** | Known CSV under A |
| M4 | present | same as M2 (thermal/EV on; manuals off) | **A** | Alias of realistic partial CSV (same as M2 on this env) |

### Path B — not executable on this env

Path **B** (meter residual Basislast) requires `total_profile_csv` **and** every controllable generic (`flex` + `manual`) to have active `use_profile_csv`. Live manuals have no CSV — do **not** invent series for this plan. Unlock later by importing CSVs for all manuals, then add a B cell.

## Pass / fail

| Check | Pass when |
| ----- | --------- |
| B-gate on M0–M4 | Always `False` |
| Actual vs Live-ref | Record Δ%; **warn** if \|Δ\| > 5% (not auto-fail) |
| Optimized vs Live-ref | Pass if \|Δ\| ≤ 5% or timing-shift / plausibility story holds |
| Hard fail | Crash, missing artifacts, B-gate unexpectedly `True`, unexplained ≫5% optimized vs Live-ref |

## How to run

```text
# 1) Materialize cell overlays + descriptors
python -m scripts.se_calc_test_matrix --cells M0,M1,M2

# 2) SE runs (Live only, year 2025 months; workers default = max useful)
python -m scripts.se_calc_test_run --cells M0,M1,M2 --months 1,4,7,10 --year 2025

# 3) Compare + write results
python -m scripts.se_calc_test_compare
```

Artifacts:

| Path | Content |
| ---- | ------- |
| `earnie_env/runtime/se_calc_test/cells/<cell>/` | Patched `house_profiles.json`, Live-only `backtesting_scenarios.json` |
| `earnie_env/runtime/se_calc_test/runs/<cell>/<YYYY>-<MM>/` | `backtesting_log.json` (+ hourly CSV) |
| `docs/spec/se-calc-test-results.json` | Machine-readable comparison |
| Results appendix below | Filled after compare |

CLI note: stock `scripts/run_backtesting.py` maps `--start-month` to the cons_data **max year**. The SE calc runner forces `--year` (2025) via a patched `backtesting_base_year` so Oct/Jan land in 2025, not 2026.

## Results appendix

Filled by `scripts/se_calc_test_compare.py`.

**Notes from this run:** Re-run after Live `export_tariff_id` fix (`monthly_sunny` → `at_tiwag_tiwag_einspeisung_fix`); SE runner uses max useful workers (`3` for Live-only). M0 ≡ M1 for Live-ref/optimized (path **A** ignores `total_profile_csv` for Basislast). M2 shifts Live-ref when thermal/EV CSV overlays are on. Summary: 1 warn, 0 hard_fail (warn = actual vs Live-ref >5%, not auto-fail). kWh table unchanged vs prior run (tariff mainly affects €).

| Cell | Month | Actual kWh | Live-ref kWh | Optimized kWh | Δ act/ref | Δ opt/ref | Status | Notes |
| ---- | ----- | ---------- | ------------ | ------------- | --------- | --------- | ------ | ----- |
| M0 | 01/2025 | 1269.7 | 1257.8 | 1239.9 | +0.9% | -1.4% | pass | — |
| M0 | 04/2025 | 941.2 | 953.8 | 938.9 | -1.3% | -1.6% | pass | — |
| M0 | 07/2025 | 812.5 | 825.3 | 812.2 | -1.6% | -1.6% | pass | — |
| M0 | 10/2025 | 1051.6 | 1061.5 | 1043.2 | -0.9% | -1.7% | pass | — |
| M1 | 01/2025 | 1269.7 | 1257.8 | 1239.9 | +0.9% | -1.4% | pass | — |
| M1 | 04/2025 | 941.2 | 953.8 | 938.9 | -1.3% | -1.6% | pass | — |
| M1 | 07/2025 | 812.5 | 825.3 | 812.2 | -1.6% | -1.6% | pass | — |
| M1 | 10/2025 | 1051.6 | 1061.5 | 1043.2 | -0.9% | -1.7% | pass | — |
| M2 | 01/2025 | 1269.7 | 1337.8 | 1335.6 | -5.1% | -0.2% | warn | warn actual vs Live-ref |Δ|=5.1% > 5% |
| M2 | 04/2025 | 941.2 | 960.6 | 951.1 | -2.0% | -1.0% | pass | — |
| M2 | 07/2025 | 812.5 | 782.4 | 778.2 | +3.9% | -0.5% | pass | — |
| M2 | 10/2025 | 1051.6 | 1064.6 | 1056.9 | -1.2% | -0.7% | pass | — |

Machine-readable: [se-calc-test-results.json](se-calc-test-results.json).
