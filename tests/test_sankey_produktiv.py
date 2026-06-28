"""Tests für Produktiv-Overlay im Live-Sankey."""
from __future__ import annotations

from datetime import datetime, timedelta

from ui import sankey_produktiv as produktiv


def _state(*, age_sec: float = 30.0, success: bool = True) -> dict:
    completed = (datetime.now() - timedelta(seconds=age_sec)).isoformat(timespec="seconds")
    return {
        "success": success,
        "completed_at": completed,
        "mode": 1,
        "target_power_kw": 2.5,
        "target_soc_percent": 85.0,
        "forecast_consumption_kw": 0.54,
        "consumer_powers_kw": {"eauto": 11.0, "swimspa": 2.8},
    }


def test_has_produktiv_run_when_successful():
    assert produktiv.has_produktiv_run(_state(age_sec=30.0)) is True


def test_has_produktiv_run_even_when_stale():
    assert produktiv.has_produktiv_run(_state(age_sec=900.0)) is True


def test_run_fresh_only_within_threshold():
    assert produktiv.produktiv_run_fresh(_state(age_sec=30.0)) is True
    assert produktiv.produktiv_run_fresh(_state(age_sec=200.0)) is False


def test_flex_label_includes_soll():
    label = produktiv.flex_node_label("E-Auto", 0.0, "eauto", _state())
    assert "live 0.00 kW" in label
    assert "Soll 11.00 kW" in label


def test_caption_keeps_soll_hint_when_stale():
    caption = produktiv.produktiv_caption(_state(age_sec=600.0))
    assert "Soll-Werte aus diesem Lauf" in caption


def test_flex_sankey_link_uses_placeholder_when_inactive_with_soll():
    link_kw, is_placeholder = produktiv.flex_sankey_link(0.0, "eauto", _state())
    assert link_kw == produktiv.SOLL_PLACEHOLDER_FLOW_KW
    assert is_placeholder is True


def test_flex_sankey_link_no_link_without_soll():
    state = _state()
    state["consumer_powers_kw"] = {"eauto": 0.0}
    link_kw, is_placeholder = produktiv.flex_sankey_link(0.0, "eauto", state)
    assert link_kw is None
    assert is_placeholder is False


def test_flex_sankey_link_live_when_drawing():
    link_kw, is_placeholder = produktiv.flex_sankey_link(3.5, "eauto", _state())
    assert link_kw == 3.5
    assert is_placeholder is False


def test_flex_mismatch_color():
    color = produktiv.flex_node_color("#9b59b6", 0.0, "eauto", _state())
    assert color == produktiv._FLEX_MISMATCH_COLOR
