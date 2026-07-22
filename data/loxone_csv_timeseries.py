"""Einlesen stündlicher Loxone-CSV-Zeitreihen (Datum;Zeit;Wert oder kombiniert)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

_TIME_HEADER_NAMES = frozenset({"zeit", "uhrzeit"})
_DATE_HEADER_NAMES = frozenset({"datum"})
_COMBINED_TS_HINTS = ("datum/uhrzeit", "datum_uhrzeit", "timestamp")


def load_hourly_series(
    filepath: str,
    *,
    value_column: int = 2,
    encoding: str = "latin-1",
) -> pd.Series:
    """Lädt eine Loxone-CSV (Datum;Zeit;…) und liefert eine stündliche Float-Serie."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Loxone-CSV nicht gefunden: {filepath}")

    df = _read_loxone_frame(path, encoding=encoding)
    if df.shape[1] < value_column + 1:
        raise ValueError(
            f"Loxone-CSV '{filepath}' hat zu wenige Spalten "
            f"(erwartet mindestens {value_column + 1})."
        )
    timestamps = _parse_split_timestamps(df)
    return _series_to_hourly(df, timestamps, value_column)


def load_power_hourly(filepath: str, *, encoding: str = "latin-1") -> pd.Series:
    """Loxone-Leistungs-/Wert-CSV: flexible Zeitstempel- und Wertspalte."""
    return load_loxone_value_hourly(filepath, encoding=encoding)


def load_loxone_value_hourly(filepath: str, *, encoding: str = "latin-1") -> pd.Series:
    """Loxone-CSV → stündliche Serie: split oder kombiniert; Leistung oder letzte Spalte."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Loxone-CSV nicht gefunden: {filepath}")

    df = _read_loxone_frame(path, encoding=encoding)
    ts_width = _resolve_timestamp_width(df, filepath)
    value_column = _resolve_value_column(df, ts_width=ts_width, filepath=filepath)
    if ts_width == 2:
        timestamps = _parse_split_timestamps(df)
    else:
        timestamps = _parse_combined_timestamps(df)
    return _series_to_hourly(df, timestamps, value_column)


def _read_loxone_frame(path: Path, *, encoding: str) -> pd.DataFrame:
    return pd.read_csv(path, sep=";", decimal=",", header=0, encoding=encoding)


def _resolve_timestamp_width(df: pd.DataFrame, filepath: str) -> int:
    """Return 2 for Datum+Zeit, 1 for combined timestamp in column 0."""
    if df.shape[1] < 2:
        raise ValueError(
            f"Loxone-CSV '{filepath}' hat zu wenige Spalten (erwartet mindestens 2)."
        )
    headers = [str(c).strip().lower() for c in df.columns]
    if headers[0] in _DATE_HEADER_NAMES and headers[1] in _TIME_HEADER_NAMES:
        if df.shape[1] < 3:
            raise ValueError(
                f"Loxone-CSV '{filepath}' hat zu wenige Spalten "
                "(Datum;Zeit plus Wert erwartet)."
            )
        return 2
    if any(hint in headers[0] for hint in _COMBINED_TS_HINTS):
        return 1
    sample = str(df.iloc[0, 0]).strip() if len(df) else ""
    if " " in sample and _looks_like_loxone_date_prefix(sample):
        return 1
    if df.shape[1] >= 3 and _looks_like_date_only(sample):
        time_sample = str(df.iloc[0, 1]).strip()
        if _looks_like_time(time_sample):
            return 2
    if _looks_like_loxone_date_prefix(sample):
        return 1
    raise ValueError(
        f"Loxone-CSV '{filepath}': Zeitstempel nicht erkennbar "
        "(erwartet Datum;Zeit oder kombiniertes Datum/Uhrzeit)."
    )


def _resolve_value_column(df: pd.DataFrame, *, ts_width: int, filepath: str) -> int:
    for index, name in enumerate(df.columns):
        if str(name).strip().lower() == "leistung":
            return index
    value_column = df.shape[1] - 1
    if value_column < ts_width:
        raise ValueError(
            f"Loxone-CSV '{filepath}' hat zu wenige Spalten "
            f"(erwartet mindestens {ts_width + 1})."
        )
    return value_column


def _parse_split_timestamps(df: pd.DataFrame) -> pd.DatetimeIndex:
    combined = df.iloc[:, 0].astype(str) + " " + df.iloc[:, 1].astype(str)
    timestamps = pd.to_datetime(combined, format="%d.%m.%Y %H:%M:%S", errors="coerce")
    if timestamps.isna().all():
        timestamps = pd.to_datetime(combined, format="%d.%m.%Y %H:%M", errors="coerce")
    return timestamps


def _parse_combined_timestamps(df: pd.DataFrame) -> pd.DatetimeIndex:
    raw = df.iloc[:, 0].astype(str)
    timestamps = pd.to_datetime(raw, format="%d.%m.%Y %H:%M:%S", errors="coerce")
    if timestamps.isna().all():
        timestamps = pd.to_datetime(raw, format="%d.%m.%Y %H:%M", errors="coerce")
    if timestamps.isna().all():
        timestamps = pd.to_datetime(raw, dayfirst=True, errors="coerce")
    return timestamps


def resample_to_hourly_zoh(series: pd.Series) -> pd.Series:
    """Zero-order hold to 1 min, then hourly mean (= ∫P dt / 1h)."""
    cleaned = series.dropna().sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    if cleaned.empty:
        return cleaned
    minutely = cleaned.resample("1min").ffill()
    return minutely.resample("1h").mean().dropna()


def _series_to_hourly(
    df: pd.DataFrame,
    timestamps: pd.Series | pd.DatetimeIndex,
    value_column: int,
) -> pd.Series:
    values = pd.to_numeric(df.iloc[:, value_column], errors="coerce")
    series = pd.Series(
        values.values,
        index=timestamps,
        name=str(df.columns[value_column]),
    )
    series = series[~series.index.isna()].sort_index()
    return resample_to_hourly_zoh(series)


def _looks_like_date_only(text: str) -> bool:
    if len(text) < 8 or "." not in text or " " in text:
        return False
    try:
        pd.to_datetime(text[:10], format="%d.%m.%Y")
        return True
    except (TypeError, ValueError):
        return False


def _looks_like_loxone_date_prefix(text: str) -> bool:
    if len(text) < 8 or "." not in text:
        return False
    try:
        pd.to_datetime(text[:10], format="%d.%m.%Y")
        return True
    except (TypeError, ValueError):
        return False


def _looks_like_time(text: str) -> bool:
    parts = text.split(":")
    if len(parts) not in (2, 3):
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        return 0 <= hour <= 23 and 0 <= minute <= 59
    except ValueError:
        return False
