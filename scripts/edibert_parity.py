"""Edibert P3a parity harness: Earnie's pricing engine vs. Edibert, slot by slot.

  python -m scripts.edibert_parity [--from 2025-01-01] [--to 2026-10-01] [--workers N]
      [--tariffs-path share/config/tariffs.json] [--grid-fees-path share/config/grid_fees.json]
      [--prices ZONE=CSV]... [--fetch-prices] [--tariffs ID,...] [--areas ID,...]
      [--tolerance 1e-4] [--out runtime/edibert_parity] [--site-config]

Matrix: every import tariff × every grid area of its ``land`` plus "no grid fee", every
export tariff without area. Each case runs month by month over ``[from, to)``: Earnie's
seams (``import_brutto_cent_for_slots`` / ``enrich_matrix_feed_in_prices`` with
``EARNIE_PRICING_ENGINE=earnie``) against the Edibert adapter (``data.edibert_slot_prices``),
same day-ahead prices for both. Compared: final cent per slot and, for import with an area,
the net grid fee (``grid_fee_work_cent`` vs. ``PricePoint.grid_cent``).

A month that only one engine can price is reported with both outcomes (e.g. Earnie's
monthly-table fallback vs. Edibert ``PRICE_MISSING`` until Edibert ``0.1.g``); it is not a
price deviation. Deviations of a triaged kind (``docs/dev/edibert-integration.md`` § P3a,
*Triage*) are counted apart: T1 = hourly settled spot tariff in the repeated autumn DST hour.
Exit code 1 when an untriaged price deviation exceeds the tolerance.

Earnie's price helpers read the planning time zone from ``config``; without
``--site-config`` the harness points ``config`` at the test fixture config (as pytest does),
so an unmigrated site config does not block the run. Prices: Energy-Charts CSV export
(``Datum (MEZ)`` in UTC, EUR/MWh); hourly rows count for their four quarter-hours.
``--fetch-prices`` downloads the period from the Energy-Charts API for every zone without
``--prices`` and caches it as such a CSV under ``--out`` (the SNAP rule starts 2026-04-01, so
the default period needs 2026 prices).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TIMEZONE = "Europe/Vienna"
ENERGY_CHARTS_PRICE_URL = "https://api.energy-charts.info/price"
_SLOT = timedelta(minutes=15)
_MAX_SAMPLES = 5


def _use_fixture_config() -> None:
    fixture = ROOT / "tests" / "fixtures" / "backtesting"
    os.environ["EARNIE_CONFIG_PATH"] = str(fixture / "config.json")
    os.environ["EARNIE_TARIFFS_PATH"] = str(fixture / "tariffs.json")
    os.environ["EARNIE_HOUSE_PROFILES_PATH"] = str(fixture / "house_profiles.json")
    os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"] = str(fixture / "backtesting_scenarios.json")
    os.environ["EARNIE_COMPONENTS_PATH"] = str(fixture / "components.json")


@dataclass(frozen=True)
class Case:
    direction: str  # "import" | "export"
    tariff_id: str
    tariff_type: str
    land: str
    area_id: str | None

    @property
    def key(self) -> str:
        return f"{self.direction}:{self.tariff_id}@{self.area_id or '-'}"


@dataclass
class CaseResult:
    case: Case
    months_compared: int = 0
    slots_compared: int = 0
    max_diff_cent: float = 0.0
    over_tol_cent: int = 0
    max_diff_grid: float = 0.0
    over_tol_grid: int = 0
    triaged_t1: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)
    month_outcomes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case": self.case.key,
            "direction": self.case.direction,
            "tariff_id": self.case.tariff_id,
            "tariff_type": self.case.tariff_type,
            "land": self.case.land,
            "area_id": self.case.area_id,
            "months_compared": self.months_compared,
            "slots_compared": self.slots_compared,
            "max_diff_cent": self.max_diff_cent,
            "over_tol_cent": self.over_tol_cent,
            "max_diff_grid": self.max_diff_grid,
            "over_tol_grid": self.over_tol_grid,
            "triaged_t1": self.triaged_t1,
            "samples": self.samples,
            "month_outcomes": self.month_outcomes,
            "warnings": sorted(set(self.warnings)),
            "skipped": self.skipped,
        }


# --- Inputs -------------------------------------------------------------------------


@lru_cache(maxsize=4)
def _load_prices(path: str) -> dict[datetime, float]:
    """Energy-Charts CSV → cent/kWh per 15-min slot start (UTC)."""
    rows: list[tuple[datetime, float]] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        next(reader)  # unit row
        if len(header) < 2:
            raise ValueError(f"{path}: Energy-Charts-CSV mit Zeit- und Preisspalte erwartet.")
        for record in reader:
            if len(record) < 2 or not record[1].strip():
                continue
            moment = datetime.fromisoformat(record[0]).astimezone(UTC)
            rows.append((moment, float(record[1]) * 0.1))
    rows.sort()
    prices: dict[datetime, float] = {}
    for index, (moment, cent) in enumerate(rows):
        step = rows[index + 1][0] - moment if index + 1 < len(rows) else (
            moment - rows[index - 1][0] if index else _SLOT
        )
        for offset in range(max(1, int(step / _SLOT))):
            prices[moment + _SLOT * offset] = cent
    return prices


def _fetch_chunk(zone: str, first: date, last: date, cache_dir: Path) -> dict[str, Any]:
    """One Energy-Charts request (cached as JSON); waits and retries on HTTP 429."""
    import requests

    path = cache_dir / f"{zone}_{first.isoformat()}_{last.isoformat()}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    for attempt in range(6):
        response = requests.get(
            ENERGY_CHARTS_PRICE_URL,
            params={"bzn": zone, "start": first.isoformat(), "end": last.isoformat()},
            headers={"User-Agent": "Earnie-edibert-parity", "Accept": "application/json"},
            timeout=120,
        )
        if response.status_code != 429:
            break
        wait = int(response.headers.get("Retry-After", "") or 60 * (attempt + 1))
        print(f"Energy-Charts 429 für {zone} {first}: warte {wait} s", flush=True)
        time.sleep(wait)
    response.raise_for_status()
    payload = response.json()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def fetch_prices_csv(zone: str, start: date, end: date, out_dir: Path) -> Path:
    """Energy-Charts day-ahead prices for ``[start, end)`` as cached CSV (one request per quarter)."""
    path = out_dir / f"prices_{zone}_{start.isoformat()}_{end.isoformat()}.csv"
    if path.is_file():
        return path
    rows: dict[int, float] = {}
    months = _month_starts(start, end)
    for index in range(0, len(months), 3):
        first = months[index]
        after = months[index + 3] if index + 3 < len(months) else end
        payload = _fetch_chunk(zone, first, min(after, end), out_dir / "price_cache")
        for stamp, price in zip(payload.get("unix_seconds") or [], payload.get("price") or []):
            if price is not None:
                rows[int(stamp)] = float(price)
    if not rows:
        raise SystemExit(f"Energy-Charts lieferte keine Preise für {zone} {start} → {end}.")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Datum (MEZ)", f"Day Ahead Auktion ({zone})"])
        writer.writerow(["Datum", "EUR/MWh"])
        for stamp in sorted(rows):
            writer.writerow([datetime.fromtimestamp(stamp, UTC).isoformat(), rows[stamp]])
    return path


def _netznutzung(area_id: str) -> dict[str, Any]:
    """The ``netznutzung`` object as Earnie writes it into a house profile."""
    from data.grid_fees import default_netznutzung_config

    return {**default_netznutzung_config(), "area_id": area_id}


def _month_starts(start: date, end: date) -> list[date]:
    months = []
    current = date(start.year, start.month, 1)
    while current < end:
        months.append(current)
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return months


def _month_slots(month: date, start: date, end: date) -> list[datetime]:
    """Aware house-time 15-min slots of one month, clipped to ``[start, end)``."""
    tz = ZoneInfo(TIMEZONE)
    first = max(month, start)
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    last = min(nxt, end)
    cursor = datetime(first.year, first.month, first.day, tzinfo=tz).astimezone(UTC)
    stop = datetime(last.year, last.month, last.day, tzinfo=tz).astimezone(UTC)
    slots = []
    while cursor < stop:
        slots.append(cursor.astimezone(tz))
        cursor += _SLOT
    return slots


def build_cases(
    tariffs_path: str,
    grid_fees_path: str,
    *,
    tariff_filter: set[str] | None,
    area_filter: set[str] | None,
) -> list[Case]:
    from house_config import edibert_tariffs as eb

    tariff_set = eb.load_tariff_set(tariffs_path)
    catalog = eb.cached_grid_fees(grid_fees_path)
    cases: list[Case] = []
    for direction, table in (("import", tariff_set.imports), ("export", tariff_set.exports)):
        for tariff_id, tariff in sorted(table.items()):
            if tariff_filter and tariff_id not in tariff_filter:
                continue
            land = tariff.land or ""
            areas: list[str | None] = [None]
            if direction == "import":
                areas += sorted(
                    area_id
                    for area_id, area in catalog.areas.items()
                    if (area.land or "") == land
                    and (not area_filter or area_id in area_filter)
                )
            cases.extend(Case(direction, tariff_id, tariff.type, land, area) for area in areas)
    return cases


# --- One case -----------------------------------------------------------------------


def earnie_prices(
    case: Case,
    slots: list[datetime],
    epex: list[float],
    tariffs_path: str,
    grid_fees_path: str,
) -> tuple[list[float], list[float] | None]:
    """Earnie's seams: final cent per slot and, for import with an area, the net grid fee."""
    from data.backtesting_prices import import_brutto_cent_for_slots
    from data.feed_in_prices import enrich_matrix_feed_in_prices, feed_in_settings_from_dict
    from data.grid_fees import grid_fee_work_cent, load_grid_fee_catalog, resolve_grid_fee_spec
    from house_config.tariffs_store import (
        load_tariffs_document,
        resolve_export_tariff_into_settings,
    )

    doc = load_tariffs_document(tariffs_path)
    if case.direction == "import":
        spec = doc["import_tariffs"][case.tariff_id]
        grid = None
        if case.area_id:
            grid = resolve_grid_fee_spec(
                _netznutzung(case.area_id),
                load_grid_fee_catalog(grid_fees_path),
                timezone_name=TIMEZONE,
            )
        cents = import_brutto_cent_for_slots(epex, slots, import_tariff_spec=spec, grid_fee=grid)
        grid_cents = [grid_fee_work_cent(grid, slot) for slot in slots] if grid else None
        return cents, grid_cents
    holder: dict = {}
    resolved = resolve_export_tariff_into_settings(
        {"export_tariff_id": case.tariff_id}, doc, monthly_rates_holder=holder
    )
    settings = feed_in_settings_from_dict(
        resolved, monthly_fixed_tariffs=holder.get("_monthly_fixed_tariffs")
    )
    matrix = [{"slot_datetime": slot, "price_buy": value} for slot, value in zip(slots, epex)]
    enrich_matrix_feed_in_prices(matrix, settings)
    return [float(row["k_push_act"]) for row in matrix], None


def edibert_points(
    case: Case,
    slots: list[datetime],
    epex: list[float],
    tariffs_path: str,
    grid_fees_path: str,
    warnings: list[str],
) -> list[Any]:
    """The Edibert adapter (same path as ``EARNIE_PRICING_ENGINE=edibert``)."""
    from data.edibert_slot_prices import price_points, pricing_reference

    profile: dict[str, Any] = {"land": case.land}
    if case.area_id:
        profile["netznutzung"] = _netznutzung(case.area_id)
    ref = pricing_reference(
        tariffs_path=tariffs_path,
        grid_fees_path=grid_fees_path,
        import_tariff_id=case.tariff_id if case.direction == "import" else None,
        export_tariff_id=case.tariff_id if case.direction == "export" else None,
        timezone_name=TIMEZONE,
        profile=profile,
    )
    return price_points(case.direction, slots, epex, ref, warnings_out=warnings)


def _sample(
    case: Case,
    slot: datetime,
    epex: float,
    earnie: float,
    point: Any,
    earnie_grid: float | None,
    tariffs_path: str,
    grid_fees_path: str,
) -> dict[str, Any]:
    """Intermediate steps of both engines for one deviating slot."""
    from house_config import edibert_tariffs as eb

    tariff = eb.tariff_by_id(eb.cached_tariff_set(tariffs_path), case.direction, case.tariff_id)
    ctx = eb.pricing_context_for_profile("parity", {"timezone_name": TIMEZONE, "land": case.land})
    grid_fee = None
    if case.area_id:
        grid_fee = eb.profile_grid_fee(
            "parity", {"netznutzung": _netznutzung(case.area_id)}, eb.cached_grid_fees(grid_fees_path)
        )
    result = eb.evaluate_slot(tariff, slot, ctx, epex_cent=epex, grid_fee=grid_fee)
    return {
        "slot": slot.isoformat(),
        "epex_cent": epex,
        "earnie_cent": earnie,
        "edibert_cent": point.cent,
        "earnie_grid_net_cent": earnie_grid,
        "edibert": {
            "supplier_cent": point.supplier_cent,
            "grid_cent": point.grid_cent,
            "vat_cent": point.vat_cent,
            "slot_without_hourly_mean": {
                "base_cent": result.base_cent,
                "rule_id": result.rule_id,
                "after_limits_cent": result.after_limits_cent,
                "grid_cent": result.grid_cent,
                "grid_rule_id": result.grid_rule_id,
                "cent": result.cent,
            },
        },
    }


def run_case(
    case: Case,
    *,
    start: date,
    end: date,
    tariffs_path: str,
    grid_fees_path: str,
    price_paths: dict[str, str],
    tolerance: float,
) -> CaseResult:
    from data.tariff_pricing import market_zone_for_land
    from house_config import edibert_tariffs as eb
    from house_config.edibert_tariffs import EdibertLoadError

    os.environ.pop("EARNIE_PRICING_ENGINE", None)  # Earnie side must run its own engine
    result = CaseResult(case)
    spot = case.tariff_type in {"spot_hourly", "ex_post_spot", "monthly_market"}
    tariff = eb.tariff_by_id(eb.cached_tariff_set(tariffs_path), case.direction, case.tariff_id)
    hourly_spot = tariff.is_spot and tariff.settlement_mtu == "60min"
    zone = market_zone_for_land(case.land) if case.land else None
    prices: dict[datetime, float] | None = None
    if zone in price_paths:
        prices = _load_prices(price_paths[zone])
    elif spot:
        result.skipped = f"keine Marktpreise für Zone {zone} (--prices {zone}=CSV)"
        return result
    for month in _month_starts(start, end):
        slots = _month_slots(month, start, end)
        if prices is None:
            epex = [0.0] * len(slots)  # tariff does not use the market price
        else:
            missing = [slot for slot in slots if slot.astimezone(UTC) not in prices]
            if missing:
                result.month_outcomes.append(
                    {"month": month.isoformat()[:7], "earnie": "skipped", "edibert": "skipped",
                     "reason": f"keine Marktpreise ab {missing[0].isoformat()}"}
                )
                continue
            epex = [prices[slot.astimezone(UTC)] for slot in slots]
        outcome: dict[str, Any] = {"month": month.isoformat()[:7]}
        earnie = earnie_grid = points = None
        try:
            earnie, earnie_grid = earnie_prices(case, slots, epex, tariffs_path, grid_fees_path)
            outcome["earnie"] = "ok"
        except ValueError as exc:
            outcome["earnie"] = f"error: {exc}"
        try:
            points = edibert_points(case, slots, epex, tariffs_path, grid_fees_path, result.warnings)
            outcome["edibert"] = "ok"
        except EdibertLoadError as exc:
            outcome["edibert"] = f"error {exc.code}: {exc}"
        if earnie is None or points is None:
            result.month_outcomes.append(outcome)
            continue
        result.months_compared += 1
        result.slots_compared += len(slots)
        for index, (slot, point) in enumerate(zip(slots, points)):
            diff = abs(point.cent - earnie[index])
            grid_diff = abs(point.grid_cent - earnie_grid[index]) if earnie_grid else 0.0
            result.max_diff_cent = max(result.max_diff_cent, diff)
            result.max_diff_grid = max(result.max_diff_grid, grid_diff)
            over = diff > tolerance
            over_grid = grid_diff > tolerance
            if over and not over_grid and hourly_spot and _repeated_hour(slot):
                result.triaged_t1 += 1
                continue
            result.over_tol_cent += over
            result.over_tol_grid += over_grid
            if (over or over_grid) and len(result.samples) < _MAX_SAMPLES:
                result.samples.append(
                    _sample(case, slot, epex[index], earnie[index], point,
                            earnie_grid[index] if earnie_grid else None,
                            tariffs_path, grid_fees_path)
                )
        result.month_outcomes.append(outcome)
    return result


# --- Committed parity fixture (CI, shared with Edibert 0.1.g) ------------------------

FIXTURE_CASES = (
    Case("import", "awattar_at", "spot_hourly", "AT", "AT-VBG"),  # net, hourly settled, SNAP
    Case("import", "at_verbund_v_strom_spot", "spot_hourly", "AT", "AT-WIEN"),  # net, 15 min
    Case("import", "at_verbund_v_strom_sterreich", "fixed_cent", "AT", "AT-VBG"),  # gross + grid
    Case("import", "at_vkw_strom_duo", "monthly_table", "AT", "AT-VBG"),  # month boundary
    Case("import", "at_tiwag_flex_privat", "spot_hourly", "AT", None),  # no grid fee
    Case("export", "dynamic_epex", "spot_hourly", "AT", None),  # hourly settled
    Case("export", "at_vkw_pv_dynamisch", "spot_hourly", "AT", None),
    Case("export", "at_oemag_gesetzlicher_marktpreis", "monthly_table", "AT", None),
    Case("export", "at_tiwag_tiwag_einspeisung_fix", "fixed", "AT", None),  # gross
)
# (name, first local hour, last local hour exclusive) — whole hours for hourly settlement.
FIXTURE_WINDOWS = (
    ("dst_spring_2026", datetime(2026, 3, 29, 0), datetime(2026, 3, 29, 4)),
    ("month_boundary_snap_start", datetime(2026, 3, 31, 22), datetime(2026, 4, 1, 12)),
    ("snap_day", datetime(2026, 7, 1, 9), datetime(2026, 7, 1, 17)),
    ("dst_autumn_2025", datetime(2025, 10, 26, 0), datetime(2025, 10, 26, 4)),
)


def _window_slots(first: datetime, last: datetime) -> list[datetime]:
    tz = ZoneInfo(TIMEZONE)
    cursor = first.replace(tzinfo=tz).astimezone(UTC)
    stop = last.replace(tzinfo=tz).astimezone(UTC)
    slots = []
    while cursor < stop:
        slots.append(cursor.astimezone(tz))
        cursor += _SLOT
    return slots


def _fixture_epex(count: int) -> list[float]:
    """Deterministic day-ahead pattern with negative prices and intra-hour spread."""
    import math

    return [round(6.0 + 9.0 * math.sin(index / 3.0) - (index % 4) * 0.37, 4) for index in range(count)]


def build_fixture(tariffs_path: str, grid_fees_path: str) -> dict[str, Any]:
    """Expected Earnie prices for :data:`FIXTURE_CASES` × :data:`FIXTURE_WINDOWS`."""
    windows = []
    for name, first, last in FIXTURE_WINDOWS:
        slots = _window_slots(first, last)
        epex = _fixture_epex(len(slots))
        expected = []
        for case in FIXTURE_CASES:
            cents, grid = earnie_prices(case, slots, epex, tariffs_path, grid_fees_path)
            expected.append({
                "direction": case.direction,
                "tariff_id": case.tariff_id,
                "land": case.land,
                "area_id": case.area_id,
                "cent": cents,
                "grid_net_cent": grid,
            })
        windows.append({
            "name": name,
            "slots": [slot.isoformat() for slot in slots],
            "epex_cent": epex,
            "expected": expected,
        })
    return {
        "comment": (
            "Edibert P3a parity fixture: Earnie's prices (engine before P3b) for the share/config "
            "catalog, netznutzung as Earnie writes it. Regenerate: python -m scripts.edibert_parity "
            "--write-fixture tests/fixtures/edibert_parity/expected_prices.json"
        ),
        "timezone": TIMEZONE,
        "windows": windows,
    }


def _repeated_hour(slot: datetime) -> bool:
    """Wall-clock time that exists twice (autumn DST change)."""
    return slot.replace(fold=1 - slot.fold).utcoffset() != slot.utcoffset()


def _one_sided(outcome: dict[str, Any]) -> bool:
    return (outcome.get("earnie") == "ok") != (outcome.get("edibert") == "ok")


def _run_case_job(payload: tuple[Case, dict[str, Any]]) -> dict[str, Any]:
    case, options = payload
    return run_case(case, **options).to_dict()


# --- Report -------------------------------------------------------------------------


def _markdown(report: dict[str, Any]) -> str:
    meta = report["meta"]
    lines = [
        "# Edibert P3a parity report",
        "",
        f"- Period: {meta['from']} → {meta['to']} (exclusive), time zone {TIMEZONE}",
        f"- Tolerance: {meta['tolerance']} ct per slot (final cent and net grid fee)",
        f"- Cases: {meta['cases']}, compared slots: {meta['slots_compared']}, "
        f"runtime {meta['seconds']:.0f} s with {meta['workers']} workers",
        f"- Price deviations above tolerance: **{meta['deviating_cases']} cases** "
        f"(untriaged); triaged T1 slots (autumn DST hour, hourly settled): {meta['triaged_t1_slots']}",
        f"- Months only one engine could price: {meta['one_sided_months']}; "
        f"months both engines refused: {meta['both_failed_months']}",
        "",
    ]
    deviating = [c for c in report["cases"] if c["over_tol_cent"] or c["over_tol_grid"]]
    if deviating:
        lines += ["## Deviations", "", "| Case | max Δ ct | slots > tol | max Δ grid | grid > tol |",
                  "| --- | --- | --- | --- | --- |"]
        for item in deviating:
            lines.append(
                f"| `{item['case']}` | {item['max_diff_cent']:.4f} | {item['over_tol_cent']} | "
                f"{item['max_diff_grid']:.4f} | {item['over_tol_grid']} |"
            )
        lines.append("")
    one_sided = [
        (item["case"], outcome)
        for item in report["cases"]
        for outcome in item["month_outcomes"]
        if _one_sided(outcome)
    ]
    if one_sided:
        lines += ["## Months priced by one engine only", "", "| Case | Month | Earnie | Edibert |",
                  "| --- | --- | --- | --- |"]
        for key, outcome in one_sided:
            earnie = str(outcome.get("earnie", "")).replace("|", "/")[:120]
            edibert = str(outcome.get("edibert", "")).replace("|", "/")[:120]
            lines.append(f"| `{key}` | {outcome['month']} | {earnie} | {edibert} |")
        lines.append("")
    skipped = [item for item in report["cases"] if item["skipped"]]
    if skipped:
        lines += ["## Skipped cases", ""]
        lines += [f"- `{item['case']}`: {item['skipped']}" for item in skipped]
        lines.append("")
    warned = [item for item in report["cases"] if item["warnings"]]
    if warned:
        lines += ["## Edibert warnings", ""]
        lines += [f"- `{item['case']}`: {', '.join(item['warnings'])}" for item in warned]
        lines.append("")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Edibert P3a parity harness (Earnie vs. Edibert).")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=date(2025, 1, 1))
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=date(2026, 10, 1))
    parser.add_argument("--tariffs-path", default=str(ROOT / "share" / "config" / "tariffs.json"))
    parser.add_argument("--grid-fees-path", default=str(ROOT / "share" / "config" / "grid_fees.json"))
    parser.add_argument("--prices", action="append", default=None, metavar="ZONE=CSV")
    parser.add_argument(
        "--fetch-prices",
        action="store_true",
        help="download missing zones from Energy-Charts (cached under --out)",
    )
    parser.add_argument("--tariffs", default="", help="comma-separated tariff IDs (default: all)")
    parser.add_argument("--areas", default="", help="comma-separated grid area IDs (default: all)")
    parser.add_argument("--tolerance", type=float, default=1e-4)
    parser.add_argument("--workers", type=int, default=os.cpu_count() or 1)
    parser.add_argument("--out", type=Path, default=ROOT / "runtime" / "edibert_parity")
    parser.add_argument("--site-config", action="store_true", help="keep the site config for Earnie")
    parser.add_argument("--write-fixture", type=Path, default=None, help="write the CI fixture and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.site_config:
        _use_fixture_config()
    os.environ.setdefault("EARNIE_OFFLINE", "1")
    os.environ.pop("EARNIE_PRICING_ENGINE", None)
    price_paths: dict[str, str] = {}
    for item in args.prices or []:
        zone, _, path = item.partition("=")
        if not path:
            raise SystemExit(f"--prices erwartet ZONE=CSV, nicht {item!r}.")
        price_paths[zone.strip()] = path.strip()
    tariffs_path = str(Path(args.tariffs_path).resolve())
    grid_fees_path = str(Path(args.grid_fees_path).resolve())
    if args.write_fixture is not None:
        fixture = build_fixture(tariffs_path, grid_fees_path)
        args.write_fixture.parent.mkdir(parents=True, exist_ok=True)
        args.write_fixture.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
        print(f"Fixture: {args.write_fixture}")
        return 0
    cases = build_cases(
        tariffs_path,
        grid_fees_path,
        tariff_filter={t for t in args.tariffs.split(",") if t} or None,
        area_filter={a for a in args.areas.split(",") if a} or None,
    )
    if args.fetch_prices:
        from data.tariff_pricing import market_zone_for_land

        for zone in sorted({market_zone_for_land(c.land) for c in cases if c.land} - set(price_paths)):
            price_paths[zone] = str(fetch_prices_csv(zone, args.start, args.end, args.out))
    options = {
        "start": args.start,
        "end": args.end,
        "tariffs_path": tariffs_path,
        "grid_fees_path": grid_fees_path,
        "price_paths": price_paths,
        "tolerance": args.tolerance,
    }
    began = time.monotonic()
    results: list[dict[str, Any]] = []
    workers = max(1, min(args.workers, len(cases)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_run_case_job, (case, options)) for case in cases]
        for done, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            print(f"\r{done}/{len(cases)} cases", end="", flush=True)
    print()
    results.sort(key=lambda item: item["case"])
    deviating = [r for r in results if r["over_tol_cent"] or r["over_tol_grid"]]
    report = {
        "meta": {
            "from": args.start.isoformat(),
            "to": args.end.isoformat(),
            "tolerance": args.tolerance,
            "tariffs_path": tariffs_path,
            "grid_fees_path": grid_fees_path,
            "prices": price_paths,
            "cases": len(results),
            "slots_compared": sum(r["slots_compared"] for r in results),
            "deviating_cases": len(deviating),
            "one_sided_months": sum(
                1 for r in results for o in r["month_outcomes"] if _one_sided(o)
            ),
            "both_failed_months": sum(
                1
                for r in results
                for o in r["month_outcomes"]
                if o.get("earnie") != "ok" and o.get("edibert") != "ok"
            ),
            "triaged_t1_slots": sum(r["triaged_t1"] for r in results),
            "workers": workers,
            "seconds": time.monotonic() - began,
        },
        "cases": results,
    }
    out_dir = args.out / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    print(f"Report: {out_dir / 'report.md'}")
    print(
        f"{len(results)} cases, {report['meta']['slots_compared']} slots, "
        f"{len(deviating)} deviating (untriaged), {report['meta']['triaged_t1_slots']} T1 slots, "
        f"{report['meta']['one_sided_months']} one-sided months"
    )
    return 1 if deviating else 0


if __name__ == "__main__":
    raise SystemExit(main())
