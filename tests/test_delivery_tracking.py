"""Tests für Lieferbuchung und Plausibilitätsprüfung."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from optimizer import delivery_tracking as dt
from optimizer import charging_session as cs


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "charging_schedule": {
            "enabled": True,
            "loxone": {"charge_immediate_name": "E-Auto_SOFORT_LADEN"},
        },
        "loxone_outputs": {"power_setpoint_name": "Ernie_EAuto_Ziel_kW"},
    }


def _session_ctx(*, plugged_in: bool = True, anticipated: bool = False) -> dict:
    return {
        "active": True,
        "plugged_in": plugged_in,
        "anticipated": anticipated,
        "deadline": datetime(2026, 6, 29, 7, 45),
        "target_kwh": 8.0,
        "use_time_window": False,
    }


class TestBookingPower:
    def test_session_prefers_live_over_planned(self):
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        assert dt.booking_power_kw(
            consumer, ctx, planned_kw=3.5, live_kw=1.2, book_planned=True
        ) == pytest.approx(1.2)

    def test_session_falls_back_to_planned_when_live_missing(self):
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        assert dt.booking_power_kw(
            consumer, ctx, planned_kw=2.0, live_kw=None, book_planned=True
        ) == pytest.approx(2.0)

    def test_event_run_uses_live_only_for_session(self):
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        assert dt.booking_power_kw(
            consumer, ctx, planned_kw=3.5, live_kw=0.0, book_planned=False
        ) == 0.0
        assert dt.booking_power_kw(
            consumer, ctx, planned_kw=3.5, live_kw=2.2, book_planned=False
        ) == pytest.approx(2.2)

    def test_non_session_ignores_live_without_planned_booking(self):
        consumer = {"id": "swimspa", "charging_schedule": {"enabled": False}}
        assert dt.booking_power_kw(
            consumer, None, planned_kw=2.8, live_kw=1.0, book_planned=False
        ) == 0.0

    def test_anticipated_absence_does_not_book_planned(self):
        consumer = _eauto_consumer()
        ctx = _session_ctx(plugged_in=False, anticipated=True)
        assert dt.booking_power_kw(
            consumer, ctx, planned_kw=2.76, live_kw=0.0, book_planned=True
        ) == 0.0


class TestSessionPlausibility:
    def test_reopens_when_charge_immediate_active(self):
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        effective, note = dt.assess_session_delivery(
            consumer,
            ctx,
            8.0,
            live_kw=0.0,
            trigger_snapshot={"eauto_charge_immediate": True},
        )
        assert note is not None
        assert note["role"] == "session_reopened"
        assert effective == pytest.approx(7.5)

    def test_reopens_when_live_charging_above_threshold(self, monkeypatch):
        monkeypatch.setattr(dt, "charging_power_threshold_kw", lambda: 0.2)
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        effective, note = dt.assess_session_delivery(
            consumer,
            ctx,
            8.0,
            live_kw=3.5,
            trigger_snapshot={"eauto_charge_immediate": False},
        )
        assert note is not None
        assert effective == pytest.approx(7.5)

    def test_keeps_delivery_when_session_complete_and_idle(self, monkeypatch):
        monkeypatch.setattr(dt, "charging_power_threshold_kw", lambda: 0.2)
        consumer = _eauto_consumer()
        ctx = _session_ctx()
        effective, note = dt.assess_session_delivery(
            consumer,
            ctx,
            8.0,
            live_kw=0.0,
            trigger_snapshot={"eauto_charge_immediate": False},
        )
        assert note is None
        assert effective == pytest.approx(8.0)


class TestRegisterConsumerDelivery:
    def test_session_books_live_energy(self, tmp_path, monkeypatch):
        import optimizer

        state_file = tmp_path / "flexible_consumers_state.json"
        monkeypatch.setattr(optimizer, "CONSUMER_STATE_FILE", str(state_file))

        consumer = _eauto_consumer()
        contexts = {"eauto": _session_ctx()}
        raw = {
            "date": "2026-06-28",
            "delivered": {},
            "charging_sessions": {
                "eauto": {
                    "target_kwh": 8.0,
                    "delivered_kwh": 0.0,
                    "deadline": "2026-06-29T07:45:00",
                }
            },
        }
        state = cs.normalize_consumer_state(
            raw,
            "2026-06-28",
            contexts,
            {"eauto": consumer},
            now=datetime(2026, 6, 28, 12, 0),
        )
        state_file.write_text(json.dumps(state), encoding="utf-8")

        compliance = optimizer.register_consumer_delivery(
            {"eauto": 3.5},
            charging_contexts=contexts,
            consumers=[consumer],
            live_flex_kw={"eauto": 2.0},
            sent_flex_kw={"eauto": 3.5},
            book_planned=True,
        )

        saved = json.loads(state_file.read_text(encoding="utf-8"))
        assert saved["charging_sessions"]["eauto"]["delivered_kwh"] == pytest.approx(0.5)
        assert compliance["eauto"]["source"] == "live"
        assert compliance["eauto"]["booked_kw"] == pytest.approx(2.0)
        assert compliance["eauto"]["sent_kw"] == pytest.approx(3.5)


CASE_FALSE_COMPLETE = "eauto_false_complete_2026-06-29"


class TestProdDumpFalseComplete:
    @pytest.fixture(scope="module")
    def manifest(self) -> dict:
        path = (
            Path(__file__).resolve().parent
            / "fixtures"
            / "prod_dumps"
            / CASE_FALSE_COMPLETE
            / "manifest.json"
        )
        if not path.is_file():
            pytest.skip(f"Prod-Dump {CASE_FALSE_COMPLETE} noch nicht archiviert")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_manifest_regression_shape(self, manifest):
        reg = manifest["regression"]
        assert reg["session_start"] == "2026-06-28T09:32:01"
        assert reg["deadline"] == "2026-06-29T07:45:00"
        assert reg["corrected_target_kwh"] == pytest.approx(11.556, abs=0.01)
        assert reg["remaining_kwh_at_correction"] == pytest.approx(7.985, abs=0.01)

    def test_plausibility_would_reopen_on_june_29_morning(self, manifest):
        from tests.fixtures import prod_dump_fixtures as pdf

        rows = pdf.load_jsonl(CASE_FALSE_COMPLETE)
        reg = manifest["regression"]
        consumer = _eauto_consumer()
        ctx = {
            "active": True,
            "plugged_in": True,
            "deadline": datetime.fromisoformat(reg["deadline"]),
            "target_kwh": float(reg["corrected_target_kwh"]),
            "use_time_window": False,
        }
        row = next(r for r in rows if r["written_at"].startswith("2026-06-29T07:30"))
        delivered = float(reg["corrected_target_kwh"])
        live_kw = float((row.get("flex_live_kw") or {}).get("eauto", 0.0))
        effective, note = dt.assess_session_delivery(
            consumer,
            ctx,
            delivered,
            live_kw=live_kw,
            trigger_snapshot=row.get("event_trigger_snapshot"),
        )
        assert note is not None
        assert effective < delivered
