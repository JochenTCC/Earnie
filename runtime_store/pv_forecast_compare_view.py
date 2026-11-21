"""PV forecasts of the comparison logger as lines for Chart 1 (dev / maintainer install only).

``scripts/pv_forecast_compare.py fetch`` writes one JSON line per run, source and PV system to
``forecasts.jsonl`` (``fetched_at`` UTC, ``kwh`` per clock hour keyed ``YYYY-MM-DDTHH:00Z``).
This module turns that file into one kW series per source for the hours of a chart.

Run choice (decided 2026-11-21, maintainer, option a): for an hour ``H`` each source uses its
**latest run fetched before ``H`` starts**, i.e. the forecast Earnie would have planned with.
For future hours that is the latest run. The value is the hour's energy in kWh, which is the
mean power in kW over that hour. Sources are summed over the PV systems; when a system has no
value for an hour, the hour stays empty (no partial sum).

Enabled only by ``EARNIE_PV_FORECAST_COMPARE_DIR`` (the logger's output directory). Without
it nothing is read and Chart 1 is unchanged.
"""
from __future__ import annotations

import json
import os
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

ENV_DIR = "EARNIE_PV_FORECAST_COMPARE_DIR"
FORECASTS_FILENAME = "forecasts.jsonl"
# A run reaches at most a few days ahead; older runs cannot be the latest before a chart hour.
RUN_LOOKBACK = timedelta(days=4)

SOURCE_LABELS: dict[str, str] = {
    "forecast_solar": "forecast.solar (Stundenenergie)",
    "forecast_solar_earnie": "forecast.solar (Earnie-Abbildung)",
    "solcast": "Solcast",
    "open_meteo_icon_d2": "Open-Meteo ICON-D2",
    "open_meteo_icon_seamless": "Open-Meteo ICON seamless",
    "open_meteo_ecmwf_ifs025": "Open-Meteo ECMWF IFS",
}


class PvForecastCompareError(RuntimeError):
    """The configured comparison directory or file cannot be read."""


def compare_dir_from_env() -> Path | None:
    """Configured logger directory, or None when the feature is off."""
    raw = os.environ.get(ENV_DIR, "").strip()
    return Path(raw) if raw else None


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


def hour_key(moment: datetime) -> str:
    """Logger key of the clock hour that contains ``moment`` (aware datetime)."""
    if moment.tzinfo is None:
        raise ValueError("hour_key braucht eine Zeit mit Zeitzone.")
    utc = moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return utc.strftime("%Y-%m-%dT%H:00Z")


def _parse_utc(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError(f"Zeit ohne Zeitzone: {text!r}")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class _Run:
    fetched_at: datetime
    kwh: dict[str, float]


def _fetched_at_prefix(line: str) -> str | None:
    """``fetched_at`` text without a full JSON parse (filters most lines cheaply)."""
    marker = '"fetched_at":'
    start = line.find(marker)
    if start < 0:
        return None
    first = line.find('"', start + len(marker))
    end = line.find('"', first + 1)
    if first < 0 or end < 0:
        return None
    return line[first + 1 : end]


def _read_runs(
    path: Path, *, earliest: datetime, latest: datetime
) -> dict[tuple[str, str], list[_Run]]:
    """Runs per (source, system) fetched in [earliest, latest], sorted by ``fetched_at``."""
    runs: dict[tuple[str, str], list[_Run]] = {}
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            stamp_text = _fetched_at_prefix(line)
            if stamp_text is None:
                raise PvForecastCompareError(f"{path}:{number}: fetched_at fehlt.")
            stamp = _parse_utc(stamp_text)
            if stamp < earliest or stamp > latest:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PvForecastCompareError(f"{path}:{number}: kein gültiges JSON ({exc}).") from exc
            key = (str(record["source"]), str(record["system_id"]))
            kwh = {str(k): float(v) for k, v in record["kwh"].items() if v is not None}
            runs.setdefault(key, []).append(_Run(fetched_at=stamp, kwh=kwh))
    for series in runs.values():
        series.sort(key=lambda run: run.fetched_at)
    return runs


def _latest_before(runs: Sequence[_Run], stamps: Sequence[datetime], hour_start: datetime):
    index = bisect_right(stamps, hour_start)
    return runs[index - 1] if index > 0 else None


def series_by_source(
    path: Path, hour_starts: Iterable[datetime]
) -> dict[str, dict[str, float | None]]:
    """kW per source and logger hour key for the given hour starts (rule a, summed systems)."""
    hours = sorted({_parse_utc(hour_key(h)) for h in hour_starts})
    if not hours:
        return {}
    if not path.is_file():
        raise PvForecastCompareError(f"Datei der Test-Prognosen fehlt: {path}")
    runs = _read_runs(path, earliest=hours[0] - RUN_LOOKBACK, latest=hours[-1])
    systems_by_source: dict[str, set[str]] = {}
    for source, system in runs:
        systems_by_source.setdefault(source, set()).add(system)
    out: dict[str, dict[str, float | None]] = {}
    for source in sorted(systems_by_source):
        systems = sorted(systems_by_source[source])
        stamps = {s: [run.fetched_at for run in runs[(source, s)]] for s in systems}
        values: dict[str, float | None] = {}
        for hour in hours:
            key = hour.strftime("%Y-%m-%dT%H:00Z")
            total: float | None = 0.0
            for system in systems:
                run = _latest_before(runs[(source, system)], stamps[system], hour)
                kwh = run.kwh.get(key) if run is not None else None
                if kwh is None:
                    total = None
                    break
                total += kwh
            values[key] = round(total, 3) if total is not None else None
        out[source] = values
    return out


_CACHE: dict[tuple, dict[str, dict[str, float | None]]] = {}


def cached_series_by_source(
    path: Path, hour_starts: Sequence[datetime]
) -> dict[str, dict[str, float | None]]:
    """:func:`series_by_source`, cached per file state and chart hours (Chart 1 reruns often)."""
    try:
        stat = path.stat()
    except OSError as exc:
        raise PvForecastCompareError(f"Datei der Test-Prognosen fehlt: {path}") from exc
    keys = tuple(sorted({hour_key(h) for h in hour_starts}))
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size, keys)
    hit = _CACHE.get(cache_key)
    if hit is None:
        _CACHE.clear()
        hit = series_by_source(path, hour_starts)
        _CACHE[cache_key] = hit
    return hit


def slot_series(
    by_source: dict[str, dict[str, float | None]], slot_starts: Sequence[datetime]
) -> dict[str, list[float | None]]:
    """Per source one value per chart slot (a quarter hour takes its hour's mean kW)."""
    keys = [hour_key(start) for start in slot_starts]
    return {source: [values.get(key) for key in keys] for source, values in by_source.items()}
