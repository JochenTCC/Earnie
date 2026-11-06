# SE forecast mode — plan on forecasts, book on actuals

**Status:** implemented 2026-11-05 (`simulation/forecast_mode.py`, `booking_matrix` in `optimizer/simulation.py::simulate_horizon`). Follows RuleRef decision O1 ([`rule-based-reference.md`](rule-based-reference.md) § 7).

## 1. Goal

The SE plans with perfect foresight of PV, load and prices, so L2 − L3 is an upper bound. The forecast mode gives the other end: each window plans once from what was known then, and the result is booked on actuals. A study then reports a range for L3:

- **Upper bound:** today's run, perfect foresight.
- **Lower bound:** forecast mode, one plan per day without re-plan. Live re-plans every cycle, so live should land between the two.

The ladder steps L0–L2 do not change. They already book actuals and see only published prices.

## 2. Why `--price-strategy` does not do this

`--price-strategy mirror|forecast` books at the planned price, because the planned matrix is also the booked one. It plans at SA₀, past almost all of the book, and PV and load stay perfect. The mode stays as it is for now; the forecast mode does not build on its booking.

## 3. Method

### 3.1 Two matrices per window

The window keeps today's matrix unchanged. It is the **booking matrix**: actual prices, PV and load, also the source of targets, windows and plausibility. A copy with forecast inputs is the **plan matrix**, and only the MILP sees it.

`simulate_horizon` solves on the plan matrix and applies each schedule slot to the matching booking row. Everything a slot books comes from that row: `k_act`, `k_push_act`, PV, load.

With forecast = actual both matrices are equal and the code path is the existing one, so that run must reproduce the perfect-foresight run exactly. This is the main test.

### 3.2 Plan inputs

Each input can be switched separately (`--plan-forecast price,pv,load`), which also shows how much each one costs. No input selected is the reproduction test above.

| Input | Plan matrix | Source |
|---|---|---|
| Prices | Day-ahead state at **SA₁**, the book's start. Unpublished slots use `--price-strategy mirror` or `forecast` | `matrix_prices_from_context(..., planning_moment=sa1)`, feed-in re-enriched on the planned prices |
| PV | See § 3.3 | Open-Meteo Previous Runs |
| Load | Baseload from the profile (below); fixed load and role overlays stay | `simulation/forecast_mode.py` |
| Flex targets | **Actual**, not forecast | Same as today: energy parity per window, and the thermal need is known from the climate data |

The plan's first part SA₀→SA₁ carries no flex and the SoC is held at SA₁, so it does not affect the book. SA₁ is therefore a consistent planning moment. On a normal day the plan knows the prices up to midnight and has to estimate midnight→SA₂.

**Load per consumption source:**

- `logged_day`: month / weekday / hour mean of `BaseLoad` from `cons_data`, the same key as live's profile. The target day is left out of its own mean: with one year of data it would be about 25 % of the value.
- `profile_spec` with a meter CSV (path B): `monthly_residual_baseload_kw` instead of `meter_residual_baseload_kw`.
- `profile_spec` otherwise (flat or monthly baseload): forecast = actual. **These houses have no load deviation**, and that includes the viability study's generated houses, so their range only reflects PV and prices.

### 3.3 PV forecast source

Open-Meteo's Previous Runs API serves `global_tilted_irradiance_previous_day1`, the value forecast 24 h earlier, on the same surfaces as the archive. It starts 2024-01-19 (checked 2026-11-05). A planning period before that fails loud.

The booked PV is the archive (ERA5), a different model. Checked for Vienna, 30° south, 2025, against the archive:

| Variant | Annual bias | Daily MAE | Daily correlation | Hourly MAE |
|---|---|---|---|---|
| Lead 0 (best forecast at that hour) | −10.3 % | 14 % | 0.959 | 20 % |
| Raw day 1 | −9.0 % | 15.7 % | 0.945 | 21 % |
| **Day 1, scaled to the month's total** | 0.0 % | 14.8 % | 0.944 | 21 % |
| Archive + (day 1 − lead 0) | +1.4 % | 9.9 % | 0.967 | 16 % |

The difference between lead 0 and day 1 is small, so most of the raw deviation is ERA5 against the forecast model, not lead time. A raw forecast would plan about 10 % too little PV all year, which a live system would notice and which is not what the mode should measure.

**Decision (maintainer, 2026-11-05): day 1 scaled per calendar month** so its monthly total equals the booked PV's (`factor = Σ actual / Σ forecast`, per scenario, also for imported PV CSVs). It removes the bias and keeps the weather error, including the part that is ERA5 against model, so it leans pessimistic, which suits a lower bound. The factor knows the month's total in hindsight; a live system's bias correction is comparable only over longer periods. Monthly factors for the check above range from 1.00 to 1.33.

An error model was the alternative. It needs calibration from the same data and loses the link between errors and weather.

### 3.4 Replay on deviations

- **Battery:** the live controller, `derive_control_from_milp_plan` through `_chart_row_from_schedule_slot`, on the actual row and the actual SoC. Forced charging aims at the planned SoC, a discharge lock holds, and Automatik follows the actual surplus. No new battery logic.
- **Flex:** runs at the planned power, open loop. It does not follow actual surplus, which is part of why this is a lower bound. PV-follow consumers book the planned power too.
- **Export cap:** on the actual feed-in price, as today.
- **SoC chain:** `_sunrise_book_end_soc` reads the replayed rows, so the next window plans from the real SoC.

Preparation of the matrix (immediate charging, appliance plans, standby relief) adds load to the plan matrix. The booking row takes the same addition per slot.

### 3.5 Limits

- No re-plan, by design. A plan after the day-ahead publication at 13:00 would narrow the range; not part of this item.
- Thermal need and fixed thermal overlays are perfect, so a cold-snap error is missing.
- A critical-window snapshot still holds the booking matrix, so `backtesting_single_window` replays such a window with foresight.
- The forecast is 24 h ahead although much of the book is closer than that, one more reason for "lower bound".
- **Prices before the period:** a mirror or forecast plan needs about 8 days of prices before the period's start, and a missing one fails loud. A price file that starts on the period's first day therefore cannot run January. The study's `prices_AT_2025.csv` is such a file; fetch it with an earlier start (`python -m studies.poc_cloud.fetch_prices --start 2024-12-20 --end 2026-01-04`).
- **Current month:** a month's scaling factor covers the hours with an archived run, and the booked PV of those hours must exist in the archive. Use complete past months.
- **Runtime:** a second full SE run, so the export takes about twice as long.

## 4. Output

`python -m scripts.run_backtesting --plan-forecast price,pv,load --price-strategy mirror|forecast`. Sunrise mode only; the price strategy is mandatory with `price`. The log records `plan_forecast` and `price_strategy`, and the fingerprint includes both. The UI keeps running perfect foresight.

`python -m scripts.run_reference_ladder` runs the perfect run, then the forecast run into `<output-dir>/forecast_mode/`, and adds to the study export:

- `reference_ladder_summary.csv`: `l3_forecast_eur`, `saving_l2_l3_forecast_eur`, `rule_share_forecast`, `l2_soc_correction_forecast_eur`, `soc_end_percent_l3_forecast`, `plausibility_failed_windows_l3_forecast`, `plan_forecast`, `price_strategy`.
- `reference_ladder_daily.csv`: `l3_forecast_eur`.

`l3_eur` stays the perfect run and `l3_foresight` keeps saying so. The end-SoC term of the forecast columns comes from the forecast run. A run whose L0, L1 or L2 totals differ between the two logs fails loud, because they must not depend on the plan. `--skip-forecast` leaves the second run out. The new price argument is `--forecast-price-strategy`, mandatory unless skipped. It has no default because the training data for `forecast` does not cover every year (`data/cache/price_training_*.csv`).

Study runner: `python -m studies.viability.run_houses ... --forecast-price-strategy mirror`; without the argument it passes `--skip-forecast`. The first run needs `--allow-network` for the archived forecasts, which are cached in `data/cache/energy_charts`.

## 5. Sample result

Viability house S2 (`packs_s2_g2`), 2025, all three inputs, prices `mirror`. The house has a flat baseload, so the load input changes nothing here. One house and two months, so this only shows the mode works, not a study figure:

| Month | Tariff | L2 | L3 perfect | L3 forecast | L2 − L3 perfect | L2 − L3 forecast |
|---|---|---|---|---|---|---|
| February | Duo | 118.87 € | 117.28 € | 117.98 € | +0.93 € | +0.22 € |
| February | Dynamic | 140.68 € | 126.57 € | 130.20 € | +13.43 € | +9.81 € |
| June | Duo | −147.86 € | −143.61 € | −143.13 € | −2.80 € | −3.28 € |
| June | Dynamic | −54.43 € | −138.12 € | −135.36 € | +80.05 € | +77.27 € |

In both months and on both tariffs, consumption and booked prices match between the runs, no window fails plausibility, and L0–L2 agree within the tolerance.

## 6. Tests

- `--plan-forecast` empty reproduces the perfect-foresight run: costs, SoC chain, flex per slot. The test reuses the first run's schedules and checks that the MILP saw the same matrix, because CBC can pick another of several equal optima under parallel load.
- Energy parity per window with deviating PV and load (plausibility holds, flex total equals the target).
- Booked price equals the actual price per slot while the plan sees another one.
- Plan matrix: prices follow the cutoff at SA₁; PV and load of the plan differ, the booking row's do not.
- PV: monthly total equals the booked one; a gap fails loud; zero kWp stays zero.
- Load: the target day is left out of its mean; flat `profile_spec` has no deviation.
- Export: range columns, failure when L0–L2 differ between the logs.
