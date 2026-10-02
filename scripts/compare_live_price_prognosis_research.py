"""Compare live price-prognosis with/without live bias.

Example:

  .venv\\Scripts\\python.exe -m scripts.compare_live_price_prognosis_research \\
      --hours 12 --with-live-bias

Requires network (Open-Meteo / Energy-Charts) when not fully mocked.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from data.market_prices import (
    PRICE_SOURCE_PREDICTED,
    normalize_price_slot,
    resolve_market_slots,
)
from data.price_forecast_live import (
    build_live_feature_frame_for_slots,
    load_configured_model,
)
from data.tariff_pricing import import_cent_kwh


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "OLS green-zone predictions with optional live bias "
            "(archive hour-of-day EU power stand-in)."
        )
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=12,
        help="Number of future hour parents to predict (default 12).",
    )
    parser.add_argument(
        "--tz",
        default="Europe/Vienna",
        help="Planning timezone for synthetic target hours.",
    )
    parser.add_argument(
        "--with-live-bias",
        action="store_true",
        help="Also print a column with live_bias_enabled=True (uses Day-Ahead lookback).",
    )
    parser.add_argument(
        "--bias-cap",
        type=float,
        default=12.0,
        help="live_bias_cap_cent_kwh when --with-live-bias (default 12).",
    )
    return parser.parse_args()


def _future_hour_slots(hours: int, tz_name: str) -> list[datetime]:
    tz = ZoneInfo(tz_name)
    start = normalize_price_slot(datetime.now(tz)).replace(
        minute=0, second=0, microsecond=0
    ) + timedelta(hours=1)
    return [start + timedelta(hours=i) for i in range(hours)]


def _tariff_parity_check(epex: float = 10.0) -> dict:
    """Sanity: same EPEX → same k_act for day_ahead vs predicted formula."""
    spec = {
        "type": "spot_hourly",
        "settlement_fee_cent_kwh": 1.5,
        "markup_percent": 3.0,
        "prices_include_vat": False,
        "vat_percent": 20.0,
    }
    nne = 2.0
    k = import_cent_kwh(epex, spec, netzentgelt_override=nne)
    return {
        "epex": epex,
        "k_act": round(k, 4),
        "note": "import_cent_kwh is shared by day_ahead and predicted paths",
    }


def main() -> int:
    args = _parse_args()
    model = load_configured_model()
    if model is None:
        print("ERROR: no price model (share/data/price_model_coefficients.json).")
        return 1

    targets = _future_hour_slots(args.hours, args.tz)
    print(json.dumps({"tariff_parity": _tariff_parity_check()}, indent=2))

    variants = [("archive_hod", False)]
    if args.with_live_bias:
        variants.append(("archive_hod+bias", True))

    market = []
    for hours_back in range(1, 72):
        slot = targets[0] - timedelta(hours=hours_back)
        market.append({"timestamp": slot, "price_buy": 8.0 + (hours_back % 5)})

    frame = build_live_feature_frame_for_slots(targets)
    rows = []
    if frame is None or frame.empty:
        print(json.dumps({"error": "no feature frame"}, indent=2))
        return 1

    for label, bias_on in variants:
        resolved = resolve_market_slots(
            market,
            targets,
            missing_price_strategy="forecast",
            forecast_model=model,
            forecast_feature_frame=frame,
            live_bias_enabled=bias_on,
            live_bias_lookback_hours=48,
            live_bias_cap_cent_kwh=float(args.bias_cap),
        )
        predicted = [
            r for r in resolved if r.get("price_source") == PRICE_SOURCE_PREDICTED
        ]
        if not predicted:
            rows.append({"variant": label, "error": "no predicted slots"})
            continue
        prices = [float(r["price_buy"]) for r in predicted]
        rows.append(
            {
                "variant": label,
                "n_predicted": len(predicted),
                "mean_epex": round(sum(prices) / len(prices), 3),
                "min_epex": round(min(prices), 3),
                "max_epex": round(max(prices), 3),
                "live_bias": predicted[0].get("live_bias_cent_kwh"),
            }
        )

    print(json.dumps({"variants": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
