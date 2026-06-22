# optimization_consistency.py
"""Interne Konsistenzprüfungen für 24h-Optimierungsläufe."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import config
from .battery import (
    MODE_AUTOMATIK,
    MODE_ENTLADESPERRE,
    MODE_ZWANGS_ENTLADEN,
    MODE_ZWANGS_LADEN,
    apply_soc_change as _apply_soc_change,
    battery_plan_kw_from_control,
)
from .simulation import (
    calculate_step_cost_euro_from_row as _calculate_step_cost_euro_from_row,
    delivered_flex_kwh_from_rows as _delivered_flex_kwh_from_rows,
    flexible_consumer_power_kw as _flexible_consumer_power_kw,
)
from .targets import resolve_horizon_consumer_targets_kwh
from simulation_engine import window_anchor_for_date, window_slot_datetimes

_GRID_TOLERANCE_KW = 0.03
_SOC_DISPLAY_TOLERANCE = 0.2
_CONSUMER_KWH_TOLERANCE = 0.55


@dataclass
class ConsistencyIssue:
    check: str
    hour_index: int | None
    message: str


@dataclass
class ConsistencyReport:
    anchor: datetime | None = None
    label: str = ""
    issues: list[ConsistencyIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, check: str, message: str, hour_index: int | None = None) -> None:
        self.issues.append(ConsistencyIssue(check=check, hour_index=hour_index, message=message))


def _parse_steuerbefehl(steuerbefehl: str) -> tuple[int, float]:
    text = str(steuerbefehl or "")
    if text.startswith("Zwangsladen"):
        start = text.find("(")
        end = text.find(" kW)", start)
        power = float(text[start + 1 : end]) if start >= 0 and end > start else 0.0
        return MODE_ZWANGS_LADEN, power
    if text.startswith("Zwangsentladen"):
        start = text.find("(")
        end = text.find(" kW)", start)
        power = float(text[start + 1 : end]) if start >= 0 and end > start else 0.0
        return MODE_ZWANGS_ENTLADEN, power
    if "Entladesperre" in text:
        return MODE_ENTLADESPERRE, 0.0
    return MODE_AUTOMATIK, 0.0


def _consumer_delivery_tolerance_kwh(consumer: dict, target_kwh: float) -> float:
    if target_kwh <= 0:
        return 0.05
    nominal = float(consumer.get("nominal_power_kw", 0.0) or 0.0)
    return max(_CONSUMER_KWH_TOLERANCE, nominal * 1.05)


def check_window_structure(matrix: list[dict], anchor: datetime) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    if len(matrix) != 24:
        issues.append(
            ConsistencyIssue(
                "window_length",
                None,
                f"Matrix hat {len(matrix)} statt 24 Stunden",
            )
        )
        return issues

    slots = window_slot_datetimes(anchor)
    if len(slots) != 24:
        issues.append(
            ConsistencyIssue("window_slots", None, f"Erwartete 24 Slot-Zeiten, erhalten {len(slots)}")
        )
        return issues

    for index, (row, slot_dt) in enumerate(zip(matrix, slots)):
        row_slot = row.get("slot_datetime")
        if row_slot != slot_dt:
            issues.append(
                ConsistencyIssue(
                    "window_slots",
                    index,
                    f"Slot {index}: {row_slot!r} != {slot_dt!r}",
                )
            )
        row_anchor = row.get("charging_anchor")
        if row_anchor != anchor:
            issues.append(
                ConsistencyIssue(
                    "charging_anchor",
                    index,
                    f"charging_anchor {row_anchor!r} != Fensterende {anchor!r}",
                )
            )

    expected_ready = window_anchor_for_date(anchor.date())
    if anchor != expected_ready:
        issues.append(
            ConsistencyIssue(
                "ready_by_hour",
                None,
                f"Fensterende {anchor} weicht von ready_by_hour-Anker {expected_ready} ab",
            )
        )

    last_slot = slots[-1]
    if last_slot + timedelta(hours=1) != anchor:
        issues.append(
            ConsistencyIssue(
                "ready_by_hour",
                23,
                f"Letzte Stunde {last_slot} + 1h != Anker {anchor}",
            )
        )
    return issues


def check_energy_balance(rows: list[dict]) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    for index, row in enumerate(rows):
        if "Netzbezug (kW)" not in row:
            issues.append(
                ConsistencyIssue("energy_balance", index, "Spalte Netzbezug (kW) fehlt")
            )
            continue
        pv = float(row["PV-Prognose (kW)"])
        con = float(row["Verbrauch-Prognose (kW)"])
        flex = _flexible_consumer_power_kw(row)
        batt = float(row["Geplante Batterie-Aktion (kW)"])
        grid = float(row["Netzbezug (kW)"])
        calc_grid = con + flex - pv + batt
        if round(calc_grid, 2) != round(grid, 2):
            issues.append(
                ConsistencyIssue(
                    "energy_balance",
                    index,
                    f"Netzbezug {grid:.3f} kW, berechnet {calc_grid:.3f} kW "
                    f"(Δ {grid - calc_grid:+.3f})",
                )
            )
    return issues


def check_soc_chain(
    rows: list[dict],
    initial_soc: float,
    battery_params: dict,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    soc = float(initial_soc)
    for index, row in enumerate(rows):
        displayed = float(row["Simulierter SoC (%)"])
        if abs(displayed - soc) > _SOC_DISPLAY_TOLERANCE:
            issues.append(
                ConsistencyIssue(
                    "soc_chain",
                    index,
                    f"Angezeigter SoC {displayed:.1f} %, erwartet {soc:.1f} %",
                )
            )
        batt = float(row["Geplante Batterie-Aktion (kW)"])
        soc, _ = _apply_soc_change(
            displayed,
            batt,
            battery_params["battery_capacity_kwh"],
            battery_params["efficiency"],
            battery_params["min_soc"],
            battery_params["max_soc"],
        )
    return issues


def check_mode_battery_alignment(
    rows: list[dict],
    battery_params: dict,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    max_power = float(battery_params["max_power_kw"])
    for index, row in enumerate(rows):
        mode, target_power = _parse_steuerbefehl(row.get("Steuerbefehl", ""))
        pv = float(row["PV-Prognose (kW)"])
        con = float(row["Verbrauch-Prognose (kW)"])
        flex = _flexible_consumer_power_kw(row)
        expected = battery_plan_kw_from_control(
            mode, target_power, pv, con, flex, max_power
        )
        actual = float(row["Geplante Batterie-Aktion (kW)"])
        old_soc = float(row["Simulierter SoC (%)"])
        _, expected_after_limits = _apply_soc_change(
            old_soc,
            expected,
            battery_params["battery_capacity_kwh"],
            battery_params["efficiency"],
            battery_params["min_soc"],
            battery_params["max_soc"],
        )
        if abs(actual - expected_after_limits) > _GRID_TOLERANCE_KW:
            issues.append(
                ConsistencyIssue(
                    "mode_battery",
                    index,
                    f"{row.get('Steuerbefehl')}: Batterie {actual:.3f} kW, "
                    f"aus Modus erwartet {expected_after_limits:.3f} kW",
                )
            )
    return issues


def check_consumer_targets(
    rows: list[dict],
    matrix: list[dict],
    consumer_daily_targets_kwh: dict[str, float] | None,
) -> list[ConsistencyIssue]:
    issues: list[ConsistencyIssue] = []
    targets = resolve_horizon_consumer_targets_kwh(matrix, consumer_daily_targets_kwh)
    delivered = _delivered_flex_kwh_from_rows(rows)
    for consumer in config.get_flexible_consumers(optimizer_only=True):
        cid = consumer["id"]
        target = float(targets.get(cid, 0.0))
        actual = float(delivered.get(cid, 0.0))
        tolerance = _consumer_delivery_tolerance_kwh(consumer, target)
        if target <= 0:
            if actual > tolerance:
                issues.append(
                    ConsistencyIssue(
                        "consumer_targets",
                        None,
                        f"{consumer['name']}: {actual:.2f} kWh geliefert, Ziel 0 kWh",
                    )
                )
            continue
        if actual + tolerance < target:
            issues.append(
                ConsistencyIssue(
                    "consumer_targets",
                    None,
                    f"{consumer['name']}: {actual:.2f} kWh geliefert, Ziel {target:.2f} kWh "
                    f"(Defizit {target - actual:.2f} kWh)",
                )
            )
        if actual - target > tolerance:
            issues.append(
                ConsistencyIssue(
                    "consumer_targets",
                    None,
                    f"{consumer['name']}: {actual:.2f} kWh geliefert, Ziel {target:.2f} kWh "
                    f"(Überschuss {actual - target:.2f} kWh)",
                )
            )
    return issues


def check_cost_recompute(rows: list[dict], sell_price_cent: float) -> list[ConsistencyIssue]:
    """Prüft, dass die Kostenfunktion mit dem gespeicherten Netzbezug übereinstimmt."""
    issues: list[ConsistencyIssue] = []
    for index, row in enumerate(rows):
        grid = float(row.get("Netzbezug (kW)", 0.0) or 0.0)
        price = float(row["Strompreis (Cent/kWh)"])
        if grid >= 0:
            expected = grid * price / 100.0
        else:
            expected = grid * sell_price_cent / 100.0
        actual = _calculate_step_cost_euro_from_row(row, sell_price_cent)
        if abs(actual - expected) > 1e-6:
            issues.append(
                ConsistencyIssue(
                    "cost_formula",
                    index,
                    f"Kosten {actual:.6f} € weicht von Netzbezug×Preis {expected:.6f} € ab",
                )
            )
    return issues


def validate_24h_optimization_run(
    matrix: list[dict],
    rows: list[dict],
    *,
    anchor: datetime,
    initial_soc: float,
    battery_params: dict,
    consumer_daily_targets_kwh: dict[str, float] | None,
    sell_price_cent: float,
    label: str = "",
) -> ConsistencyReport:
    """Führt alle internen Konsistenzprüfungen für einen 24h-Lauf aus."""
    report = ConsistencyReport(anchor=anchor, label=label)
    for issue in check_window_structure(matrix, anchor):
        report.add(issue.check, issue.message, issue.hour_index)
    if len(rows) != 24:
        report.add("result_length", f"Ergebnis hat {len(rows)} statt 24 Zeilen")
        return report
    for checker in (
        check_energy_balance,
        lambda r: check_soc_chain(r, initial_soc, battery_params),
        lambda r: check_mode_battery_alignment(r, battery_params),
        lambda r: check_consumer_targets(r, matrix, consumer_daily_targets_kwh),
        lambda r: check_cost_recompute(r, sell_price_cent),
    ):
        for issue in checker(rows):
            report.add(issue.check, issue.message, issue.hour_index)
    return report


def assert_24h_optimization_consistent(report: ConsistencyReport) -> None:
    """Hebt bei Inkonsistenzen AssertionError mit gesammelter Meldung aus."""
    if report.ok:
        return
    header = report.label or (report.anchor.isoformat() if report.anchor else "24h-Lauf")
    lines = [f"Konsistenzfehler ({header}):"]
    for issue in report.issues:
        hour = f" Stunde {issue.hour_index}" if issue.hour_index is not None else ""
        lines.append(f"  - [{issue.check}]{hour}: {issue.message}")
    raise AssertionError("\n".join(lines))
