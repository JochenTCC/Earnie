"""CSV-Format für historische Verbrauchsprofile: timestamp;power_kw (stündlich)."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from data.loxone_csv_timeseries import load_loxone_value_hourly, resample_to_hourly_zoh

logger = logging.getLogger(__name__)

MIN_HOURS_FULL_YEAR = 8760
# Soft floor for Hauskonfigurator import/normalize (short CSVs allowed for QC).
MIN_HOURS_IMPORT = 1
_WATT_MEDIAN_THRESHOLD_KW = 50.0
_DIGITAL_MATCH_FRACTION = 0.95
_DIGITAL_TOLERANCE = 1e-6
_POWER_HEADER_NAMES = frozenset({"power_kw", "kw", "leistung_kw", "leistung"})


def consumer_uses_profile_csv(consumer: dict) -> bool:
    """True when historical CSV is active for modeling (path + use flag)."""
    path = str(consumer.get("profile_csv", "") or "").strip()
    if not path:
        return False
    return bool(consumer.get("use_profile_csv"))


def estimate_annual_kwh_from_profile_csv(path: str) -> float:
    """Estimate kWh/a from a canonical hourly profile CSV.

    Uses the most recent calendar year with the most samples. Missing hours in
    that year count as 0 kW (no upscaling) — important for sparse digital logs.
    Falls back to mean power × 8760 when no year bucket exists.
    """
    rows = load_hourly_profile_csv(path)
    if not rows:
        return 0.0
    by_year: dict[str, list[float]] = {}
    for ts_raw, power_kw in rows:
        year = ts_raw[:4]
        by_year.setdefault(year, []).append(float(power_kw))
    if not by_year:
        return 0.0
    # Prefer coverage, then recency (e.g. 2025 over 2024 when tied).
    year = max(by_year, key=lambda key: (len(by_year[key]), key))
    return float(sum(by_year[year]))

def load_hourly_profile_csv(path: str) -> list[tuple[str, float]]:
    """Liest bereits kanonisches stündliches Profil; liefert (ISO-timestamp, kW)-Paare."""
    from runtime_store.persist_paths import resolve_config_prefixed_path

    resolved = resolve_config_prefixed_path(path)
    file_path = Path(resolved)
    if not file_path.is_file():
        raise FileNotFoundError(f"Profil-CSV nicht gefunden: {path}")
    rows: list[tuple[str, float]] = []
    with file_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        header = next(reader, None)
        if header is None:
            return rows
        col_ts = 0
        col_kw = 1
        if header and header[0].strip().lower() == "timestamp":
            for index, name in enumerate(header):
                if name.strip().lower() in _POWER_HEADER_NAMES:
                    col_kw = index
                    break
        else:
            handle.seek(0)
            reader = csv.reader(handle, delimiter=";")
        for line_no, row in enumerate(reader, start=2 if header else 1):
            parsed = _parse_canonical_row(row, col_ts, col_kw, path, line_no)
            if parsed is not None:
                rows.append(parsed)
    if not rows:
        raise ValueError(f"Profil-CSV '{path}' enthält keine Datenzeilen.")
    return rows


def load_and_normalize_profile_csv(
    path: str,
    *,
    min_hours: int = MIN_HOURS_IMPORT,
    digital_scale_kw: float | None = None,
) -> list[tuple[str, float]]:
    """Detect format, normalize to hourly positive kW, enforce min length."""
    series = detect_and_load_raw_series(path)
    return normalize_hourly_power_kw(
        series,
        min_hours=min_hours,
        source=path,
        digital_scale_kw=digital_scale_kw,
    )


def normalize_profile_csv_file(
    path: str,
    *,
    min_hours: int = MIN_HOURS_IMPORT,
    digital_scale_kw: float | None = None,
) -> list[tuple[str, float]]:
    """Normalize file in place and rewrite as canonical timestamp;power_kw."""
    rows = load_and_normalize_profile_csv(
        path,
        min_hours=min_hours,
        digital_scale_kw=digital_scale_kw,
    )
    write_canonical_hourly_csv(path, rows)
    return rows


def profile_rows_bounds(
    rows: list[tuple[str, float]],
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return (min_ts, max_ts) for canonical profile rows, or None if empty."""
    if not rows:
        return None
    stamps = pd.to_datetime(
        [ts.replace(" ", "T", 1)[:19] for ts, _ in rows],
        errors="coerce",
    )
    valid = stamps[~stamps.isna()]
    if valid.empty:
        return None
    return pd.Timestamp(valid.min()), pd.Timestamp(valid.max())


def profile_span_hours(rows: list[tuple[str, float]]) -> int:
    """Inclusive hour count from first to last timestamp (0 if empty/invalid)."""
    bounds = profile_rows_bounds(rows)
    if bounds is None:
        return 0
    start, end = bounds
    return int((end - start).total_seconds() // 3600) + 1


def shared_import_span_hours(
    verbrauch_rows: list[tuple[str, float]] | None,
    pv_rows: list[tuple[str, float]] | None,
) -> int:
    """Adequacy span: intersection when both series exist, else the single series."""
    v_bounds = profile_rows_bounds(verbrauch_rows or [])
    p_bounds = profile_rows_bounds(pv_rows or [])
    if v_bounds is None and p_bounds is None:
        return 0
    if v_bounds is None:
        return profile_span_hours(pv_rows or [])
    if p_bounds is None:
        return profile_span_hours(verbrauch_rows or [])
    start = max(v_bounds[0], p_bounds[0])
    end = min(v_bounds[1], p_bounds[1])
    if start > end:
        return 0
    return int((end - start).total_seconds() // 3600) + 1


def import_span_adequate_for_se(
    verbrauch_rows: list[tuple[str, float]] | None = None,
    pv_rows: list[tuple[str, float]] | None = None,
    *,
    min_hours: int = MIN_HOURS_FULL_YEAR,
) -> bool:
    """True when shared import span is long enough for SE meter/import paths."""
    return shared_import_span_hours(verbrauch_rows, pv_rows) >= min_hours


def profile_csv_adequate_for_se(
    path: str,
    *,
    min_hours: int = MIN_HOURS_FULL_YEAR,
) -> bool:
    """True when a single profile CSV spans at least ``min_hours`` (SE gate)."""
    try:
        rows = load_hourly_profile_csv(path)
    except (OSError, ValueError, FileNotFoundError):
        return False
    return profile_span_hours(rows) >= min_hours


def is_digital_on_off_series(series: pd.Series) -> bool:
    """True if ≥95% of finite samples are within tolerance of 0 or 1."""
    if series.empty:
        return False
    values = series.dropna().astype(float)
    if values.empty:
        return False
    near_zero = (values.abs() <= _DIGITAL_TOLERANCE).sum()
    near_one = ((values - 1.0).abs() <= _DIGITAL_TOLERANCE).sum()
    return float(near_zero + near_one) / float(len(values)) >= _DIGITAL_MATCH_FRACTION


def profile_csv_looks_digital(path: str) -> bool:
    """True if raw profile looks digital after unit/sign normalization."""
    series = detect_and_load_raw_series(path)
    if series.empty:
        return False
    cleaned = series.dropna().sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    if cleaned.empty:
        return False
    scaled = _normalize_power_unit(cleaned, source=path)
    signed = _normalize_consumption_sign(scaled, source=path)
    return is_digital_on_off_series(signed)


def write_canonical_hourly_csv(path: str, rows: list[tuple[str, float]]) -> None:
    """Write canonical hourly CSV (UTF-8, semicolon)."""
    from runtime_store.persist_paths import resolve_config_prefixed_path

    target = Path(resolve_config_prefixed_path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["timestamp", "power_kw"])
        for ts_raw, power_kw in rows:
            writer.writerow([ts_raw, f"{power_kw:.6f}".rstrip("0").rstrip(".")])


def import_energiemonitor_to_canonical(
    source_path: str,
    *,
    verbrauch_dest: str,
    produktion_dest: str | None = None,
    battery_dest: str | None = None,
    grid_dest: str | None = None,
    min_hours: int = MIN_HOURS_IMPORT,
) -> dict[str, str]:
    """Parse Energiemonitor CSV; write Verbrauch (+ optional PV/Batt/Netz).

    Verbrauch is taken from ``Leistung Verbrauch`` (not derived from Bilanz).
    Returns paths: ``total_profile_csv``, optional ``pv_profile_csv`` /
    ``battery_profile_csv`` / ``grid_profile_csv``.
    """
    from data.energiemonitor_csv import load_energiemonitor_hourly

    series_map = load_energiemonitor_hourly(source_path)
    verbrauch_rows = normalize_hourly_power_kw(
        series_map["verbrauch"],
        min_hours=min_hours,
        source=f"{source_path}#Verbrauch",
    )
    write_canonical_hourly_csv(verbrauch_dest, verbrauch_rows)
    result: dict[str, str] = {"total_profile_csv": verbrauch_dest}
    if "produktion" in series_map and produktion_dest:
        produktion_rows = normalize_hourly_power_kw(
            series_map["produktion"],
            min_hours=min_hours,
            source=f"{source_path}#Produktion",
        )
        write_canonical_hourly_csv(produktion_dest, produktion_rows)
        result["pv_profile_csv"] = produktion_dest
    if "batterie" in series_map and battery_dest:
        batt_rows = normalize_hourly_power_kw(
            series_map["batterie"],
            min_hours=min_hours,
            source=f"{source_path}#Batterie",
            preserve_sign=True,
        )
        write_canonical_hourly_csv(battery_dest, batt_rows)
        result["battery_profile_csv"] = battery_dest
    if "energieversorger" in series_map and grid_dest:
        grid_rows = normalize_hourly_power_kw(
            series_map["energieversorger"],
            min_hours=min_hours,
            source=f"{source_path}#Energieversorger",
            preserve_sign=True,
        )
        write_canonical_hourly_csv(grid_dest, grid_rows)
        result["grid_profile_csv"] = grid_dest
    return result


def import_energiemonitor_balance_to_canonical(
    source_path: str,
    *,
    verbrauch_dest: str,
    pv_dest: str,
    battery_dest: str,
    grid_dest: str,
    min_hours: int = MIN_HOURS_IMPORT,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> dict[str, object]:
    """Derive Verbrauch from Produktion + Batterie + Energieversorger.

    Returns paths + ``clipped_hours`` count.
    """
    from data.energiemonitor_csv import load_energiemonitor_hourly

    series_map = load_energiemonitor_hourly(source_path, require_verbrauch=False)
    missing = [
        name
        for name, key in (
            ("Leistung Produktion", "produktion"),
            ("Leistung Batterie", "batterie"),
            ("Leistung Energieversorger", "energieversorger"),
        )
        if key not in series_map
    ]
    if missing:
        raise ValueError(
            f"Energiemonitor-Bilanz '{source_path}': fehlende Spalten: "
            + ", ".join(missing)
        )
    pv_rows = normalize_hourly_power_kw(
        series_map["produktion"],
        min_hours=min_hours,
        source=f"{source_path}#Produktion",
    )
    batt_rows = normalize_hourly_power_kw(
        series_map["batterie"],
        min_hours=min_hours,
        source=f"{source_path}#Batterie",
        preserve_sign=True,
    )
    grid_rows = normalize_hourly_power_kw(
        series_map["energieversorger"],
        min_hours=min_hours,
        source=f"{source_path}#Energieversorger",
        preserve_sign=True,
    )
    total_rows, clipped = derive_total_from_balance(
        pv_rows,
        batt_rows,
        grid_rows,
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )
    if len(total_rows) < min_hours:
        raise ValueError(
            f"Energiemonitor-Bilanz '{source_path}': nach Schnittmenge nur "
            f"{len(total_rows)} Stunden (mindestens {min_hours} erforderlich)."
        )
    write_canonical_hourly_csv(pv_dest, pv_rows)
    write_canonical_hourly_csv(battery_dest, batt_rows)
    write_canonical_hourly_csv(grid_dest, grid_rows)
    write_canonical_hourly_csv(verbrauch_dest, total_rows)
    return {
        "total_profile_csv": verbrauch_dest,
        "pv_profile_csv": pv_dest,
        "battery_profile_csv": battery_dest,
        "grid_profile_csv": grid_dest,
        "clipped_hours": clipped,
    }


def derive_and_write_balance_total(
    *,
    pv_path: str,
    battery_path: str,
    grid_path: str,
    total_dest: str,
    min_hours: int = MIN_HOURS_IMPORT,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> dict[str, object]:
    """Load PV + Netz (+ optional Batterie), derive total, write ``total_dest``."""
    pv_rows = load_and_normalize_profile_csv(pv_path, min_hours=min_hours)
    grid_series = detect_and_load_raw_series(grid_path)
    grid_rows = normalize_hourly_power_kw(
        grid_series,
        min_hours=min_hours,
        source=grid_path,
        preserve_sign=True,
    )
    batt_rows: list[tuple[str, float]] = []
    batt = str(battery_path or "").strip()
    if batt:
        batt_series = detect_and_load_raw_series(batt)
        batt_rows = normalize_hourly_power_kw(
            batt_series,
            min_hours=min_hours,
            source=batt,
            preserve_sign=True,
        )
        write_canonical_hourly_csv(batt, batt_rows)
    write_canonical_hourly_csv(grid_path, grid_rows)
    write_canonical_hourly_csv(pv_path, pv_rows)
    total_rows, clipped = derive_total_from_balance(
        pv_rows,
        batt_rows,
        grid_rows,
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )
    if len(total_rows) < min_hours:
        raise ValueError(
            f"Bilanz-Import: nach Schnittmenge nur {len(total_rows)} Stunden "
            f"(mindestens {min_hours} erforderlich)."
        )
    write_canonical_hourly_csv(total_dest, total_rows)
    return {
        "total_profile_csv": total_dest,
        "clipped_hours": clipped,
        "hours": len(total_rows),
    }


def detect_and_load_raw_series(path: str) -> pd.Series:
    """Load raw power series (any sampling); energy counter, Loxone, or canonical."""
    from house_config.energy_counter_csv import (
        load_energy_counter_as_power_kw,
        looks_like_energy_counter,
    )
    from runtime_store.persist_paths import resolve_config_prefixed_path

    resolved = resolve_config_prefixed_path(path)
    file_path = Path(resolved)
    if not file_path.is_file():
        raise FileNotFoundError(f"Profil-CSV nicht gefunden: {path}")
    # Energy counters also match Loxone layout — convert ΔE/Δt before ZOH path.
    if looks_like_energy_counter(file_path):
        return load_energy_counter_as_power_kw(str(file_path))
    if _looks_like_loxone_meter(file_path):
        return _load_loxone_raw_or_hourly(str(file_path))
    return _load_canonical_raw_series(path)


def normalize_hourly_power_kw(
    series: pd.Series,
    *,
    min_hours: int = MIN_HOURS_IMPORT,
    source: str = "",
    digital_scale_kw: float | None = None,
    preserve_sign: bool = False,
) -> list[tuple[str, float]]:
    """Unit/sign/resample to 1h; require min_hours samples.

    ``preserve_sign=True`` keeps bipolar series (battery/grid: + into system).
    """
    if series.empty:
        raise ValueError(f"Profil-CSV '{source}' enthält keine Datenzeilen.")
    cleaned = series.dropna().sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    if cleaned.empty:
        raise ValueError(f"Profil-CSV '{source}' enthält keine gültigen Werte.")
    scaled = _normalize_power_unit(cleaned, source=source)
    if preserve_sign:
        signed = scaled
    else:
        signed = _normalize_consumption_sign(scaled, source=source)
    signed = _maybe_scale_digital(signed, digital_scale_kw, source=source)
    hourly = _resample_to_hourly(signed)
    if len(hourly) < min_hours:
        raise ValueError(
            f"Profil-CSV '{source}' hat nach Normalisierung nur {len(hourly)} Stunden "
            f"(mindestens {min_hours} erforderlich)."
        )
    return [
        (ts.strftime("%Y-%m-%d %H:%M:%S"), float(value))
        for ts, value in hourly.items()
    ]


def _rows_to_lookup(rows: list[tuple[str, float]]) -> dict[str, float]:
    return {ts: float(kw) for ts, kw in rows}


def derive_total_from_balance(
    pv_rows: list[tuple[str, float]],
    battery_rows: list[tuple[str, float]] | None,
    grid_rows: list[tuple[str, float]],
    *,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> tuple[list[tuple[str, float]], int]:
    """Derive house load: P_Ges = P_PV + P_Batt + P_Grid (+ = into system).

    Battery may be empty/None (treated as 0 kW). Returns (rows, clipped_negative_hours).
    Intersection: PV ∩ Grid, and ∩ Battery when battery rows are present.
    """
    pv = _rows_to_lookup(pv_rows)
    grid = _rows_to_lookup(grid_rows)
    batt = _rows_to_lookup(battery_rows or [])
    if batt:
        common = sorted(set(pv) & set(batt) & set(grid))
        missing_msg = "PV-, Batterie- und Netz-Serie"
    else:
        common = sorted(set(pv) & set(grid))
        missing_msg = "PV- und Netz-Serie"
    if not common:
        raise ValueError(
            f"Bilanz-Import: keine gemeinsamen Zeitstempel zwischen {missing_msg}."
        )
    sign_pv = -1.0 if invert_pv else 1.0
    sign_batt = -1.0 if invert_battery else 1.0
    sign_grid = -1.0 if invert_grid else 1.0
    out: list[tuple[str, float]] = []
    clipped = 0
    for ts in common:
        total = (
            sign_pv * float(pv[ts])
            + sign_batt * float(batt.get(ts, 0.0))
            + sign_grid * float(grid[ts])
        )
        if total < 0.0:
            clipped += 1
            total = 0.0
        out.append((ts, round(total, 6)))
    return out, clipped


def _maybe_scale_digital(
    series: pd.Series,
    digital_scale_kw: float | None,
    *,
    source: str,
) -> pd.Series:
    if digital_scale_kw is None:
        return series
    if digital_scale_kw <= 0.0:
        raise ValueError(
            f"Profil-CSV '{source}': Nennleistung für Digital-Skalierung muss > 0 sein "
            f"(got {digital_scale_kw})."
        )
    if not is_digital_on_off_series(series):
        raise ValueError(
            f"Profil-CSV '{source}' ist kein digitales 0/1-Signal — "
            "Skalierung mit Nennleistung nicht möglich."
        )
    logger.info(
        "Profil-CSV '%s': digitales Signal × Nennleistung %.3f kW.",
        source,
        digital_scale_kw,
    )
    return series * float(digital_scale_kw)


def _parse_canonical_row(
    row: list[str],
    col_ts: int,
    col_kw: int,
    path: str,
    line_no: int,
) -> tuple[str, float] | None:
    if not row or len(row) <= max(col_ts, col_kw):
        return None
    ts_raw = row[col_ts].strip()
    kw_raw = row[col_kw].strip().replace(",", ".")
    if not ts_raw or ts_raw.lower() == "timestamp":
        return None
    try:
        power_kw = float(kw_raw)
    except ValueError as exc:
        raise ValueError(
            f"{path} Zeile {line_no}: power_kw ungültig ({kw_raw!r})."
        ) from exc
    datetime.fromisoformat(ts_raw.replace(" ", "T", 1)[:19])
    return ts_raw, power_kw


def _looks_like_loxone_meter(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return False
    first = text.splitlines()[0] if text else ""
    lower = first.lower()
    if "datum" in lower and ("zeit" in lower or "uhrzeit" in lower):
        return True
    if "leistung" in lower and ";" in first:
        return True
    try:
        sample = pd.read_csv(path, sep=";", decimal=",", header=0, encoding="latin-1", nrows=3)
    except Exception:
        return False
    if sample.shape[1] < 2:
        return False
    col0 = str(sample.columns[0]).lower()
    if "datum" in col0:
        return True
    first_cell = sample.iloc[0, 0] if len(sample) else ""
    return _row_looks_like_loxone_date(first_cell)


def _row_looks_like_loxone_date(value: object) -> bool:
    text = str(value).strip()
    if len(text) < 8 or "." not in text:
        return False
    try:
        datetime.strptime(text[:10], "%d.%m.%Y")
        return True
    except ValueError:
        return False


def _load_loxone_raw_or_hourly(path: str) -> pd.Series:
    """Loxone CSV via flexible loader (split/combined ts; already hourly mean)."""
    series = load_loxone_value_hourly(path)
    if series.empty:
        raise ValueError(f"Loxone-Profil-CSV '{path}' enthält keine Datenzeilen.")
    return series.astype(float)


def _load_canonical_raw_series(path: str) -> pd.Series:
    rows = load_hourly_profile_csv(path)
    index = pd.to_datetime(
        [ts.replace(" ", "T", 1)[:19] for ts, _ in rows],
        errors="coerce",
    )
    values = [kw for _, kw in rows]
    series = pd.Series(values, index=index, dtype=float)
    series = series[~series.index.isna()].sort_index()
    return series[~series.index.duplicated(keep="last")]


def _normalize_power_unit(series: pd.Series, *, source: str) -> pd.Series:
    median_abs = float(series.abs().median())
    if median_abs > _WATT_MEDIAN_THRESHOLD_KW:
        logger.info(
            "Profil-CSV '%s': Median |P|=%.1f wirkt wie Watt — Division durch 1000.",
            source,
            median_abs,
        )
        return series / 1000.0
    return series


def _normalize_consumption_sign(series: pd.Series, *, source: str) -> pd.Series:
    """Earnie convention: consumption is positive kW."""
    nonzero = series[series != 0.0]
    if nonzero.empty:
        return series
    negative_share = float((nonzero < 0).mean())
    if negative_share > 0.5:
        logger.info(
            "Profil-CSV '%s': Mehrheit negativ — Vorzeichen invertiert (Verbrauch positiv).",
            source,
        )
        return -series
    return series


def _resample_to_hourly(series: pd.Series) -> pd.Series:
    """Zero-order hold to 1 min, then hourly mean (= ∫P dt / 1h)."""
    return resample_to_hourly_zoh(series)