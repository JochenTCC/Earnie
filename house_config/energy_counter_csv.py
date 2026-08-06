"""Cumulative energy-counter CSV (kWh) → interval-average power (kW)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import pandas as pd

from data.loxone_csv_timeseries import (
    load_loxone_raw_value_series,
    loxone_value_column_headers,
)

logger = logging.getLogger(__name__)

# Same magnitude as consumption_csv Watt heuristic — here means "too large for kW".
_COUNTER_MEDIAN_THRESHOLD = 50.0
_NEAR_ZERO_ABS = 1e-6
_NEAR_ZERO_MAX_SHARE = 0.01
_NEGATIVE_DIFF_MAX_SHARE = 0.01

_ENERGY_NAME_HINTS = ("zähler", "zaehler", "counter", "ertrag")
_POWER_NAME_HINTS = ("leistung", "power_kw", "power")


def looks_like_energy_counter(path: str | Path) -> bool:
    """True if CSV is a cumulative energy counter (kWh), not instantaneous power."""
    file_path = Path(path)
    if not file_path.is_file():
        return False
    header_kind = _header_series_kind(file_path)
    if header_kind == "power":
        return False
    if header_kind == "energy":
        return True
    try:
        series = load_loxone_raw_value_series(str(file_path))
    except (OSError, ValueError):
        return False
    return _values_look_like_energy_counter(series)


def counter_kwh_to_power_kw(energy: pd.Series, *, source: str = "") -> pd.Series:
    """Convert cumulative kWh samples to interval-average kW at left endpoints.

    P(t_i) = (E(t_{i+1}) - E(t_i)) / Δt_i [h]. Negative ΔE → warn and P=0.
    The last sample has no forward interval and is dropped.
    """
    cleaned = energy.dropna().sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")].astype(float)
    if len(cleaned) < 2:
        raise ValueError(
            f"Energiezähler-CSV '{source}' braucht mindestens 2 Samples "
            f"(got {len(cleaned)})."
        )
    powers: list[float] = []
    indices: list[pd.Timestamp] = []
    times = cleaned.index
    for i in range(len(cleaned) - 1):
        t0 = times[i]
        t1 = times[i + 1]
        dt_h = (t1 - t0).total_seconds() / 3600.0
        if dt_h <= 0.0:
            logger.warning(
                "Energiezähler-CSV '%s': non-positive Δt between %s and %s — skip.",
                source,
                t0,
                t1,
            )
            continue
        e0 = float(cleaned.iloc[i])
        e1 = float(cleaned.iloc[i + 1])
        delta_e = e1 - e0
        if delta_e < 0.0:
            logger.warning(
                "Energiezähler-CSV '%s': counter drop %s → %s (ΔE=%.6f kWh) — "
                "ignore interval (P=0).",
                source,
                t0,
                t1,
                delta_e,
            )
            power_kw = 0.0
        else:
            power_kw = delta_e / dt_h
        powers.append(power_kw)
        indices.append(t0)
    if not powers:
        raise ValueError(
            f"Energiezähler-CSV '{source}': keine gültigen Intervalle nach ΔE/Δt."
        )
    return pd.Series(powers, index=pd.DatetimeIndex(indices), dtype=float)


def load_energy_counter_as_power_kw(path: str, *, encoding: str = "latin-1") -> pd.Series:
    """Load Loxone-style counter CSV and return interval-average power (kW)."""
    energy = load_loxone_raw_value_series(path, encoding=encoding)
    if energy.empty:
        raise ValueError(f"Energiezähler-CSV '{path}' enthält keine Datenzeilen.")
    return counter_kwh_to_power_kw(energy, source=path)


def column_header_unit_kind(header: str) -> str | None:
    """Return 'energy', 'power', or None from a single column header cell."""
    lower = str(header).strip().lower()
    # [kWh] before [kW] — "[kwh]" contains the letters of "[kw]".
    if "[kwh]" in lower:
        return "energy"
    if re.search(r"\[kw\]", lower):
        return "power"
    return None


def first_value_column_unit_kind(path: str | Path, *, encoding: str = "latin-1") -> str | None:
    """Unit kind of the first value column after the timestamp, or None."""
    _ts_width, headers = loxone_value_column_headers(str(path), encoding=encoding)
    if not headers:
        return None
    return column_header_unit_kind(headers[0])


def load_grid_dual_energy_as_power_kw(
    path: str, *, encoding: str = "latin-1"
) -> pd.Series:
    """Netz: two cumulative kWh columns → bipolar power (Bezug − Einspeisung).

    First value column = import (positive), second = export (subtracted).
    Both must be labeled ``[kWh]``.
    """
    file_path = Path(path)
    ts_width, headers = loxone_value_column_headers(str(file_path), encoding=encoding)
    if len(headers) < 1 or column_header_unit_kind(headers[0]) != "energy":
        raise ValueError(
            f"Netz-CSV '{path}': erste Wertspalte muss [kWh] sein "
            "(Bezug-Energiezähler)."
        )
    if len(headers) < 2 or column_header_unit_kind(headers[1]) != "energy":
        raise ValueError(
            f"Netz-CSV '{path}' mit Energiezähler [kWh] ist ungültig: "
            "es werden zwei Spalten benötigt (Bezug [kWh], dann Einspeisung [kWh])."
        )
    e_import = load_loxone_raw_value_series(
        str(file_path), encoding=encoding, value_column=ts_width
    )
    e_export = load_loxone_raw_value_series(
        str(file_path), encoding=encoding, value_column=ts_width + 1
    )
    if e_import.empty or e_export.empty:
        raise ValueError(f"Netz-CSV '{path}' enthält keine Datenzeilen.")
    p_import = counter_kwh_to_power_kw(e_import, source=f"{path}#bezug")
    p_export = counter_kwh_to_power_kw(e_export, source=f"{path}#einspeisung")
    aligned = pd.concat(
        [p_import.rename("bezug"), p_export.rename("einspeisung")],
        axis=1,
        join="inner",
    )
    if aligned.empty:
        raise ValueError(
            f"Netz-CSV '{path}': keine überlappenden Intervalle nach ΔE/Δt."
        )
    return aligned["bezug"] - aligned["einspeisung"]


def _header_series_kind(path: Path) -> str | None:
    """Return 'energy', 'power', or None if header is inconclusive."""
    first = _read_header_line(path)
    if not first:
        return None
    lower = first.lower()
    value_header = _value_header_from_line(lower)

    # [kWh] before [kW] — "[kwh]" contains the letters of "[kw]".
    if "[kwh]" in lower:
        return "energy"
    if re.search(r"\[kw\]", lower):
        return "power"
    if any(hint in value_header for hint in _POWER_NAME_HINTS):
        return "power"
    if any(hint in value_header for hint in _ENERGY_NAME_HINTS):
        return "energy"
    if "energie" in value_header and "leistung" not in value_header:
        return "energy"
    return None


def _read_header_line(path: Path) -> str:
    """Read first CSV line; Loxone exports are typically latin-1."""
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            text = path.read_text(encoding=encoding)
        except (OSError, UnicodeDecodeError):
            continue
        if text:
            return text.splitlines()[0]
    return ""


def _value_header_from_line(lower_header: str) -> str:
    parts = [p.strip() for p in lower_header.split(";")]
    if len(parts) >= 3 and parts[0] in {"datum", "date"} and parts[1] in {
        "zeit",
        "time",
        "uhrzeit",
    }:
        return parts[-1]
    if len(parts) >= 2:
        return parts[-1]
    return lower_header


def _values_look_like_energy_counter(series: pd.Series) -> bool:
    cleaned = series.dropna().astype(float)
    if len(cleaned) < 2:
        return False
    near_zero_share = float((cleaned.abs() <= _NEAR_ZERO_ABS).mean())
    if near_zero_share > _NEAR_ZERO_MAX_SHARE:
        return False
    diffs = cleaned.diff().iloc[1:]
    if diffs.empty:
        return False
    neg_share = float((diffs < 0.0).mean())
    if neg_share > _NEGATIVE_DIFF_MAX_SHARE:
        return False
    median_abs = float(cleaned.abs().median())
    return median_abs > _COUNTER_MEDIAN_THRESHOLD
