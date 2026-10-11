"""Tests für Loxone-Ist-SOC vs. berechneter Session-SOC."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from optimizer import ev_soc_tracking as est


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "charging_schedule": {
            "enabled": True,
            "target_soc_percent": 100.0,
            "charging_efficiency": 0.9,
            "loxone": {
                "actual_soc_name": "Ernie-SOC-Ist-EAuto",
                "battery_capacity_kwh_name": "Batteriekapazität_E-Auto",
            },
        },
    }


def test_loxone_reports_charge_complete_at_target():
    consumer = _eauto_consumer()
    with patch.object(est, "fetch_loxone_actual_soc_percent", return_value=100.0):
        assert est.loxone_reports_charge_complete(consumer) is True


def test_computed_session_soc_percent_from_plug_in_and_delivery():
    consumer = _eauto_consumer()
    session = {"plug_in_rest_soc_percent": 40.0}
    with patch.object(
        est.ehal_live,
        "resolve_consumer_battery_capacity_kwh",
        return_value=16.0,
    ):
        soc = est.computed_session_soc_percent(consumer, session, delivered_kwh=4.5)
    assert soc == pytest.approx(65.3125)


def test_compare_ev_soc_sources_warns_on_large_delta():
    consumer = _eauto_consumer()
    session = {"plug_in_rest_soc_percent": 40.0}
    with patch.object(est, "fetch_loxone_actual_soc_percent", return_value=90.0):
        with patch.object(
            est.ehal_live,
            "resolve_consumer_battery_capacity_kwh",
            return_value=16.0,
        ):
            note = est.compare_ev_soc_sources(
                consumer,
                session,
                delivered_kwh=4.5,
                live_kw=3.5,
            )
    assert note is not None
    assert note["warn"] is True
