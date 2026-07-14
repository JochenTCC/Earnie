"""Heizleistung aus Gesamtzähler + binären Loxone-Indikatoren (SwimSpa Fall B)."""
from __future__ import annotations

from typing import Literal

import pandas as pd

from data.loxone_csv_timeseries import load_hourly_series, load_power_hourly

AttributionMethod = Literal["indicator", "threshold"]


def _is_active(series: pd.Series) -> pd.Series:
    return series.fillna(0.0) >= 0.5


def load_binary_indicator_hourly(filepath: str) -> pd.Series:
    """Stündliche 0/1-Indikatoren aus Loxone-CSV (Wertspalte Index 2)."""
    return load_hourly_series(filepath, value_column=2)


def derive_heating_power_kw(
    total_kw: pd.Series,
    *,
    heating_active: pd.Series | None,
    filter_active: pd.Series | None,
    filter_nominal_kw: float,
    heating_threshold_kw: float,
) -> tuple[pd.Series, AttributionMethod]:
    """
    Leitet thermische Heizleistung aus Gesamtzähler und Indikatoren ab.

    Mit ``heating_active``: Heizung nur wenn Indikator aktiv; Filteranteil abziehen.
    Ohne Indikator: Fallback über ``heating_power_threshold_kw``.
    """
    if heating_active is not None and not heating_active.dropna().empty:
        index = total_kw.index
        active = _is_active(heating_active.reindex(index).fillna(0.0))
        if filter_active is not None and not filter_active.dropna().empty:
            filter_on = _is_active(filter_active.reindex(index).fillna(0.0))
        else:
            filter_on = pd.Series(False, index=index)
        filter_kw = float(filter_nominal_kw) * filter_on.astype(float)
        heating = (total_kw - filter_kw).clip(lower=0.0) * active.astype(float)
        return heating, "indicator"

    heating = total_kw.where(total_kw >= float(heating_threshold_kw), 0.0)
    return heating, "threshold"


def _load_optional_indicator(history_logs: dict, key: str) -> pd.Series | None:
    path = str(history_logs.get(key, "") or "").strip()
    if not path:
        return None
    return load_binary_indicator_hourly(path)


def load_thermal_history_merged(
    history_logs: dict,
    *,
    heating_threshold_kw: float,
    filter_nominal_kw: float = 0.18,
) -> pd.DataFrame:
    """
    Stündliche Ist-/Außen-Temp., Gesamtleistung und abgeleitete Heizleistung.

    ``power_kw`` = Gesamtzähler (Fall B). ``heating_kw`` nutzt Indikator-CSVs
    wenn konfiguriert, sonst Leistungsschwelle.
    """
    actual_path = history_logs.get("actual_temp_csv", "")
    ambient_path = history_logs.get("ambient_temp_csv", "")
    power_path = history_logs.get("power_csv", "")
    if not actual_path or not ambient_path or not power_path:
        raise ValueError(
            "history_logs benötigt actual_temp_csv, ambient_temp_csv und power_csv."
        )

    total_kw = load_power_hourly(power_path)
    heating_active = _load_optional_indicator(history_logs, "heating_active_csv")
    filter_active = _load_optional_indicator(history_logs, "filter_active_csv")
    heating_kw, method = derive_heating_power_kw(
        total_kw,
        heating_active=heating_active,
        filter_active=filter_active,
        filter_nominal_kw=filter_nominal_kw,
        heating_threshold_kw=heating_threshold_kw,
    )

    merged = pd.DataFrame({
        "ist_c": load_hourly_series(actual_path),
        "ambient_c": load_hourly_series(ambient_path),
        "power_kw": total_kw,
        "heating_kw": heating_kw,
    }).dropna()
    if merged.empty:
        raise ValueError("Keine überlappenden Stunden in den Historien-CSV-Dateien.")
    merged.attrs["heating_attribution"] = method
    return merged.sort_index()


def resolve_live_heating_power_kw(
    *,
    total_kw: float | None,
    filter_kw: float,
    heating_active: bool | None,
) -> float | None:
    """Live-Heizleistung aus Gesamtzähler und Heiz-Indikator (None = unbekannt)."""
    if total_kw is None or heating_active is None:
        return None
    if not heating_active:
        return 0.0
    return round(max(0.0, float(total_kw) - float(filter_kw or 0.0)), 3)
