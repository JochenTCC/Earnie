"""Integration: Abweichungen entlang Chart-Historie und Display-Kontext (Soll-Ist P2)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer import battery as bat
from runtime_store import history_timeline, optimization_history
from ui.chart_context import SLOT_MILP, build_chart_display_context, build_live_chart_context

RULES_PATH = Path("config") / "deviation_rules.example.json"
TZ = ZoneInfo("Europe/Vienna")
NOW = datetime(2026, 7, 5, 10, 7, 30, tzinfo=TZ)


def _write_jsonl(path, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def _entry(completed: datetime, **extra) -> dict:
    base = {
        "completed_at": completed.isoformat(timespec="seconds"),
        "source": "main.py",
        "success": True,
        "soc_percent": 50.0,
        "mode": bat.MODE_AUTOMATIK,
        "target_power_kw": 0.0,
        "battery_plan_kw": 0.0,
        "market_price_cent": 10.0,
        "forecast_pv_kw": 1.0,
        "forecast_consumption_kw": 0.5,
        "consumption_snapshot": {"flex_kw": {}, "battery_kw": 0.0},
        "consumer_powers_kw": {},
        "charging_contexts": {},
        "consumer_remaining_kwh": {},
        "thermal_observability": [],
    }
    base.update(extra)
    return base


@pytest.fixture
def history_files(tmp_path, monkeypatch):
    jsonl = tmp_path / "optimization_history.jsonl"
    legacy = tmp_path / "legacy.csv"
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(jsonl))
    monkeypatch.setattr(optimization_history, "LEGACY_CSV_FILE", str(legacy))
    return jsonl


@pytest.fixture
def rules_doc():
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


class TestChartHistoryDeviations:
    def test_present_slot_gets_warning(self, history_files, rules_doc, monkeypatch):
        slot = datetime(2026, 7, 5, 10, 0, tzinfo=TZ)
        _write_jsonl(
            history_files,
            [
                _entry(
                    slot,
                    consumer_powers_kw={"swimspa": 2.8},
                    consumption_snapshot={
                        "flex_kw": {"swimspa": 0.0},
                        "battery_kw": 0.0,
                    },
                    thermal_observability=[
                        {
                            "consumer_id": "swimspa",
                            "heating_hours": 2,
                            "heating_schedule": [0, 1],
                            "readings_c": {
                                "actual": 36.5,
                                "band_min": 35.5,
                                "band_max": 37.5,
                            },
                        }
                    ],
                )
            ],
        )
        from optimizer import deviation_timeline as dt

        monkeypatch.setattr(
            dt,
            "resolve_deviation_rules_document",
            lambda _doc=None: rules_doc,
        )
        end = slot.replace(minute=15)
        result = history_timeline.build_chart_history(slot, end)
        assert len(result.slot_deviation_events) == 1
        assert result.slot_deviation_events[0][0].category == "warning"

    def test_missing_slot_has_no_events(self, history_files, rules_doc, monkeypatch):
        slot = datetime(2026, 7, 5, 10, 0, tzinfo=TZ)
        _write_jsonl(history_files, [])
        from optimizer import deviation_timeline as dt

        monkeypatch.setattr(
            dt,
            "resolve_deviation_rules_document",
            lambda _doc=None: rules_doc,
        )
        end = slot.replace(minute=15)
        result = history_timeline.build_chart_history(slot, end)
        assert result.slot_qualities == (history_timeline.SLOT_MISSING,)
        assert result.slot_deviation_events == ((),)


class TestChartDisplayContextDeviations:
    def test_milp_tail_has_no_deviation_events(self, history_files, monkeypatch):
        slot = datetime(2026, 7, 5, 10, 0, tzinfo=TZ)
        _write_jsonl(
            history_files,
            [
                _entry(
                    slot,
                    consumer_powers_kw={"eauto": 3.5},
                    consumption_snapshot={"flex_kw": {"eauto": 0.0}, "battery_kw": 0.0},
                    charging_contexts={"eauto": {"plugged_in": True}},
                    consumer_remaining_kwh={"eauto": 8.0},
                )
            ],
        )
        rules_doc = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        from optimizer import deviation_timeline as dt

        monkeypatch.setattr(
            dt,
            "resolve_deviation_rules_document",
            lambda _doc=None: rules_doc,
        )
        now = slot.replace(minute=20)
        chart_context = build_live_chart_context(0, 0, now=now)
        sim_rows = [
            {
                "slot_datetime": now.replace(minute=0),
                "Uhrzeit": now.strftime("%d.%m. %H:%M"),
                "Strompreis (Cent/kWh)": 10.0,
                "Preis extrapoliert": False,
                "PV-Prognose (kW)": 1.0,
                "Verbrauch-Prognose (kW)": 0.5,
                "Geplante Batterie-Aktion (kW)": 0.0,
                "Netzbezug (kW)": 0.0,
                "Simulierter SoC (%)": 50.0,
                "Steuerbefehl": "Automatik",
            }
        ]
        display = build_chart_display_context(chart_context, sim_rows)
        assert display.history_slot_count > 0
        assert len(display.slot_deviation_events) == len(display.slot_datetimes)
        for index, quality in enumerate(display.slot_qualities):
            if quality == SLOT_MILP:
                assert display.slot_deviation_events[index] == ()
        history_indices = [
            index
            for index, quality in enumerate(display.slot_qualities)
            if quality == history_timeline.SLOT_PRESENT
        ]
        assert history_indices
        assert display.slot_deviation_events[history_indices[0]][0].category == "error"

    def test_forecast_segment_has_no_deviations(self):
        chart_context = build_live_chart_context(0, 1, now=NOW)
        display = build_chart_display_context(chart_context, [])
        assert all(events == () for events in display.slot_deviation_events)
