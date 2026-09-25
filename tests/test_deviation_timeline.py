"""Integration: Abweichungen entlang Chart-Historie und Display-Kontext (Soll-Ist P2)."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

os.environ.setdefault("EARNIE_OFFLINE", "1")

from optimizer import battery as bat
from runtime_store import history_timeline, optimization_history
from ui.chart_context import SLOT_MILP, build_chart_display_context, build_live_chart_context

RULES_PATH = Path("share/config") / "deviation_rules.example.json"
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
    monkeypatch.setattr(optimization_history, "HISTORY_FILE", str(jsonl))
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

    def test_closed_interval_survives_same_slot_rewrite(
        self, history_files, rules_doc, monkeypatch
    ):
        """Later same-slot entry without closed_interval must not drop prior-QH mean.

        Mirrors dump debug_dump_20260923_201155: 19:30 rewrite lost closed mean for
        19:15 → decision snap looked like forced discharge missing.
        """
        slot_a = datetime(2026, 9, 23, 19, 15, tzinfo=TZ)
        slot_b = datetime(2026, 9, 23, 19, 30, 19, tzinfo=TZ)
        slot_b_rewrite = datetime(2026, 9, 23, 19, 37, 26, tzinfo=TZ)
        _write_jsonl(
            history_files,
            [
                _entry(
                    slot_a,
                    mode=bat.MODE_ZWANGS_ENTLADEN,
                    target_power_kw=3.317,
                    battery_plan_kw=-3.317,
                    consumption_snapshot={"flex_kw": {}, "battery_kw": 0.34},
                    closed_interval={
                        "interval_start": "2026-09-23T19:00:00",
                        "sample_count": 31,
                        "battery_kw": 0.451,
                        "pv_kw": 0.0,
                        "grid_kw": 0.0,
                        "house_kw": 0.5,
                        "baseload_kw": 0.5,
                        "flex_kw": {},
                    },
                ),
                _entry(
                    slot_b,
                    mode=bat.MODE_ZWANGS_ENTLADEN,
                    target_power_kw=5.0,
                    battery_plan_kw=-5.0,
                    consumption_snapshot={"flex_kw": {}, "battery_kw": 3.32},
                    closed_interval={
                        "interval_start": "2026-09-23T19:15:00",
                        "sample_count": 31,
                        "battery_kw": 2.844,
                        "pv_kw": 0.0,
                        "grid_kw": -2.0,
                        "house_kw": 0.5,
                        "baseload_kw": 0.5,
                        "flex_kw": {},
                    },
                ),
                _entry(
                    slot_b_rewrite,
                    mode=bat.MODE_ZWANGS_ENTLADEN,
                    target_power_kw=4.19,
                    battery_plan_kw=-4.19,
                    consumption_snapshot={"flex_kw": {}, "battery_kw": 5.0},
                ),
            ],
        )
        from optimizer import deviation_timeline as dt

        monkeypatch.setattr(
            dt,
            "resolve_deviation_rules_document",
            lambda _doc=None: rules_doc,
        )
        end = datetime(2026, 9, 23, 19, 45, tzinfo=TZ)
        result = history_timeline.build_chart_history(slot_a, end)
        assert result.slot_starts[0] == slot_a
        battery_events = [
            ev.rule_id
            for ev in result.slot_deviation_events[0]
            if ev.scope == "battery"
        ]
        assert battery_events == []



class TestChartDisplayContextDeviations:
    def test_milp_tail_has_no_deviation_events(self, history_files, monkeypatch):
        slot = datetime(2026, 7, 5, 10, 0, tzinfo=TZ)
        _write_jsonl(
            history_files,
            [
                _entry(
                    slot,
                    consumer_powers_kw={"ev": 3.5},
                    consumption_snapshot={"flex_kw": {"ev": 0.0}, "battery_kw": 0.0},
                    charging_contexts={"ev": {"plugged_in": True}},
                    consumer_remaining_kwh={"ev": 8.0},
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
