#!/usr/bin/env python3
"""Compare PV forecast providers against measured PV energy (dev tool, no daemon change).

``fetch`` stores hourly energy forecasts (kWh per clock hour, UTC slot start) per PV system
of the live scenario; run it hourly (Task Scheduler / cron). ``evaluate`` compares the stored
forecasts with the measured PV energy from ``optimization_history.jsonl``
(``closed_interval.pv_energy_kwh``).

Sources:
  forecast_solar        forecast.solar ``watt_hours_period`` (energy of the period ending at the key)
  forecast_solar_earnie forecast.solar ``watts`` at the slot start, as ``data/pv_forecast.py`` maps it
  solcast               Solcast rooftop sites (``SOLCAST_API_KEY``, ``SOLCAST_SITES=<pv_id>=<resource_id>,…``)
  open_meteo_<model>    Open-Meteo ``global_tilted_irradiance`` × kWp × performance ratio

Usage (UTF-8 env, from the Earnie repo root):
  .venv\\Scripts\\python.exe -m scripts.pv_forecast_compare fetch
  .venv\\Scripts\\python.exe -m scripts.pv_forecast_compare evaluate --history <path> [--history <path> …]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

FORECAST_SOLAR_URL = "https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}"
SOLCAST_URL = "https://api.solcast.com.au/rooftop_sites/{resource_id}/forecasts"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_MODELS = ("icon_d2", "icon_seamless", "ecmwf_ifs025")

# Solcast hobbyist: 10 calls per UTC day; 2 sites × 4 hours = 8, leaves 2 for manual tests.
DEFAULT_SOLCAST_HOURS = "5,8,11,14"
DEFAULT_SOLCAST_DAILY_LIMIT = 10
# forecast.solar free: 12 calls/h per public IP, shared with the production daemon.
MIN_INTERVAL = {"forecast_solar": timedelta(minutes=55), "open_meteo": timedelta(minutes=55)}
LEAD_BUCKETS = ((0, 6, "0-6 h"), (6, 24, "6-24 h"), (24, 48, "24-48 h"))
DAYLIGHT_KWH = 0.01
OUT_DIRNAME = "pv_forecast_compare"


@dataclass(frozen=True)
class PvSystem:
    id: str
    kwp: float
    tilt: float
    azimuth: float


# ---------------------------------------------------------------------------
# Slot mapping (pure functions, unit-tested)
# ---------------------------------------------------------------------------


def _slot_key(slot_start_utc: datetime) -> str:
    return slot_start_utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:00Z")


def _parse_slot_key(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H:00Z").replace(tzinfo=timezone.utc)


def _hour_floor(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def _add_kwh(slots: dict[str, float], slot_start_utc: datetime, kwh: float) -> None:
    key = _slot_key(slot_start_utc)
    slots[key] = round(slots.get(key, 0.0) + kwh, 4)


def forecast_solar_period_slots(watt_hours_period: dict[str, float], tz: ZoneInfo) -> dict[str, float]:
    """Energy of the period ending at each local key → clock hour that contains the period."""
    slots: dict[str, float] = {}
    for key, wh in watt_hours_period.items():
        period_end = datetime.strptime(key, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        slot_start = _hour_floor(period_end - timedelta(seconds=1))
        _add_kwh(slots, slot_start, float(wh) / 1000.0)
    return slots


def forecast_solar_earnie_slots(watts: dict[str, float], tz: ZoneInfo) -> dict[str, float]:
    """``watts`` at the full-hour key taken as the mean power of that hour (``data/pv_forecast.py``)."""
    slots: dict[str, float] = {}
    for key, w in watts.items():
        ts = datetime.strptime(key, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
        if ts.minute or ts.second:
            continue  # sunrise / sunset keys never match a slot start in Earnie
        _add_kwh(slots, ts, float(w) / 1000.0)
    return slots


def solcast_slots(forecasts: list[dict[str, Any]]) -> dict[str, float]:
    """Solcast mean power (kW) per period ending at ``period_end`` → clock hour energy."""
    slots: dict[str, float] = {}
    for row in forecasts:
        period_end = datetime.fromisoformat(str(row["period_end"]).replace("Z", "+00:00"))
        period = str(row["period"])
        if period != "PT30M":
            raise ValueError(f"Solcast: unerwartete Periode {period!r} (erwartet PT30M).")
        slot_start = _hour_floor(period_end - timedelta(seconds=1))
        _add_kwh(slots, slot_start, float(row["pv_estimate"]) * 0.5)
    return slots


def open_meteo_slots(
    times: list[str], gti_w_m2: list[float | None], kwp: float, performance_ratio: float
) -> dict[str, float]:
    """Hourly GTI is the mean of the preceding hour (UTC timestamps) → slot ``t - 1 h``."""
    slots: dict[str, float] = {}
    for t, gti in zip(times, gti_w_m2):
        if gti is None:
            continue  # beyond the model horizon (ICON-D2: 48 h)
        end = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        _add_kwh(slots, end - timedelta(hours=1), float(gti) / 1000.0 * kwp * performance_ratio)
    return slots


def actual_slots(history_rows: Iterable[dict[str, Any]], tz: ZoneInfo) -> dict[str, float]:
    """Measured PV energy per clock hour; only hours with all four quarter hours."""
    by_interval: dict[datetime, float] = {}
    for row in history_rows:
        closed = row.get("closed_interval")
        if not isinstance(closed, dict) or closed.get("pv_energy_kwh") is None:
            continue
        start = datetime.fromisoformat(str(closed["interval_start"]))
        if start.tzinfo is None:
            start = start.replace(tzinfo=tz)
        by_interval[start.astimezone(timezone.utc)] = float(closed["pv_energy_kwh"])
    sums: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for start, kwh in by_interval.items():
        key = _slot_key(_hour_floor(start))
        sums[key] += kwh
        counts[key] += 1
    return {key: round(sums[key], 4) for key in sums if counts[key] == 4}


# ---------------------------------------------------------------------------
# fetch
# ---------------------------------------------------------------------------


def _load_state(path: str) -> dict[str, Any]:
    if not os.path.isfile(path):
        return {"last_fetch": {}, "solcast_calls": {}}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_state(path: str, state: dict[str, Any]) -> None:
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)
    os.replace(tmp, path)


def _due(state: dict[str, Any], source: str, now: datetime) -> bool:
    last = state["last_fetch"].get(source)
    return last is None or now - datetime.fromisoformat(last) >= MIN_INTERVAL[source]


def _fetch_forecast_solar(lat: float, lon: float, system: PvSystem, timeout: int) -> dict[str, dict[str, float]]:
    url = FORECAST_SOLAR_URL.format(
        lat=lat, lon=lon, tilt=system.tilt, azimuth=system.azimuth, kwp=system.kwp
    )
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    tz = ZoneInfo(payload["message"]["info"]["timezone"])
    result = payload["result"]
    return {
        "forecast_solar": forecast_solar_period_slots(result["watt_hours_period"], tz),
        "forecast_solar_earnie": forecast_solar_earnie_slots(result["watts"], tz),
    }


def _fetch_solcast(resource_id: str, api_key: str, timeout: int) -> dict[str, float]:
    response = requests.get(
        SOLCAST_URL.format(resource_id=resource_id),
        params={"format": "json", "hours": 48},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return solcast_slots(response.json()["forecasts"])


def _fetch_open_meteo(
    lat: float, lon: float, system: PvSystem, performance_ratio: float, timeout: int
) -> dict[str, dict[str, float]]:
    response = requests.get(
        OPEN_METEO_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "hourly": "global_tilted_irradiance",
            "tilt": system.tilt,
            "azimuth": system.azimuth,
            "models": ",".join(OPEN_METEO_MODELS),
            "timezone": "UTC",
            "forecast_days": 3,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    hourly = response.json()["hourly"]
    return {
        f"open_meteo_{model}": open_meteo_slots(
            hourly["time"],
            hourly[f"global_tilted_irradiance_{model}"],
            system.kwp,
            performance_ratio,
        )
        for model in OPEN_METEO_MODELS
    }


def _solcast_sites(raw: str) -> dict[str, str]:
    sites: dict[str, str] = {}
    for part in raw.split(","):
        if not part.strip():
            continue
        pv_id, sep, resource_id = part.partition("=")
        if not sep or not pv_id.strip() or not resource_id.strip():
            raise ValueError(f"SOLCAST_SITES: Eintrag {part!r} ist nicht <pv_id>=<resource_id>.")
        sites[pv_id.strip()] = resource_id.strip()
    return sites


def _planning_systems() -> tuple[float, float, str, list[PvSystem]]:
    import config

    systems = [
        PvSystem(
            id=str(s["id"]),
            kwp=float(s["pv_kwp"]),
            tilt=float(s["pv_tilt"]),
            azimuth=float(s["pv_azimuth"]),
        )
        for s in config.get_planning_pv_systems()
    ]
    if not systems:
        raise SystemExit("Keine PV-Anlagen im Live-Szenario (config.get_planning_pv_systems leer).")
    lat = float(config.get("LATITUDE", cast=float))
    lon = float(config.get("LONGITUDE", cast=float))
    return lat, lon, config.get_planning_timezone(), systems


def _out_dir(arg: str | None) -> str:
    if arg:
        return arg
    from runtime_store.persist_paths_base import runtime_path

    return runtime_path(OUT_DIRNAME)


def cmd_fetch(args: argparse.Namespace) -> int:
    from runtime_store.dotenv_loader import load_app_dotenv

    load_app_dotenv()
    lat, lon, tz_name, systems = _planning_systems()
    tz = ZoneInfo(tz_name)
    out_dir = _out_dir(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    state_path = os.path.join(out_dir, "state.json")
    state = _load_state(state_path)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    run_id = now.isoformat()
    records: list[dict[str, Any]] = []
    failures = 0

    def add(source: str, system_id: str, slots: dict[str, float]) -> None:
        records.append(
            {"run_id": run_id, "fetched_at": run_id, "source": source, "system_id": system_id, "kwh": slots}
        )

    if _due(state, "forecast_solar", now):
        try:
            for system in systems:
                for source, slots in _fetch_forecast_solar(lat, lon, system, args.timeout).items():
                    add(source, system.id, slots)
            state["last_fetch"]["forecast_solar"] = run_id
        except (requests.RequestException, KeyError, ValueError) as exc:
            failures += 1
            print(f"[FEHLER] forecast.solar: {exc}")
    else:
        print("[skip] forecast.solar: letzter Abruf < 55 min.")

    if _due(state, "open_meteo", now):
        try:
            for system in systems:
                for source, slots in _fetch_open_meteo(
                    lat, lon, system, args.performance_ratio, args.timeout
                ).items():
                    add(source, system.id, slots)
            state["last_fetch"]["open_meteo"] = run_id
        except (requests.RequestException, KeyError, ValueError) as exc:
            failures += 1
            print(f"[FEHLER] Open-Meteo: {exc}")
    else:
        print("[skip] Open-Meteo: letzter Abruf < 55 min.")

    api_key = os.environ.get("SOLCAST_API_KEY", "").strip()
    if not api_key:
        print("[skip] Solcast: SOLCAST_API_KEY nicht gesetzt.")
    else:
        sites = _solcast_sites(os.environ.get("SOLCAST_SITES", ""))
        missing = [s.id for s in systems if s.id not in sites]
        if missing:
            raise SystemExit(f"SOLCAST_SITES: keine resource_id für PV-Anlage(n) {missing}.")
        local_now = now.astimezone(tz)
        hours = {int(h) for h in args.solcast_hours.split(",") if h.strip()}
        hour_tag = local_now.strftime("%Y-%m-%dT%H")
        day_tag = now.strftime("%Y-%m-%d")
        used = int(state["solcast_calls"].get(day_tag, 0))
        if local_now.hour not in hours and not args.solcast_now:
            print(f"[skip] Solcast: {local_now.hour} Uhr nicht in --solcast-hours {sorted(hours)}.")
        elif state["last_fetch"].get("solcast_hour") == hour_tag and not args.solcast_now:
            print("[skip] Solcast: in dieser Stunde schon abgerufen.")
        elif used + len(systems) > args.solcast_daily_limit:
            print(f"[skip] Solcast: Tagesbudget ({used}/{args.solcast_daily_limit} Aufrufe, UTC-Tag) erschöpft.")
        else:
            try:
                for system in systems:
                    state["solcast_calls"][day_tag] = used = used + 1
                    add("solcast", system.id, _fetch_solcast(sites[system.id], api_key, args.timeout))
                state["last_fetch"]["solcast_hour"] = hour_tag
            except (requests.RequestException, KeyError, ValueError) as exc:
                failures += 1
                print(f"[FEHLER] Solcast: {exc}")
        state["solcast_calls"] = {d: n for d, n in state["solcast_calls"].items() if d >= day_tag}

    if records:
        with open(os.path.join(out_dir, "forecasts.jsonl"), "a", encoding="utf-8") as fh:
            for record in records:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
    _save_state(state_path, state)
    sources = sorted({r["source"] for r in records})
    print(f"[OK] {len(records)} Prognosen gespeichert ({', '.join(sources) or '—'}) → {out_dir}")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


def _read_jsonl(paths: Iterable[str]) -> Iterable[dict[str, Any]]:
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def _history_paths(args_history: list[str] | None) -> list[str]:
    if args_history:
        paths: list[str] = []
        for pattern in args_history:
            matches = sorted(glob.glob(pattern))
            if not matches:
                raise SystemExit(f"--history {pattern!r}: keine Datei gefunden.")
            paths.extend(matches)
        return paths
    from runtime_store.optimization_history import history_archive_paths, history_file_path

    return [*history_archive_paths(), history_file_path()]


def plant_runs(records: Iterable[dict[str, Any]], system_ids: set[str]) -> dict[str, list[tuple[datetime, dict[str, float]]]]:
    """Per source: list of (fetched_at, plant kWh per slot); slots only where every system has a value."""
    grouped: dict[tuple[str, str], dict[str, dict[str, float]]] = defaultdict(dict)
    for record in records:
        grouped[(record["source"], record["run_id"])][record["system_id"]] = record["kwh"]
    runs: dict[str, list[tuple[datetime, dict[str, float]]]] = defaultdict(list)
    for (source, run_id), by_system in grouped.items():
        if set(by_system) != system_ids:
            continue
        common = set.intersection(*(set(s) for s in by_system.values()))
        plant = {key: round(sum(s[key] for s in by_system.values()), 4) for key in common}
        runs[source].append((datetime.fromisoformat(run_id), plant))
    for source in runs:
        runs[source].sort(key=lambda item: item[0])
    return runs


def latest_in_bucket(
    runs: list[tuple[datetime, dict[str, float]]], lo_h: int, hi_h: int
) -> dict[str, float]:
    """Per slot the forecast with the shortest lead time inside [lo_h, hi_h)."""
    best: dict[str, tuple[datetime, float]] = {}
    for fetched_at, plant in runs:
        for key, kwh in plant.items():
            lead_h = (_parse_slot_key(key) - fetched_at).total_seconds() / 3600.0
            if not (lo_h <= lead_h < hi_h):
                continue
            if key not in best or fetched_at > best[key][0]:
                best[key] = (fetched_at, kwh)
    return {key: kwh for key, (_, kwh) in best.items()}


def metrics(pairs: list[tuple[float, float]]) -> dict[str, float]:
    """pairs = (forecast, actual) kWh."""
    n = len(pairs)
    mean_actual = sum(a for _, a in pairs) / n
    mae = sum(abs(f - a) for f, a in pairs) / n
    bias = sum(f - a for f, a in pairs) / n
    ff = sum(f * f for f, _ in pairs)
    scale = sum(f * a for f, a in pairs) / ff if ff else float("nan")
    mae_scaled = sum(abs(scale * f - a) for f, a in pairs) / n
    return {
        "n": n,
        "mae": mae,
        "bias": bias,
        "rmae_pct": 100.0 * mae / mean_actual if mean_actual else float("nan"),
        "scale": scale,
        "mae_scaled": mae_scaled,
    }


def daily_day_ahead(
    runs: list[tuple[datetime, dict[str, float]]], day: date, tz: ZoneInfo
) -> float | None:
    """Daily kWh of ``day`` from the latest run fetched before local midnight."""
    midnight = datetime.combine(day, datetime.min.time(), tzinfo=tz)
    candidates = [(t, plant) for t, plant in runs if t < midnight]
    if not candidates:
        return None
    _, plant = candidates[-1]
    keys = _day_slot_keys(day, tz)
    if not all(k in plant for k in keys if _is_daylight_hour(k, tz)):
        return None
    return sum(plant.get(k, 0.0) for k in keys)


def _day_slot_keys(day: date, tz: ZoneInfo) -> list[str]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=tz).astimezone(timezone.utc)
    keys, t = [], start
    while t < end:
        keys.append(_slot_key(t))
        t += timedelta(hours=1)
    return keys


def _is_daylight_hour(key: str, tz: ZoneInfo) -> bool:
    return 6 <= _parse_slot_key(key).astimezone(tz).hour < 19


def _fmt(value: float, digits: int = 2) -> str:
    return "—" if value != value else f"{value:.{digits}f}"


def cmd_evaluate(args: argparse.Namespace) -> int:
    _, _, tz_name, systems = _planning_systems()
    tz = ZoneInfo(tz_name)
    out_dir = _out_dir(args.out_dir)
    forecasts_path = os.path.join(out_dir, "forecasts.jsonl")
    if not os.path.isfile(forecasts_path):
        raise SystemExit(f"Keine Prognosen unter {forecasts_path} — erst `fetch` laufen lassen.")
    runs = plant_runs(_read_jsonl([forecasts_path]), {s.id for s in systems})
    actual = actual_slots(_read_jsonl(_history_paths(args.history)), tz)
    if not actual:
        raise SystemExit("Keine Messwerte (closed_interval.pv_energy_kwh) in der Historie gefunden.")
    sources = sorted(runs)
    print(f"Quellen: {', '.join(sources)} · Messstunden: {len(actual)} · TZ {tz_name}")
    print("Nur Tageslicht-Stunden (Messung oder Prognose > 0.01 kWh), nur Stunden, die alle Quellen haben.\n")

    for lo, hi, label in LEAD_BUCKETS:
        per_source = {s: latest_in_bucket(runs[s], lo, hi) for s in sources}
        keys = set(actual).intersection(*(set(v) for v in per_source.values()))
        keys = {
            k for k in keys
            if actual[k] > DAYLIGHT_KWH or any(per_source[s][k] > DAYLIGHT_KWH for s in sources)
        }
        print(f"== Vorlauf {label}: {len(keys)} Stunden ==")
        if not keys:
            print("   (keine gemeinsamen Stunden)\n")
            continue
        print(f"   {'Quelle':<24}{'MAE kWh':>9}{'rMAE %':>8}{'Bias':>8}{'Skala':>7}{'MAE skal.':>10}")
        for source in sources:
            m = metrics([(per_source[source][k], actual[k]) for k in sorted(keys)])
            print(
                f"   {source:<24}{_fmt(m['mae'], 3):>9}{_fmt(m['rmae_pct'], 1):>8}"
                f"{_fmt(m['bias'], 3):>8}{_fmt(m['scale']):>7}{_fmt(m['mae_scaled'], 3):>10}"
            )
        print()

    days = sorted({_parse_slot_key(k).astimezone(tz).date() for k in actual})
    complete_days = [d for d in days if all(k in actual for k in _day_slot_keys(d, tz) if _is_daylight_hour(k, tz))]
    print(f"== Tagesenergie Day-ahead (letzter Abruf vor Mitternacht), {len(complete_days)} Tage ==")
    rows = []
    for day in complete_days:
        measured = sum(actual.get(k, 0.0) for k in _day_slot_keys(day, tz))
        row = {"day": day, "actual": measured}
        for source in sources:
            row[source] = daily_day_ahead(runs[source], day, tz)
        rows.append(row)
    usable = [r for r in rows if all(r[s] is not None for s in sources)]
    if not usable:
        print("   (noch keine Tage mit Day-ahead-Prognose aller Quellen)")
        return 0
    print(f"   {'Quelle':<24}{'MAE kWh/d':>10}{'Bias kWh/d':>11}")
    for source in sources:
        errs = [r[source] - r["actual"] for r in usable]
        print(f"   {source:<24}{_fmt(sum(map(abs, errs)) / len(errs)):>10}{_fmt(sum(errs) / len(errs)):>11}")
    print()
    header = f"   {'Tag':<12}{'Ist':>7}" + "".join(f"{s[:14]:>15}" for s in sources)
    print(header)
    for r in usable[-args.days:]:
        print(f"   {r['day'].isoformat():<12}{r['actual']:>7.1f}" + "".join(f"{r[s]:>15.1f}" for s in sources))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out-dir", help=f"Ablage (Standard: runtime/{OUT_DIRNAME})")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Prognosen aller Quellen abrufen und anhängen (stündlich aufrufen)")
    fetch.add_argument("--timeout", type=int, default=20)
    fetch.add_argument(
        "--performance-ratio",
        type=float,
        default=0.85,
        help="Open-Meteo: kWh = GTI/1000 × kWp × PR (Standard 0.85; die Auswertung zeigt zusätzlich MAE nach Skalierung)",
    )
    fetch.add_argument("--solcast-hours", default=DEFAULT_SOLCAST_HOURS, help="Ortszeit-Stunden für Solcast-Abrufe")
    fetch.add_argument("--solcast-daily-limit", type=int, default=DEFAULT_SOLCAST_DAILY_LIMIT)
    fetch.add_argument("--solcast-now", action="store_true", help="Solcast jetzt abrufen (Stundenplan ignorieren, Budget gilt)")
    fetch.set_defaults(func=cmd_fetch)

    evaluate = sub.add_parser("evaluate", help="Prognosen gegen gemessene PV-Energie auswerten")
    evaluate.add_argument(
        "--history",
        action="append",
        help="optimization_history.jsonl (Glob erlaubt, mehrfach); Standard: aktive Runtime inkl. Archive",
    )
    evaluate.add_argument("--days", type=int, default=21, help="Anzahl Tage in der Tagestabelle")
    evaluate.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
