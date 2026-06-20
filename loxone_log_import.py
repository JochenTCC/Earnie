"""
loxone_log_import.py – Einlesen historischer Loxone-CSV-Logs (nur Migration / Tests).

Nicht für main.py oder profile_manager; nutzen: GenerateConsData.py, app_test_data.py.
"""
from __future__ import annotations

import os

import pandas as pd

import config


def load_and_resample_csv(filepath: str, is_wp: bool = False, wp_power: float = 1.6) -> pd.Series:
    """Lädt eine Loxone-CSV und aggregiert auf 1-Stunden-Mittelwerte."""
    if not filepath or not os.path.exists(filepath):
        return pd.Series(dtype=float)

    try:
        df = pd.read_csv(filepath, sep=";", decimal=",", header=0)

        if df.shape[1] == 3 and not any(
            "datum" in str(col).lower() or "uhrzeit" in str(col).lower() for col in df.columns
        ):
            df = pd.read_csv(
                filepath, sep=";", decimal=",", names=["timestamp", "label", "value"], header=None
            )
        else:
            if df.shape[1] == 2:
                df.columns = ["timestamp", "value"]
            elif df.shape[1] == 3:
                df.columns = ["timestamp", "label", "value"]

        df["timestamp"] = pd.to_datetime(df["timestamp"], format="%d.%m.%Y %H:%M", errors="coerce")
        if df["timestamp"].isna().all():
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        df.dropna(subset=["timestamp", "value"], inplace=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df.dropna(subset=["value"], inplace=True)

        df.set_index("timestamp", inplace=True)
        df = df[~df.index.duplicated(keep="last")]

        s_minutely = df["value"].resample("1min").ffill()
        if is_wp:
            s_minutely = s_minutely * wp_power

        return s_minutely.resample("1h").mean()

    except Exception as e:
        print(f"[WARN] Fehler beim Verarbeiten von {filepath}: {e}")
        return pd.Series(dtype=float)


def load_consumer_series(consumer: dict) -> pd.Series:
    """Zeitreihe eines flexiblen Verbrauchers aus path_log (log_signal_type)."""
    log_signal = consumer.get("log_signal_type") or consumer.get("signal_type", "power")
    is_binary = log_signal == "binary"
    nominal = float(consumer.get("nominal_power_kw", 1.6))
    return load_and_resample_csv(
        consumer.get("path_log", ""),
        is_wp=is_binary,
        wp_power=nominal,
    )


def build_flexible_consumer_dataframe(s_total: pd.Series) -> pd.DataFrame:
    """DataFrame mit Gesamtlast und allen flexiblen Verbrauchern aus Loxone-CSVs."""
    df = pd.DataFrame({"Total": s_total})
    for consumer in config.get_flexible_consumers():
        series = load_consumer_series(consumer)
        df[consumer["name"]] = series if not series.empty else 0.0
        df[consumer["name"]] = df[consumer["name"]].fillna(0.0)
    return df


def compute_baseload(df: pd.DataFrame) -> pd.DataFrame:
    """Subtrahiert flexible Verbraucher von der Gesamtlast."""
    flex_cols = [c["name"] for c in config.get_flexible_consumers()]
    if flex_cols:
        df["BaseLoad"] = df["Total"] - df[flex_cols].sum(axis=1)
    else:
        df["BaseLoad"] = df["Total"]
    df["BaseLoad"] = df["BaseLoad"].clip(lower=0.0)
    return df
