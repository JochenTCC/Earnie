"""Tests für Live-Verbrauchs-Snapshots (Sankey, Live-Modus)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from data import live_consumption as lc
from integrations.loxone_client import LiveFlexPowerResult

_FILTER_CONTEXTS = {
    "swimspa_filter": {
        "native_start_hour": 10,
        "native_duration_hours": 4.0,
        "source_label": "loxone",
    }
}
_SLOT = datetime(2026, 7, 9, 12, 5, tzinfo=ZoneInfo("Europe/Vienna"))


def test_fetch_live_flex_kw_for_ui_passes_filter_contexts_from_main_state():
    main_state = {"filter_contexts": _FILTER_CONTEXTS}
    flex_result = LiveFlexPowerResult(
        kw={"swimspa": 0.0, "swimspa_filter": 0.18},
        chart_kw={"swimspa_filter": 0.18},
        measured_ids=frozenset({"swimspa", "swimspa_filter"}),
    )
    with patch.object(
        lc.loxone_client,
        "resolve_flexible_consumers_live_power",
        return_value=flex_result,
    ) as resolve:
        with patch.object(lc, "_ui_slot_datetime", return_value=_SLOT):
            result = lc.fetch_live_flex_kw_for_ui(main_state)

    resolve.assert_called_once_with(
        filter_contexts=_FILTER_CONTEXTS,
        slot_datetime=_SLOT,
    )
    assert result["swimspa_filter"] == 0.18
    assert result["swimspa"] == 0.0


def test_fetch_live_consumption_snapshot_uses_ui_flex_resolution():
    main_state = {"filter_contexts": _FILTER_CONTEXTS}
    live_power = {
        "house": 0.5,
        "pv": 3.6,
        "grid": -3.1,
        "battery": -0.03,
    }
    with patch.object(lc.loxone_client, "fetch_loxone_live_power", return_value=live_power):
        with patch.object(
            lc,
            "fetch_live_flex_kw_for_ui",
            return_value={"swimspa": 0.0, "swimspa_filter": 0.18},
        ) as fetch_flex:
            snapshot = lc.fetch_live_consumption_snapshot(main_state)

    fetch_flex.assert_called_once_with(main_state)
    assert snapshot is not None
    assert snapshot["flex_kw"]["swimspa_filter"] == 0.18
    assert snapshot["flex_kw"]["swimspa"] == 0.0
    assert snapshot["baseload_kw"] == 0.32


def test_filter_contexts_for_ui_uses_config_fallback_without_main_state():
    consumer = {
        "id": "swimspa_filter",
        "filter_schedule": {
            "enabled": True,
            "config_fallback": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            },
        },
    }
    with patch.object(lc.config, "get_flexible_consumers", return_value=[consumer]):
        contexts = lc.filter_contexts_for_ui(None)

    assert contexts == {
        "swimspa_filter": {
            "native_start_hour": 10.0,
            "native_duration_hours": 4.0,
            "source_label": "config_fallback",
        }
    }


def test_chart_debug_dump_replay_filter_attribution():
    """Replay chart_debug_20260709_120500: 0,15 kW am Gesamtzähler → Filter, nicht SwimSpa."""
    from integrations import loxone_client as lox

    consumers = [
        {
            "id": "swimspa",
            "nominal_power_kw": 2.8,
            "signal_type": "power",
            "loxone_inputs": {
                "power_name": "Ernie_Swim-Spa-P_act",
                "subtract_consumer_ids": ["swimspa_filter"],
            },
        },
        {
            "id": "swimspa_filter",
            "nominal_power_kw": 0.18,
            "signal_type": "binary",
            "loxone_inputs": {
                "power_name": "homie_bwa_spa_filter2",
                "alternate_binary_power_name": "homie_bwa_spa_filter1",
                "signal_type": "binary",
            },
        },
    ]

    def _reads(io_name: str):
        mapping = {
            "Ernie_Swim-Spa-P_act": 0.15,
            "homie_bwa_spa_filter2": 0.0,
            "homie_bwa_spa_filter1": 0.0,
        }
        return mapping.get(io_name)

    with patch.object(lox, "fetch_loxone_generic_value", side_effect=_reads):
        live = lox.resolve_flexible_consumers_live_power(
            consumers=consumers,
            filter_contexts=_FILTER_CONTEXTS,
            slot_datetime=_SLOT,
        )

    assert live.kw["swimspa_filter"] == 0.18
    assert live.kw["swimspa"] == 0.0
