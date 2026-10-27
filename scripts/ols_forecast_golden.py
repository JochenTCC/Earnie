"""Recorded inputs and golden output of the OLS price forecast (Edibert P5 parity).

``record`` fetches the EU features (Energy-Charts, Open-Meteo archive) and the Day-Ahead
prices (Edibert ``MarketArchive``) of two DST weeks once and writes them with the model to
``tests/fixtures/edibert_forecast/``. ``golden`` runs ``resolve_market_slots`` over every
case and writes ``expected.json``. ``tests/test_edibert_p5_forecast.py`` rebuilds the same
cases from the fixture and compares.

    python -m scripts.ols_forecast_golden record
    python -m scripts.ols_forecast_golden golden
"""
from __future__ import annotations

import argparse
import json
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

FIXTURE_DIR = Path("tests/fixtures/edibert_forecast")
MODEL_FILE = "model.json"
EXPECTED_FILE = "expected.json"
VIENNA = ZoneInfo("Europe/Vienna")
ZONE = "AT"
# Two windows with a DST change each (2025-03-30, 2025-10-26).
WINDOWS: dict[str, tuple[date, date]] = {
    "spring": (date(2025, 3, 24), date(2025, 4, 7)),
    "autumn": (date(2025, 10, 20), date(2025, 11, 3)),
}
# (days after the window start, hour): history for mirror and bias; 10:00 before, 14:00 after the
# Day-Ahead publication; the gappy days 4, 8, 10 fall into their 72 h.
MOMENTS = ((3, 10), (3, 14), (7, 10), (9, 14))
FRAME_VARIANTS = ("hourly_naive", "quarter_naive", "hourly_aware", "gappy")
BIAS_VARIANTS: dict[str, dict[str, Any]] = {
    "off": {"live_bias_enabled": False},
    "on": {"live_bias_enabled": True, "live_bias_lookback_hours": 48, "live_bias_cap_cent_kwh": 12.0},
    "capped": {"live_bias_enabled": True, "live_bias_lookback_hours": 48, "live_bias_cap_cent_kwh": 0.3},
}
MODEL_PATH_LABEL = Path("share/data/price_model_coefficients.json")


@dataclass(frozen=True)
class Case:
    name: str
    window: str
    moment: datetime
    horizon_hours: int
    frame_variant: str
    bias_variant: str
    hourly_market: bool


def _features_path(window: str) -> Path:
    return FIXTURE_DIR / f"features_{window}.csv"


def _prices_path(window: str) -> Path:
    return FIXTURE_DIR / f"prices_{window}.csv"


def record() -> None:
    """Fetch features and prices of both windows; copy the model."""
    from data.price_forecast_live import _build_archive_feature_frame

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MODEL_PATH_LABEL, FIXTURE_DIR / MODEL_FILE)
    for window, (start, end) in WINDOWS.items():
        slots = [datetime(start.year, start.month, start.day), datetime(end.year, end.month, end.day) - timedelta(hours=1)]
        frame = _build_archive_feature_frame(slots)
        if frame is None or frame.empty:
            raise RuntimeError(f"Keine EU-Features für {window}.")
        frame.to_csv(_features_path(window), index_label="slot")
        # UTC keys: a naive Vienna index would average the repeated autumn hour.
        prices = _utc_prices(start, end)
        if prices.empty:
            raise RuntimeError(f"Keine Preise für {window}.")
        prices.to_csv(_prices_path(window), index_label="slot_utc")


def _utc_prices(start: date, end: date) -> pd.Series:
    from data.edibert_market_range import CACHE_DIR_NAME
    from edibert import api
    from runtime_store.persist_paths import runtime_path

    archive = api.MarketArchive(ZONE, Path(runtime_path(CACHE_DIR_NAME)), timeout=60)
    first = datetime(start.year, start.month, start.day, tzinfo=VIENNA)
    last = datetime(end.year, end.month, end.day, tzinfo=VIENNA)
    data = archive.prices(first, last)
    slots = sorted(data.prices)
    return pd.Series([data.prices[s] for s in slots], index=pd.DatetimeIndex(slots, tz=UTC), name="cent")


def load_model():
    from data.price_forecast_model import load_price_model

    return load_price_model(FIXTURE_DIR / MODEL_FILE)


def load_features(window: str) -> pd.DataFrame:
    frame = pd.read_csv(_features_path(window), index_col="slot", parse_dates=["slot"])
    frame.index = pd.DatetimeIndex(frame.index)
    return frame


def load_prices(window: str) -> pd.Series:
    series = pd.read_csv(_prices_path(window), index_col="slot_utc", parse_dates=["slot_utc"])["cent"]
    series.index = pd.DatetimeIndex(series.index).tz_convert(UTC)
    return series


def frame_variant(frame: pd.DataFrame, variant: str, window: str) -> pd.DataFrame:
    """Feature frame as live / SE hand it in: naive hourly, naive quarter-hourly, aware, or with gaps."""
    if variant == "hourly_naive":
        return frame
    if variant == "quarter_naive":
        parts = []
        for minutes in (0, 15, 30, 45):
            part = frame.copy()
            part.index = part.index + pd.Timedelta(minutes=minutes)
            parts.append(part)
        return pd.concat(parts).sort_index(kind="stable")
    if variant == "hourly_aware":
        aware = frame.copy()
        aware.index = aware.index.tz_localize(VIENNA, ambiguous="infer")
        return aware
    if variant == "gappy":
        start = WINDOWS[window][0]
        # Evenings of two forecast days and a whole day have no features: those slots fall to the mirror.
        drop = (
            ((frame.index.normalize() == pd.Timestamp(start + timedelta(days=4))) & (frame.index.hour >= 18))
            | ((frame.index.normalize() == pd.Timestamp(start + timedelta(days=8))) & (frame.index.hour >= 18))
            | (frame.index.normalize() == pd.Timestamp(start + timedelta(days=10)))
        )
        return frame.loc[~drop]
    raise ValueError(variant)


def _cutoff(moment: datetime) -> datetime:
    """Day-Ahead known up to the end of today, after 13:00 up to the end of tomorrow."""
    days = 2 if moment.hour >= 13 else 1
    day = moment.date() + timedelta(days=days)
    return datetime(day.year, day.month, day.day, tzinfo=VIENNA)


def market_data(prices: pd.Series, moment: datetime, *, hourly: bool) -> list[dict[str, Any]]:
    cutoff = _cutoff(moment).astimezone(UTC)
    rows = []
    for slot_utc, cent in prices.items():
        slot = slot_utc.to_pydatetime()
        if slot >= cutoff:
            continue
        local = slot.astimezone(VIENNA)
        if hourly and local.minute != 0:
            continue
        rows.append({"timestamp": local, "hour": local.hour, "price_buy": float(cent)})
    return rows


def target_slots(moment: datetime, horizon_hours: int) -> list[datetime]:
    start = moment.astimezone(UTC)
    return [(start + timedelta(minutes=15 * i)).astimezone(VIENNA) for i in range(horizon_hours * 4)]


def iter_cases() -> Iterator[Case]:
    """Per moment: every frame variant with the bias on (72 h), bias off / capped, and a 48 h horizon."""
    for window, (start, _end) in WINDOWS.items():
        for day, hour in MOMENTS:
            d = start + timedelta(days=day)
            moment = datetime(d.year, d.month, d.day, hour, tzinfo=VIENNA)
            stem = f"{window}-{d.isoformat()}T{hour:02d}"
            combos = [(72, fv, "on") for fv in FRAME_VARIANTS]
            combos += [(72, "hourly_naive", "off"), (72, "hourly_naive", "capped"), (48, "hourly_naive", "on")]
            for horizon, fv, bv in combos:
                yield Case(f"{stem}-{horizon}h-{fv}-bias_{bv}", window, moment, horizon, fv, bv, False)
            if (day, hour) == MOMENTS[0]:
                yield Case(f"{stem}-72h-hourly_naive-bias_on-hourly_market", window, moment, 72, "hourly_naive", "on", True)


def run_case(case: Case, inputs: dict[str, Any]) -> list[dict[str, Any]]:
    """``resolve_market_slots`` (strategy ``forecast``) on the recorded inputs of ``case``."""
    from data.market_prices import resolve_market_slots

    frame = frame_variant(inputs["features"][case.window], case.frame_variant, case.window)
    market = market_data(inputs["prices"][case.window], case.moment, hourly=case.hourly_market)
    # The live bias reads its lookback features through this builder; serve the recorded frame.
    with patch("data.price_forecast_live.build_live_feature_frame_for_slots", return_value=frame):
        rows = resolve_market_slots(
            market,
            target_slots(case.moment, case.horizon_hours),
            missing_price_strategy="forecast",
            forecast_model=inputs["model"],
            forecast_feature_frame=frame,
            forecast_model_path=MODEL_PATH_LABEL,
            eu_power_live_source="archive",
            **BIAS_VARIANTS[case.bias_variant],
        )
    return [compact_row(row) for row in rows]


ROW_KEYS = ("slot_datetime", "hour", "price_buy", "price_source")


def compact_row(row: dict[str, Any]) -> list[Any]:
    """``[slot ISO, hour, price_buy, price_source, {other fields}]``."""
    extras = {k: v for k, v in sorted(row.items()) if k not in ROW_KEYS}
    return [row["slot_datetime"].isoformat(), row["hour"], row["price_buy"], row["price_source"], extras]


def load_inputs() -> dict[str, Any]:
    return {
        "model": load_model(),
        "features": {w: load_features(w) for w in WINDOWS},
        "prices": {w: load_prices(w) for w in WINDOWS},
    }


def golden() -> None:
    inputs = load_inputs()
    expected = {case.name: run_case(case, inputs) for case in iter_cases()}
    with (FIXTURE_DIR / EXPECTED_FILE).open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(expected, fh, separators=(",", ":"), sort_keys=True)
        fh.write("\n")
    sources: dict[str, int] = {}
    for rows in expected.values():
        for row in rows:
            sources[row[3]] = sources.get(row[3], 0) + 1
    print(f"{len(expected)} Fälle, Slots je Quelle: {sources}")


def main() -> None:
    import config  # noqa: F401  (load before data.* to avoid the config ↔ optimizer import cycle)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=("record", "golden"))
    args = parser.parse_args()
    if args.action == "record":
        record()
    else:
        golden()


if __name__ == "__main__":
    main()
