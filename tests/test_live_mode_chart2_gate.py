"""Chart 2 on the Monitor page is hidden unless EARNIE_UI_CHART2=1 (2.7 release)."""
from __future__ import annotations

import pytest


@pytest.fixture
def live_mode(monkeypatch):
    from ui import live_mode as module

    monkeypatch.setattr(module, "reload_runtime_config", lambda: None)
    monkeypatch.setattr(module, "_live_optimization_prepare_fragment", lambda soc: None)
    monkeypatch.setattr(module, "_live_optimization_chart1_fragment", lambda soc: None)
    monkeypatch.setattr(module, "render_s2_nav_buttons", lambda now=None: None)
    monkeypatch.setattr(module, "render_live_power_flow", lambda soc: None)
    monkeypatch.setattr(module, "render_optimization_results_tail", lambda bundle: None)
    monkeypatch.setattr(module.st, "session_state", {})
    return module


def test_chart2_hidden_by_default(monkeypatch, live_mode):
    monkeypatch.delenv("EARNIE_UI_CHART2", raising=False)
    calls: list[str] = []
    monkeypatch.setattr(
        live_mode, "_live_optimization_chart2_fragment", lambda: calls.append("chart2")
    )
    assert live_mode.chart2_enabled() is False
    live_mode.render_optimization_savings_and_chart(50.0)
    assert calls == []


def test_chart2_shown_with_env_flag(monkeypatch, live_mode):
    monkeypatch.setenv("EARNIE_UI_CHART2", "1")
    calls: list[str] = []
    monkeypatch.setattr(
        live_mode, "_live_optimization_chart2_fragment", lambda: calls.append("chart2")
    )
    assert live_mode.chart2_enabled() is True
    live_mode.render_optimization_savings_and_chart(50.0)
    assert calls == ["chart2"]


@pytest.mark.parametrize("raw", ["0", "true", "yes", ""])
def test_chart2_flag_accepts_only_one(monkeypatch, live_mode, raw):
    monkeypatch.setenv("EARNIE_UI_CHART2", raw)
    assert live_mode.chart2_enabled() is False
