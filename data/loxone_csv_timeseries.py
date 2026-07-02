"""Einlesen stündlicher Loxone-CSV-Zeitreihen (Datum;Zeit;Wert)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_hourly_series(
    filepath: str,
    *,
    value_column: int = 2,
    encoding: str = "latin-1",
) -> pd.Series:
    """Lädt eine Loxone-CSV und liefert eine stündliche Float-Serie (index=Timestamp)."""
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Loxone-CSV nicht gefunden: {filepath}")

    df = pd.read_csv(path, sep=";", decimal=",", header=0, encoding=encoding)
    if df.shape[1] < value_column + 1:
        raise ValueError(
            f"Loxone-CSV '{filepath}' hat zu wenige Spalten (erwartet mindestens {value_column + 1})."
        )

    timestamps = pd.to_datetime(
        df.iloc[:, 0].astype(str) + " " + df.iloc[:, 1].astype(str),
        format="%d.%m.%Y %H:%M:%S",
        errors="coerce",
    )
    values = pd.to_numeric(df.iloc[:, value_column], errors="coerce")
    series = pd.Series(values.values, index=timestamps, name=str(df.columns[value_column]))
    series = series[~series.index.isna()].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    series = series.dropna()
    return series.resample("1h").mean()


def load_power_hourly(filepath: str, *, encoding: str = "latin-1") -> pd.Series:
    """Loxone-Verbrauchszähler-CSV: Spalte 'Leistung' (Index 3)."""
    return load_hourly_series(filepath, value_column=3, encoding=encoding)
