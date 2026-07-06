"""Fiktive Chart-1-Szenarien für Rauf/Runter-Energiebilanz (Tests, Seed, HTML-Vorschau)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from ui.chart_flow_balance import (
    KIND_BATTERY_CHARGE_GRID,
    KIND_BATTERY_CHARGE_PV,
    KIND_BATTERY_DISCHARGE_LOAD,
    KIND_BASELOAD,
    KIND_EXPORT_BATTERY,
    KIND_EXPORT_PV,
    KIND_FLEX,
    KIND_GRID_IMPORT,
    KIND_PV,
    build_flow_balance_segments,
)

_TZ = ZoneInfo("Europe/Vienna")
SCENARIO_START = datetime(2026, 7, 6, 8, 0, tzinfo=_TZ)

_FLEX_SWIMSPA_CONFIG = {
    "id": "swimspa",
    "name": "SwimSpa",
    "chart_color": "#c2185b",
    "optimizer_enabled": True,
}
_FLEX_SWIMSPA_COLUMN = "SwimSpa (kW)"


def flow_balance_flex_pairs() -> list[tuple[dict[str, Any], str]]:
    return [(_FLEX_SWIMSPA_CONFIG, _FLEX_SWIMSPA_COLUMN)]


def balanced_chart_row(
    *,
    pv: float,
    baseload: float,
    flex: float = 0.0,
    battery: float = 0.0,
) -> dict[str, float]:
    """Energiebilanz-konsistente Chart-Zeile (Netzbezug abgeleitet)."""
    netz = baseload + flex - pv + battery
    return {
        "PV-Prognose (kW)": pv,
        "Verbrauch-Prognose (kW)": baseload,
        _FLEX_SWIMSPA_COLUMN: flex,
        "Geplante Batterie-Aktion (kW)": battery,
        "Netzbezug (kW)": netz,
    }


@dataclass(frozen=True)
class FlowBalanceScenario:
    """Fiktives Chart-1-Szenario für Rauf/Runter-Balken."""

    scenario_id: str
    title: str
    row: dict[str, Any]
    offset_kw: float
    kinds_up: tuple[str, ...]
    kinds_down: tuple[str, ...]
    balanced: bool


def flow_balance_scenario_rows() -> tuple[FlowBalanceScenario, ...]:
    """Acht fiktive Slots — fünf Kernfälle plus Randvarianten."""
    return (
        FlowBalanceScenario(
            scenario_id="A",
            title="PV-Überschuss, Einspeisung, extern ausgeglichen",
            row=balanced_chart_row(pv=8, baseload=2, flex=1),
            offset_kw=5.0,
            kinds_up=(KIND_PV,),
            kinds_down=(KIND_BASELOAD, KIND_FLEX, KIND_EXPORT_PV),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="B",
            title="PV-Überschuss, Batterieladung, Rest eingespeist",
            row=balanced_chart_row(pv=10, baseload=2, battery=3),
            offset_kw=5.0,
            kinds_up=(KIND_PV,),
            kinds_down=(KIND_BASELOAD, KIND_BATTERY_CHARGE_PV, KIND_EXPORT_PV),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="C",
            title="Abend: Netzbezug + Batterie-Entladung (Ausgleich oben)",
            row=balanced_chart_row(pv=0, baseload=3, flex=2, battery=-4),
            offset_kw=-4.0,
            kinds_up=(KIND_GRID_IMPORT, KIND_BATTERY_DISCHARGE_LOAD),
            kinds_down=(KIND_BASELOAD, KIND_FLEX),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="D",
            title="Mittag: wenig PV, hoher Flex, Netz füllt Lücke",
            row=balanced_chart_row(pv=3, baseload=2, flex=4),
            offset_kw=0.0,
            kinds_up=(KIND_PV, KIND_GRID_IMPORT),
            kinds_down=(KIND_BASELOAD, KIND_FLEX),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="E",
            title="Überschuss-Ausgleich unten (keine Einspeisung in der Zeile)",
            row={
                "PV-Prognose (kW)": 7.0,
                "Verbrauch-Prognose (kW)": 2.0,
                _FLEX_SWIMSPA_COLUMN: 1.0,
                "Geplante Batterie-Aktion (kW)": 2.0,
                "Netzbezug (kW)": 0.0,
            },
            offset_kw=2.0,
            kinds_up=(KIND_PV,),
            kinds_down=(KIND_BASELOAD, KIND_FLEX, KIND_BATTERY_CHARGE_PV, KIND_EXPORT_PV),
            balanced=False,
        ),
        FlowBalanceScenario(
            scenario_id="F",
            title="Nacht: nur Grundlast und Netzbezug",
            row=balanced_chart_row(pv=0, baseload=1.5),
            offset_kw=0.0,
            kinds_up=(KIND_GRID_IMPORT,),
            kinds_down=(KIND_BASELOAD,),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="G",
            title="Bewölkt: PV + Netz + Batterieladung",
            row=balanced_chart_row(pv=2, baseload=2, battery=1.5),
            offset_kw=0.0,
            kinds_up=(KIND_PV, KIND_GRID_IMPORT),
            kinds_down=(KIND_BASELOAD, KIND_BATTERY_CHARGE_GRID),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="H",
            title="Leerer Slot (keine sichtbaren Segmente)",
            row=balanced_chart_row(pv=0, baseload=0, flex=0, battery=0),
            offset_kw=0.0,
            kinds_up=(),
            kinds_down=(),
            balanced=True,
        ),
        FlowBalanceScenario(
            scenario_id="I",
            title="Volle Batterie: PV-Überschuss nur Einspeisung (kein PV-Laden)",
            row={
                "PV-Prognose (kW)": 10.0,
                "Verbrauch-Prognose (kW)": 2.0,
                _FLEX_SWIMSPA_COLUMN: 0.0,
                "Geplante Batterie-Aktion (kW)": 3.0,
                "Netzbezug (kW)": -5.0,
                "Simulierter SoC (%)": 100.0,
            },
            offset_kw=8.0,
            kinds_up=(KIND_PV,),
            kinds_down=(KIND_BASELOAD, KIND_EXPORT_PV),
            balanced=False,
        ),
    )


def flow_balance_scenario_dataframe(
    *,
    start: datetime | None = None,
    step_hours: int = 1,
) -> pd.DataFrame:
    """DataFrame für Chart-1-Vorschau (Spalte ``scenario_id`` für Beschriftung)."""
    anchor = start or SCENARIO_START
    rows: list[dict[str, Any]] = []
    for index, scenario in enumerate(flow_balance_scenario_rows()):
        slot = anchor + timedelta(hours=index * step_hours)
        rows.append(
            {
                "scenario_id": scenario.scenario_id,
                "scenario_title": scenario.title,
                "slot_datetime": slot,
                "Uhrzeit": slot.strftime("%d.%m. %H:%M"),
                "Steuerbefehl": "IDLE",
                "Simulierter SoC (%)": 70.0,
                **scenario.row,
            }
        )
    return pd.DataFrame(rows)


def scenario_history_entry(scenario: FlowBalanceScenario) -> dict[str, Any]:
    """Produktiv-Log-Eintrag für ``optimization_history.jsonl``."""
    row = scenario.row
    pv = float(row["PV-Prognose (kW)"])
    baseload = float(row["Verbrauch-Prognose (kW)"])
    flex = float(row.get(_FLEX_SWIMSPA_COLUMN, 0.0) or 0.0)
    battery = float(row["Geplante Batterie-Aktion (kW)"])
    netz = float(row["Netzbezug (kW)"])
    consumer_powers = {"swimspa": flex} if flex > 0 else {}
    return {
        "source": "seed_flow_balance_test_log.py",
        "success": True,
        "optimization_interval_sec": 900,
        "soc_percent": float(scenario.row.get("Simulierter SoC (%)", 70.0) or 70.0),
        "market_price_cent": 12.0,
        "forecast_pv_kw": pv,
        "forecast_consumption_kw": baseload,
        "mode": 0,
        "target_power_kw": 0.0,
        "target_soc_percent": 85.0,
        "battery_plan_kw": battery,
        "consumer_powers_kw": consumer_powers,
        "flex_live_kw": {"swimspa": 0.0},
        "consumption_snapshot": {
            "pv_kw": pv,
            "baseload_kw": baseload,
            "flex_kw": {"swimspa": flex},
            "flex_sum_kw": flex,
            "house_kw": round(baseload + flex, 3),
            "grid_kw": netz,
            "battery_kw": round(-battery, 3),
        },
        "scenario": f"flow_balance_{scenario.scenario_id}",
        "scenario_title": scenario.title,
    }


def build_flow_balance_history_entries() -> list[dict[str, Any]]:
    return [scenario_history_entry(scenario) for scenario in flow_balance_scenario_rows()]


def validate_flow_balance_scenarios() -> list[dict[str, str]]:
    """Prüft Szenario-Metadaten gegen ``build_flow_balance_segments``."""
    flex = flow_balance_flex_pairs()
    report: list[dict[str, str]] = []
    for scenario in flow_balance_scenario_rows():
        slot = build_flow_balance_segments(scenario.row, flex_consumers=flex)
        if slot.offset_kw != scenario.offset_kw:
            raise ValueError(
                f"Szenario {scenario.scenario_id}: offset "
                f"{slot.offset_kw} != {scenario.offset_kw}"
            )
        if tuple(segment.kind for segment in slot.up) != scenario.kinds_up:
            raise ValueError(f"Szenario {scenario.scenario_id}: kinds_up abweichend")
        if tuple(segment.kind for segment in slot.down) != scenario.kinds_down:
            raise ValueError(f"Szenario {scenario.scenario_id}: kinds_down abweichend")
        if not slot.is_visually_balanced:
            raise ValueError(f"Szenario {scenario.scenario_id}: Up/Down-Säule ungleich")
        report.append(
            {
                "scenario_id": scenario.scenario_id,
                "title": scenario.title,
            }
        )
    return report
