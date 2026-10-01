"""Internal research: compare live price-prognosis feature/bias variants.

Not for public release. Example:

  .venv\\Scripts\\python.exe -m scripts.compare_live_price_prognosis_research \\
      --hours 12

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
    EU_POWER_LIVE_SOURCE_ARCHIVE_HOD,
    EU_POWER_LIVE_SOURCE_ENERGY_CHARTS_FORECAST,
    build_live_feature_frame_for_slots,
    load_configured_model,
)
from data.tariff_pricing import import_cent_kwh


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Research-only: OLS green-zone predictions with archive_hod vs "
            "energy_charts_forecast and optional live bias."
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

    variants = [
        ("archive_hod", EU_POWER_LIVE_SOURCE_ARCHIVE_HOD, False),
        ("energy_charts_forecast", EU_POWER_LIVE_SOURCE_ENERGY_CHARTS_FORECAST, False),
    ]
    if args.with_live_bias:
        variants.append(
            ("energy_charts_forecast+bias", EU_POWER_LIVE_SOURCE_ENERGY_CHARTS_FORECAST, True)
        )

    # Minimal Day-Ahead history so resolve does not fail when bias lookback is empty:
    # mirror fallback still needs some past prices if forecast features miss a slot.
    market = []
    for hours_back in range(1, 72):
        slot = targets[0] - timedelta(hours=hours_back)
        market.append({"timestamp": slot, "price_buy": 8.0 + (hours_back % 5)})

    rows = []
    for label, power_source, bias_on in variants:
        # Force power source for this variant without mutating config.json.
        import data.price_forecast_live as pfl

        frame = None
        with _force_power_source(pfl, power_source):
            frame = build_live_feature_frame_for_slots(targets)
        if frame is None or frame.empty:
            rows.append({"variant": label, "error": "no feature frame"})
            continue
        resolved = resolve_market_slots(
            market,
            targets,
            missing_price_strategy="forecast",
            forecast_model=model,
            forecast_feature_frame=frame,
            eu_power_live_source=power_source,
            live_bias_enabled=bias_on,
            live_bias_lookback_hours=48,
        )
        predicted = [r for r in resolved if r.get("price_source") == PRICE_SOURCE_PREDICTED]
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
                "power_source": predicted[0].get("eu_power_live_source"),
            }
        )

    print(json.dumps({"variants": rows}, indent=2))
    return 0


class _force_power_source:
    def __init__(self, module, source: str) -> None:
        self._module = module
        self._source = source
        self._orig = None

    def __enter__(self):
        self._orig = self._module.get_eu_power_live_source
        self._module.get_eu_power_live_source = lambda: self._source
        return self

    def __exit__(self, *args):
        self._module.get_eu_power_live_source = self._orig
        return False


if __name__ == "__main__":
    raise SystemExit(main())
