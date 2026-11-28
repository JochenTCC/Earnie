# Price forecast: seam to the Day-Ahead prices

Status: implemented 2026-11-28 (`data/market_prices._resolve_live_bias`,
`data/price_forecast_live.compute_seam_anchor_cent`, `data/ols_forecaster.SeamAnchor`).
User-facing description: `docs/konfiguration/preise.md` § Fehlende Zukunftspreise.

## Problem

Slots without a Day-Ahead price get the OLS forecast plus a live bias (mean Day-Ahead − OLS
residual, capped at ±12 ct). Until 2026-11-28 the bias window was the 48 h before the planning
start, and the bias was the same for every predicted slot. The residual depends strongly on the
hour, though: in autumn 2026 the model is far too low in the expensive day hours and much less
so late in the evening. The first predicted slot (00:00 before the publication around 13:00) then
sat at the 48 h level, a visible jump after the last known price (production install
2026-11-28: 31.05 → 38.17 ct/kWh gross, bias +11.1 ct).

## Correction

- **Window:** the bias is the mean residual of the `live_bias_lookback_hours` (48) hours before
  the **first predicted slot**, so the known prices of the horizon itself count.
- **Seam anchor:** the mean residual of the last `live_bias_seam_hours` (2) known hours before
  the first predicted slot, capped like the bias.
- **Decay:** offset(t) = bias + (anchor − bias) · max(0, 1 − h / `live_bias_seam_decay_hours`),
  h = whole clock hours since the clock hour of the first predicted slot (hourly steps: all
  quarter-hours of an hour share one offset, like the hourly OLS value; a per-quarter-hour ramp
  drew sloping lines in the chart); default 8 h, 0 = no seam. The backtest is hourly and does not
  change with the steps.
- An hour's actual price is the mean of its known quarter-hours (before: the price of its
  :00 quarter).
- A seam hour without a price or a feature row → no anchor, the bias alone (log warning).
- Live features: hours before the planning start are fetched as before
  (`build_live_feature_frame_for_slots`), hours from the planning start on come from the
  horizon's `forecast_feature_frame`. SE passes its training CSV for both.

## Backtest

`python -m scripts.evaluate_price_forecast_seam --dataset <training csv>`: archive features
(EU power, weather) of `scripts.build_price_training_dataset`, model
`share/data/price_model_coefficients.json`, ticks at local 00..12 every day (known prices end at
midnight, horizon tick + 36 h), hourly, cap 12 ct. MAE in ct/kWh EPEX:

| Variant | MAE Mar–Nov | 0–3 h | 6–12 h | MAE Sep–Nov |
|---|---|---|---|---|
| Constant, window before the start (old) | 2.49 | 1.61 | 2.52 | 2.91 |
| Constant, window to the seam | 2.42 | 1.64 | 2.38 | 2.87 |
| Seam K2 D8 (default) | 2.29 | 1.33 | 2.34 | 2.79 |
| Seam K1 D12 (best Mar–Nov) | 2.24 | 1.23 | 2.32 | 2.82 |

Data 2026-03-01 to 2026-11-03 (Energy-Charts has no Danish power data after 2026-11-04 08:45, so
the training CSV builder stops there). K2 D8 is best in Sep–Nov and close to the best over the
whole period; K1 reacts to a single hour and is worse in autumn. The archive features are
perfect foresight; live features are forecasts, which affects all variants alike. A check on four
days (incl. the DST change) gave the same prices from `resolve_market_slots` as from the script's
formula (≤ 0.0001 ct).

The level problem itself (the model is ~13 ct too low in Nov 2026) stays open in the backlog
item **Price forecast: explain the price level**.
