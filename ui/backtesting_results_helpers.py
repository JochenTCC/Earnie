"""Hilfsfunktionen für Backtesting-Ergebnisanzeige (Perioden, Kostentabelle)."""
from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

import config
from scripts.run_backtesting import BACKTESTING_YEAR
from simulation.engine import (
    CONSUMPTION_TOLERANCE_REL,
    HISTORICAL_REFERENCE_ID,
    is_scenario_reference_id,
    scenario_reference_id,
)
from optimizer.slot_duration import DEFAULT_DT_H
from simulation.booked_consumption import BOOKED_CONSUMPTION_KEY
from simulation.capacity_charge import CAPACITY_KEY
from simulation.reference_costs import LADDER_L2
from simulation.jahres_verbrauch import jahres_standby_kwh, jahres_verbrauch_kwh
from ui.consumption_validation_charts import cons_data_monthly_kwh
from ui.number_format import format_decimal, format_euro
from ui.saving_text import saving_text, soc_correction_text

_DASH = "—"
_TIMING_SHIFT_NOTE = "Zeitliche Lastverschiebung (Energie ≈ Spec)"
_CONSUMPTION_DEVIATION_HINT = (
    "Verbrauch weicht >5% von Live-Referenz ab — mögliche Simulationsprobleme. "
    "Bitte Config-Dump über Info / About → Kontakt an TechCreaCon senden."
)


def is_single_month_test_run(period: dict) -> bool:
    start_month = period.get("start_month")
    end_month = period.get("end_month")
    if start_month is None or end_month is None:
        return False
    return int(start_month) == int(end_month)


def format_test_run_caption(period: dict) -> str | None:
    if not is_single_month_test_run(period):
        return None
    month = int(period["start_month"])
    year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
    return f"Testlauf — nur Monat {month:02d}/{year}"


def nav_bounds_from_period(period: dict) -> tuple[datetime, datetime] | None:
    start_raw = period.get("start")
    end_raw = period.get("end")
    if not start_raw or not end_raw:
        return None
    start = datetime.combine(date.fromisoformat(str(start_raw)), time.min)
    end = datetime.combine(date.fromisoformat(str(end_raw)), time(23, 59, 59))
    return start, end


def slice_cons_data_for_period(
    cons_df: pd.DataFrame,
    period: dict,
) -> pd.DataFrame:
    bounds = nav_bounds_from_period(period)
    if bounds is None or cons_df.empty:
        return cons_df
    start, end = bounds
    mask = (cons_df.index >= start) & (cons_df.index <= end)
    return cons_df.loc[mask]


def reference_consumption_subheader(period: dict) -> str:
    if is_single_month_test_run(period):
        month = int(period["start_month"])
        year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
        return f"Referenz-Verbrauch (Testmonat {month:02d}/{year}, nicht optimiert)"
    return "Referenz-Jahresverbrauch (nicht optimiert)"


def _flex_kw_columns(cons_df: pd.DataFrame) -> list[str]:
    from settings.flexible_consumers import runtime_consumer_id
    from ui.chart_consumer_stack import _chart_flex_consumers

    configured = [f"{runtime_consumer_id(c)}_kw" for c in _chart_flex_consumers(optimizer_only=False)]
    if configured:
        matched = [col for col in configured if col in cons_df.columns]
        if matched:
            return matched
    from data.cons_data_house_profile import expected_cons_data_consumer_ids

    expected = [f"{cid}_kw" for cid in expected_cons_data_consumer_ids()]
    if expected:
        return [col for col in expected if col in cons_df.columns]
    skip = {"total", "baseload", "pv"}
    return [
        col
        for col in cons_df.columns
        if col.endswith("_kw") and col[: -len("_kw")] not in skip
    ]


def cons_data_has_flex_energy(cons_df: pd.DataFrame) -> bool:
    """False wenn Verbraucher-Spalten fehlen oder überall 0 sind."""
    flex_cols = _flex_kw_columns(cons_df)
    if not flex_cols:
        return False
    return float(cons_df[flex_cols].sum().sum()) > 0.0


def reference_kwh_for_period(cons_df: pd.DataFrame, period: dict) -> float | None:
    sliced = slice_cons_data_for_period(cons_df, period)
    if sliced.empty:
        return None
    monthly = cons_data_monthly_kwh(sliced)
    return round(sum(monthly.values()), 1)


def scenario_consumption_subheader(period: dict) -> str:
    if is_single_month_test_run(period):
        month = int(period["start_month"])
        year = int(period.get("backtesting_year") or BACKTESTING_YEAR)
        return f"Verbrauchsvergleich (Debug, Testmonat {month:02d}/{year})"
    return "Verbrauchsvergleich (Debug)"


def _format_kwh(value: float | None) -> str:
    if value is None:
        return _DASH
    return format_decimal(value, 1)


def _format_delta_kwh(value: float | None) -> str:
    if value is None:
        return _DASH
    return format_decimal(value, 1, signed=True)


def _format_plausibility_cell(block: dict | None) -> str:
    if not block:
        return _DASH
    ok = block.get("ok_count")
    total = block.get("total_windows")
    if ok is None or total is None:
        return _DASH
    return f"{ok}/{total} OK"


def _timing_shift_note(
    scenario_id: str,
    totals: dict,
    labels: dict[str, str],
    *,
    hourly_df,
    scenarios: dict | None,
    timestamps: list[str] | None,
) -> str:
    delta = totals.get("delta_kwh")
    if delta is None or hourly_df is None or not scenarios or not timestamps:
        return _DASH
    from ui.backtesting_scenario_consumption import (
        build_baseline_optimized_overlay,
        detect_period_timing_shift,
    )

    overlay = build_baseline_optimized_overlay(
        scenarios,
        labels,
        scenario_id,
        timestamps,
        hourly_df,
    )
    if overlay is None:
        return _DASH
    if detect_period_timing_shift(overlay.baseline_kw, overlay.optimized_kw):
        return _TIMING_SHIFT_NOTE
    return _DASH


def exceeds_live_reference_rel(
    optimized_kwh: float | None,
    live_ref_kwh: float | None,
    *,
    threshold: float = CONSUMPTION_TOLERANCE_REL,
) -> bool:
    """True when |value − Live-Referenz| / |Live-Referenz| exceeds threshold."""
    if optimized_kwh is None or live_ref_kwh is None:
        return False
    base = abs(float(live_ref_kwh))
    if base <= 0.0:
        return abs(float(optimized_kwh)) > 0.0
    return abs(float(optimized_kwh) - float(live_ref_kwh)) / base > threshold


def _booked(meta: dict) -> dict:
    return meta.get(BOOKED_CONSUMPTION_KEY) or {}


def _live_reference_id(meta: dict) -> str | None:
    """Result id of the Live scenario's reference series."""
    live_id = _resolve_live_scenario_id(meta)
    if not live_id:
        return None
    return (meta.get("reference_by_scenario") or {}).get(live_id)


def _live_reference_kwh(meta: dict) -> float | None:
    """Booked consumption of the Live scenario's reference series."""
    ref_id = _live_reference_id(meta)
    if not ref_id:
        return None
    return jahres_verbrauch_kwh(ref_id, booked_consumption=_booked(meta))


def _consumption_vs_live_reference(
    meta: dict,
    scenario_id: str,
    kwh_value: float | None,
) -> float | None:
    """Consumption of a scenario to compare with the Live reference; None = not comparable.

    Another heating system than the Live reference (heat pump ↔ gas) changes the
    electricity on purpose, so there is nothing to compare. The heating rod's electricity
    replaces heat, so it comes off before the comparison. Both come from the ``heat_fuel``
    block of each result; logs without it compare the plain consumption.
    """
    if kwh_value is None:
        return None
    heat_fuel = meta.get("heat_fuel") or {}
    block = heat_fuel.get(scenario_id) or {}
    reference_block = heat_fuel.get(_live_reference_id(meta)) or {}
    if block.get("heating_systems") != reference_block.get("heating_systems"):
        return None
    return float(kwh_value) - float(block.get("rod_kwh") or 0.0)


def build_scenario_consumption_rows(
    meta: dict,
    *,
    hourly_df=None,
    scenarios: dict | None = None,
    timestamps: list[str] | None = None,
) -> list[dict]:
    """Soll / MILP-Plan / gebuchte kWh je optimiertem Szenario (Debug).

    ``Optimiert`` and both reference columns are booked series totals
    (``booked_consumption``); ``Soll`` and ``Geplant`` come from the window
    plausibility sums, so planned → booked losses are visible.
    """
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    plausibility = meta.get("plausibility", {})
    booked = _booked(meta)
    historical_kwh = jahres_verbrauch_kwh(ref_id, booked_consumption=booked)
    live_ref_kwh = _live_reference_kwh(meta)

    rows: list[dict] = []
    for scenario_id in meta.get("scenario_ids", []):
        if scenario_id == ref_id or is_scenario_reference_id(scenario_id):
            continue
        label = labels.get(scenario_id, scenario_id)
        block = plausibility.get(scenario_id)
        totals = (block or {}).get("consumption_totals") or {}
        booked_kwh = jahres_verbrauch_kwh(scenario_id, booked_consumption=booked)
        delta = None
        if booked_kwh is not None and live_ref_kwh is not None:
            delta = round(booked_kwh - float(live_ref_kwh), 1)

        rows.append(
            {
                "Szenario": label,
                "Ohne PV und Speicher [kWh]": _format_kwh(historical_kwh),
                "Reference (Live) - ohne Optimierung [kWh]": _format_kwh(live_ref_kwh),
                "Soll Fenster [kWh]": _format_kwh(totals.get("historical_kwh")),
                "Geplant MILP [kWh]": _format_kwh(totals.get("optimized_kwh")),
                "Optimiert (kWh)": _format_kwh(booked_kwh),
                "Δ kWh (Ref. ohne Optimierung)": _format_delta_kwh(delta),
                "Hinweis": _timing_shift_note(
                    scenario_id,
                    totals,
                    labels,
                    hourly_df=hourly_df,
                    scenarios=scenarios,
                    timestamps=timestamps,
                ),
                "Plausibilität": _format_plausibility_cell(block),
            }
        )
    return rows


def _resolve_live_scenario_id(meta: dict) -> str | None:
    live_id = meta.get("live_scenario_id")
    if live_id:
        return str(live_id)
    try:
        return str(config.get_live_scenario_id())
    except Exception:
        return None


def _live_reference_total_eur(meta: dict, totals: dict[str, float]) -> float | None:
    """€ total of the Live scenario reference row (Referenz Live)."""
    live_id = _resolve_live_scenario_id(meta)
    if not live_id:
        return None
    live_ref = scenario_reference_id(live_id)
    if live_ref not in totals:
        return None
    return float(totals[live_ref])


def _annual_cost_row_order(meta: dict, totals: dict[str, float]) -> list[str]:
    """Historical → Live ref → other refs → Live optimized → other optimized."""
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    scenario_ids = list(meta.get("scenario_ids", []))
    ordered_ids = list(
        dict.fromkeys(scenario_ids + [sid for sid in totals if sid not in scenario_ids])
    )

    live_id = _resolve_live_scenario_id(meta)
    live_ref = scenario_reference_id(live_id) if live_id else None

    global_refs: list[str] = []
    scenario_refs: list[str] = []
    optimized: list[str] = []
    for scenario_id in ordered_ids:
        if scenario_id not in totals:
            continue
        if scenario_id == ref_id:
            global_refs.append(scenario_id)
        elif is_scenario_reference_id(scenario_id):
            scenario_refs.append(scenario_id)
        else:
            optimized.append(scenario_id)

    if live_ref and live_ref in scenario_refs:
        scenario_refs = [live_ref] + [r for r in scenario_refs if r != live_ref]
    if live_id and live_id in optimized:
        optimized = [live_id] + [s for s in optimized if s != live_id]
    return global_refs + scenario_refs + optimized


def ordered_monthly_chart_labels(meta: dict, present_labels: list[str]) -> list[str]:
    """Same scenario order as Gesamtkosten: historical → scenario refs → optimized."""
    labels = meta.get("labels", {})
    totals = meta.get("summary", {}).get("total_eur", {})
    present = set(present_labels)
    ordered: list[str] = []
    for scenario_id in _annual_cost_row_order(meta, totals):
        label = labels.get(scenario_id, scenario_id)
        if label in present and label not in ordered:
            ordered.append(label)
    for label in present_labels:
        if label not in ordered:
            ordered.append(label)
    return ordered


def _is_live_reference_row(scenario_id: str, live_id: str | None) -> bool:
    if not live_id:
        return False
    return scenario_id == scenario_reference_id(live_id)


def _slot_hours(slots: int) -> str:
    return f"{slots * float(DEFAULT_DT_H):.0f} h"


def _booked_series_hints(scenario_id: str, booked: dict) -> list[str]:
    """Duplicate / missing slots in the series and slot-set differences to its reference."""
    block = booked.get(scenario_id) or {}
    hints: list[str] = []
    duplicates = int(block.get("duplicate_slots") or 0)
    if duplicates:
        hints.append(f"{_slot_hours(duplicates)} doppelt gebucht (einmal gezählt)")
    gaps = int(block.get("gap_slots") or 0)
    if gaps:
        hints.append(f"{_slot_hours(gaps)} ohne Buchung (Lücken in der Reihe)")
    coverage = block.get("reference_coverage") or {}
    only_here = int(coverage.get("only_scenario_slots") or 0)
    only_ref = int(coverage.get("only_reference_slots") or 0)
    if only_here or only_ref:
        hints.append(
            "Referenz rechnet über andere Zeitslots "
            f"({_slot_hours(only_here)} nur hier, {_slot_hours(only_ref)} nur in der Referenz)"
        )
    return hints


def _ladder_report_hints(report: dict | None) -> list[str]:
    """What an L1 / L2 run reports about its own quality."""
    if not report:
        return []
    hints: list[str] = []
    failed = int(report.get("plausibility_failed_windows") or 0)
    if failed:
        hints.append(f"{failed} Fenster mit abweichender Energie, Vergleich unsicher")
    for key, text in (
        ("no_shape_windows", "ohne Lastprofil, läuft ab Fensterbeginn mit Nennleistung"),
        ("no_published_block_windows", "ohne veröffentlichte Preise, behält seine Startzeit"),
    ):
        windows = report.get(key) or {}
        if windows:
            parts = ", ".join(f"{cid}: {count} Fenster" for cid, count in sorted(windows.items()))
            hints.append(f"{parts} {text}")
    truncated = int(report.get("truncated_lock_slots") or 0)
    if truncated:
        hints.append(f"{_slot_hours(truncated)} Preissperre mit kürzerem Horizont (Preisdaten enden)")
    return hints


def _soc_correction_block(meta: dict, scenario_id: str) -> dict | None:
    return (meta.get("ladder_soc_correction") or {}).get(scenario_id)


def _standard_rules_saving_cell(meta: dict, scenario_id: str, totals: dict) -> str:
    """L2 − L3 of a scenario with the end-SoC term; logs without a ladder have no value."""
    steps = (meta.get("ladder_by_scenario") or {}).get(scenario_id)
    if not steps:
        return _DASH
    saving = float(totals[steps[LADDER_L2]]) - float(totals[scenario_id])
    block = _soc_correction_block(meta, scenario_id)
    if block:
        saving += float(block["steps"][LADDER_L2]["correction_eur"])
    return saving_text(saving)


def _soc_correction_hint(meta: dict, scenario_id: str) -> list[str]:
    """How the saving column values the SoC at the end of the period."""
    if scenario_id not in (meta.get("ladder_by_scenario") or {}):
        return []
    block = _soc_correction_block(meta, scenario_id)
    if not block:
        return ["SoC am Periodenende nicht bewertet (Log vor dieser Auswertung)"]
    step = block["steps"][LADDER_L2]
    if round(float(step["correction_eur"]), 2) == 0.0:
        return []
    return [
        f"Ersparnis mit SoC am Periodenende: {soc_correction_text(step['correction_eur'])} "
        f"({block['soc_end_percent']:.0f} % gegen {step['soc_end_percent']:.0f} %)"
    ]


def _annual_cost_hinweis(
    scenario_id: str,
    *,
    live_id: str | None,
    ref_id: str,
    compare_kwh: float | None,
    live_ref_kwh: float | None,
    booked: dict,
    ladder_report: dict | None = None,
    soc_hint: list[str] | None = None,
) -> str:
    hints = (
        _booked_series_hints(scenario_id, booked)
        + _ladder_report_hints(ladder_report)
        + (soc_hint or [])
    )
    # Live-Referenz and Historisch (Ist-Zähler) are baselines, not optimized runs.
    # Historisch vs model Live-ref often differs when meter ≠ Hausprofil — not a sim bug.
    is_baseline = _is_live_reference_row(scenario_id, live_id) or scenario_id == ref_id
    if not is_baseline and exceeds_live_reference_rel(compare_kwh, live_ref_kwh):
        hints.append(_CONSUMPTION_DEVIATION_HINT)
    return " · ".join(hints) if hints else _DASH


def _heat_fuel_cells(meta: dict, scenario_id: str, *, show_fuel: bool) -> dict:
    """Brennstoff / CO2 cells (SUSI P1); empty when the log has no ``heat_fuel`` block."""
    block = (meta.get("heat_fuel") or {}).get(scenario_id)
    if not meta.get("heat_fuel"):
        return {}
    cells: dict = {}
    if show_fuel:
        fuel_kwh = float((block or {}).get("fuel_kwh") or 0.0)
        cells["Brennstoff [kWh]"] = _format_kwh(fuel_kwh) if fuel_kwh else _DASH
        cells["Brennstoffkosten [€]"] = (
            format_euro(float(block["fuel_eur"])) if fuel_kwh else _DASH
        )
    cells["CO2 [kg]"] = f"{float(block['co2_kg']):.0f}" if block else _DASH
    return cells


def _totals_with_fuel(meta: dict, totals: dict) -> dict:
    """Jahres Kosten = Strom (``summary.total_eur``) + Brennstoff (``heat_fuel``)."""
    fuel = meta.get("heat_fuel") or {}
    return {
        sid: float(total) + float((fuel.get(sid) or {}).get("fuel_eur") or 0.0)
        for sid, total in totals.items()
    }


def build_capacity_rows(meta: dict) -> list[dict]:
    """One row per result with a capacity charge: highest month peak and the sum over the period."""
    capacity = meta.get(CAPACITY_KEY) or {}
    labels = meta.get("labels", {})
    totals = meta.get("summary", {}).get("total_eur", {})
    rows: list[dict] = []
    for scenario_id in _annual_cost_row_order(meta, totals):
        months = (capacity.get(scenario_id) or {}).get("months") or []
        if not months:
            continue
        highest = max(months, key=lambda month: float(month["peak_kw"]))
        rows.append(
            {
                "Szenario": labels.get(scenario_id, scenario_id),
                "Höchste Monatsspitze [kW]": format_decimal(float(highest["peak_kw"])),
                "Monat": highest["month"],
                "Ø abgerechnet [kW]": format_decimal(
                    sum(float(month["billed_kw"]) for month in months) / len(months)
                ),
                "Leistungspreis [€]": format_euro(
                    sum(float(month["gross_eur"]) for month in months)
                ),
            }
        )
    return rows


def capacity_skipped_text(meta: dict) -> str | None:
    """Entries left out by status, for the notice under the table; ``None`` without any."""
    skipped: dict[str, str] = {}
    for block in (meta.get(CAPACITY_KEY) or {}).values():
        skipped.update(block.get("skipped") or {})
    if not skipped:
        return None
    return ", ".join(f"{cid} (Status {status})" for cid, status in sorted(skipped.items()))


def build_annual_cost_rows(meta: dict) -> list[dict]:
    """Gesamtkosten rows; Jahres Verbrauch / Standby from the booked series of every row."""
    summary = meta.get("summary", {})
    totals = _totals_with_fuel(meta, summary.get("total_eur", {}))
    show_fuel = any(
        float((block or {}).get("fuel_kwh") or 0.0) > 0.0
        for block in (meta.get("heat_fuel") or {}).values()
    )
    labels = meta.get("labels", {})
    ref_id = meta.get("reference_id", HISTORICAL_REFERENCE_ID)
    booked = _booked(meta)
    live_ref_total = _live_reference_total_eur(meta, totals)
    live_id = _resolve_live_scenario_id(meta)
    live_ref_kwh = _live_reference_kwh(meta)

    rows: list[dict] = []
    for scenario_id in _annual_cost_row_order(meta, totals):
        total_eur = totals[scenario_id]
        label = labels.get(scenario_id, scenario_id)
        kwh_value = jahres_verbrauch_kwh(scenario_id, booked_consumption=booked)
        kwh_cell = _format_kwh(kwh_value)
        standby = jahres_standby_kwh(scenario_id, booked_consumption=booked)
        standby_cell = _format_kwh(standby) if standby else _DASH
        total_cell = (
            _format_kwh(kwh_value + (standby or 0.0)) if kwh_value is not None else _DASH
        )
        hinweis = _annual_cost_hinweis(
            scenario_id,
            live_id=live_id,
            ref_id=ref_id,
            compare_kwh=_consumption_vs_live_reference(meta, scenario_id, kwh_value),
            live_ref_kwh=live_ref_kwh,
            booked=booked,
            ladder_report=(meta.get("ladder_report") or {}).get(scenario_id),
            soc_hint=_soc_correction_hint(meta, scenario_id),
        )
        is_reference = scenario_id == ref_id or is_scenario_reference_id(scenario_id)
        if is_reference:
            rows.append(
                {
                    "Szenario": label,
                    "Jahres Verbrauch [kWh]": kwh_cell,
                    "Speicher-Standby [kWh]": standby_cell,
                    "Gesamtverbrauch [kWh]": total_cell,
                    **_heat_fuel_cells(meta, scenario_id, show_fuel=show_fuel),
                    "Jahres Kosten [€]": format_euro(total_eur),
                    "Ersparnis vs. Standard-Regeln [€]": _DASH,
                    "Δ vs Referenz [€]": _DASH,
                    "Hinweis": hinweis,
                }
            )
            continue

        delta_cell = _DASH
        if live_ref_total is not None:
            delta_cell = format_euro(total_eur - live_ref_total, signed=True)
        rows.append(
            {
                "Szenario": label,
                "Jahres Verbrauch [kWh]": kwh_cell,
                "Speicher-Standby [kWh]": standby_cell,
                "Gesamtverbrauch [kWh]": total_cell,
                **_heat_fuel_cells(meta, scenario_id, show_fuel=show_fuel),
                "Jahres Kosten [€]": format_euro(total_eur),
                "Ersparnis vs. Standard-Regeln [€]": _standard_rules_saving_cell(
                    meta, scenario_id, totals
                ),
                "Δ vs Referenz [€]": delta_cell,
                "Hinweis": hinweis,
            }
        )
    return rows
