"""CSV-Format für historische Verbrauchsprofile: timestamp;power_kw (stündlich)."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from data.loxone_csv_timeseries import load_loxone_value_hourly

logger = logging.getLogger(__name__)

MIN_HOURS_FULL_YEAR = 8760
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
    file_path = Path(path)
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
    min_hours: int = MIN_HOURS_FULL_YEAR,
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
    min_hours: int = MIN_HOURS_FULL_YEAR,
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
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["timestamp", "power_kw"])
        for ts_raw, power_kw in rows:
            writer.writerow([ts_raw, f"{power_kw:.6f}".rstrip("0").rstrip(".")])


def detect_and_load_raw_series(path: str) -> pd.Series:
    """Load raw power series (any sampling); Loxone meter or timestamp;power_kw."""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Profil-CSV nicht gefunden: {path}")
    if _looks_like_loxone_meter(file_path):
        return _load_loxone_raw_or_hourly(path)
    return _load_canonical_raw_series(path)


def normalize_hourly_power_kw(
    series: pd.Series,
    *,
    min_hours: int = MIN_HOURS_FULL_YEAR,
    source: str = "",
    digital_scale_kw: float | None = None,
) -> list[tuple[str, float]]:
    """Unit/sign/resample to 1h; require min_hours samples."""
    if series.empty:
        raise ValueError(f"Profil-CSV '{source}' enthält keine Datenzeilen.")
    cleaned = series.dropna().sort_index()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    if cleaned.empty:
        raise ValueError(f"Profil-CSV '{source}' enthält keine gültigen Werte.")
    scaled = _normalize_power_unit(cleaned, source=source)
    signed = _normalize_consumption_sign(scaled, source=source)
    signed = _maybe_scale_digital(signed, digital_scale_kw, source=source)
    hourly = _resample_to_hourly(signed)
    if len(hourly) < min_hours:
        raise ValueError(
            f"Profil-CSV '{source}' hat nach Normalisierung nur {len(hourly)} Stunden "
            f"(mindestens {min_hours} erforderlich, ca. 12 Monate)."
        )
    return [
        (ts.strftime("%Y-%m-%d %H:%M:%S"), float(value))
        for ts, value in hourly.items()
    ]


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
    if series.empty:
        return series
    deltas = series.index.to_series().diff().dropna()
    median_delta = deltas.median() if not deltas.empty else pd.Timedelta(hours=1)
    if pd.isna(median_delta):
        median_delta = pd.Timedelta(hours=1)
    if median_delta <= pd.Timedelta(hours=1):
        hourly = series.resample("1h").mean()
    else:
        hourly = series.resample("1h").mean().interpolate(method="time")
    return hourly.dropna()
