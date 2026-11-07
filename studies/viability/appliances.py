"""Washing machine, dishwasher and dryer of a study house (trial, section ``geraete`` of the parameter file).

The energy is part of the household electricity. Each appliance gets one hourly profile per house:
on which days it runs and when it starts is random, with a fixed seed, so L0 to L3 share the same
runs. ``geraete.rolle`` says what Earnie may do with them: ``known`` keeps the profile as fixed load
in every ladder step (the person starts the appliance, Earnie only uses the battery); ``flex`` keeps
energy and run days of the profile but lets L2 (cheapest block) and L3 (plan) choose the start inside
the window ``fenster_start`` of the same day, L0 and L1 keep the profile's times.
"""
from __future__ import annotations

import csv
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

HOURS_PER_DAY = 24
DAYS_PER_WEEK = 7
# The window of a run reaches past the year's end, and the first one starts the day before.
MARGIN_DAYS = 31
_EPS = 1e-9


@dataclass(frozen=True)
class Appliance:
    id: str
    runs_per_week: float
    kwh_per_run: float
    duration_h: float
    annual_kwh: float
    profile_csv: str

    @property
    def power_kw(self) -> float:
        return self.kwh_per_run / self.duration_h


def start_hour_weights(params: dict) -> dict[int, float]:
    """Weight per start hour: even over the window, with a slight peak around each ``haeufungen`` hour."""
    first, last = params["geraete"]["fenster_start"]
    peak = params["geraete"]["haeufung_gewicht"]
    width = params["geraete"]["haeufung_breite_h"]
    return {
        hour: 1.0 + sum(
            peak * math.exp(-0.5 * ((hour - center) / width) ** 2)
            for center in params["geraete"]["haeufungen"]
        )
        for hour in range(first, last + 1)
    }


def daily_runs(
    appliance_id: str, runs_per_week: float, house_id: str, params: dict
) -> dict[date, int]:
    """Start hour per day with a run; the same house and seed give the same runs."""
    grid = params["geraete"]
    year = int(params["preisjahr"])
    rng = random.Random(f"{grid['seed']}:{house_id}:{appliance_id}")  # NOSONAR python:S2245 reproducible study data
    weights = start_hour_weights(params)
    hours, values = list(weights), list(weights.values())
    day = date(year, 1, 1) - timedelta(days=MARGIN_DAYS)
    end = date(year, 12, 31) + timedelta(days=MARGIN_DAYS)
    runs: dict[date, int] = {}
    while day <= end:
        if rng.random() < runs_per_week / DAYS_PER_WEEK:
            runs[day] = rng.choices(hours, values)[0]
        day += timedelta(days=1)
    return runs


def _hour_shares(duration_h: float) -> list[float]:
    whole = int(math.floor(duration_h + _EPS))
    rest = duration_h - whole
    return [1.0] * whole + ([rest] if rest > _EPS else [])


def write_profile(path: Path, runs: dict[date, int], power_kw: float, duration_h: float, params: dict) -> float:
    """Write the hourly profile in Earnie's CSV format; returns the kWh of the price year."""
    year = int(params["preisjahr"])
    shares = _hour_shares(duration_h)
    if max(params["geraete"]["fenster_start"]) + len(shares) > HOURS_PER_DAY:
        raise SystemExit(f"Ein Lauf von {duration_h} h endet nicht mehr am selben Tag: {path.name}")
    first = date(year, 1, 1) - timedelta(days=MARGIN_DAYS)
    days = (date(year, 12, 31) - first).days + 1 + MARGIN_DAYS
    annual = 0.0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:  # NOSONAR pythonsecurity:S2083 built from the study folder
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(["timestamp", "power_kw"])
        for offset in range(days):
            day = first + timedelta(days=offset)
            start = runs.get(day)
            for hour in range(HOURS_PER_DAY):
                kw = 0.0
                if start is not None and 0 <= hour - start < len(shares):
                    kw = power_kw * shares[hour - start]
                if day.year == year:
                    annual += kw
                # Earnie looks a slot up by this exact text; another format would read as 0 kW.
                writer.writerow([f"{day.isoformat()} {hour:02d}:00:00", f"{kw:.4f}"])
    return annual


def build_appliances(house, params: dict, config_dir: Path) -> list[Appliance]:
    """Profiles of the house's appliances under ``<config>/appliances``; nothing when the trial is off."""
    grid = params["geraete"]
    if not grid["aktiv"]:
        return []
    per_week = grid["laeufe_je_woche"][str(house.axes["personen"])]
    built: list[Appliance] = []
    for appliance_id, spec in grid["geraete"].items():
        runs_per_week = float(per_week[appliance_id])
        power = spec["kwh_je_lauf"] / spec["dauer_h"]
        runs = daily_runs(appliance_id, runs_per_week, house.id, params)
        relative = f"appliances/{appliance_id}.csv"
        annual = write_profile(config_dir / relative, runs, power, spec["dauer_h"], params)
        built.append(
            Appliance(appliance_id, runs_per_week, spec["kwh_je_lauf"], spec["dauer_h"], round(annual, 1),
                      f"config/{relative}")
        )
    return built


def baseload_target_kwh(household_kwh: float, profile_consumers: list[dict]) -> float:
    """Flat baseload the house must keep: the appliances are part of the household electricity."""
    return household_kwh - sum(float(c["annual_kwh"]) for c in profile_consumers if c.get("use_profile_csv"))


def flex_schedule(appliance: Appliance, params: dict) -> dict:
    """Earnie schedule of a ``flex`` appliance: start window = ``fenster_start`` as start hour +- shift.

    Energy and run days come from the CSV (``use_profile_csv``); ``runs_per_week`` only has to be a
    positive integer for Earnie's schedule check, so the weekly runs are rounded up.
    """
    first, last = params["geraete"]["fenster_start"]
    shift = (last - first) // 2
    return {
        "runs_per_week": max(1, math.ceil(appliance.runs_per_week - _EPS)),
        "duration_h": appliance.duration_h,
        "start_hour": first + shift,
        "start_shift_h": float(shift),
    }


def appliance_consumer(appliance: Appliance, template: dict, params: dict) -> dict:
    """House profile row with the role of ``geraete.rolle``; the CSV carries energy and run days."""
    role = params["geraete"]["rolle"]
    consumer = {k: v for k, v in template.items() if k not in ("appliance_recommendation", "schedule")}
    consumer.update(
        nominal_power_kw=round(appliance.power_kw, 4),
        annual_kwh=appliance.annual_kwh,
        earnie_role=role,
        profile_csv=appliance.profile_csv,
        use_profile_csv=True,
    )
    if role == "flex":
        consumer["schedule"] = flex_schedule(appliance, params)
    return consumer
