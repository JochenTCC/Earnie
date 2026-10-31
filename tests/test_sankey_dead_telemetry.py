"""Live-Sankey: warning instead of an empty figure when all meters read 0 (#89)."""
from __future__ import annotations

import pytest

from ui import sankey


class _FakeSt:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.charts: list[object] = []

    def write(self, *_args, **_kwargs) -> None:
        pass

    def caption(self, *_args, **_kwargs) -> None:
        pass

    def markdown(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, text: str) -> None:
        self.warnings.append(text)

    def plotly_chart(self, fig, **_kwargs) -> None:
        self.charts.append(fig)


@pytest.fixture
def fake_st(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(sankey, "st", fake)
    monkeypatch.setattr(sankey, "reload_runtime_config", lambda: None)
    monkeypatch.setattr(sankey.run_state, "load_run_state", lambda: None)
    monkeypatch.setattr(sankey.produktiv, "produktiv_caption", lambda _s: "")
    monkeypatch.setattr(
        sankey.live_consumption, "fetch_live_flex_kw_for_ui", lambda _s: {}
    )
    monkeypatch.setattr(sankey, "active_ehal_backend", lambda: "loxone")
    monkeypatch.setattr(sankey, "backend_label", lambda _b: "Loxone")
    return fake


def _render(monkeypatch, live: dict[str, float]) -> None:
    monkeypatch.setattr(sankey.ehal_live, "read_live_power_kw", lambda: live)
    # Body, not the st.fragment wrapper: the wrapper outside a script run
    # leaves Streamlit state behind that times out later AppTests on the worker.
    sankey._render_live_power_flow_body(current_soc=50.0)


def test_all_zero_live_values_show_warning_not_empty_sankey(monkeypatch, fake_st):
    monkeypatch.setattr(sankey.ehal_live, "is_loxone_backend", lambda: True)
    _render(monkeypatch, {"pv": 0.0, "house": 0.0, "battery": 0.0, "grid": 0.0})

    assert fake_st.charts == []
    assert len(fake_st.warnings) == 1
    assert "Alle Live-Leistungswerte von Loxone sind 0 kW" in fake_st.warnings[0]


def test_non_zero_live_values_draw_sankey(monkeypatch, fake_st):
    monkeypatch.setattr(sankey, "_sankey_breakdown_consumers", lambda: [])
    _render(monkeypatch, {"pv": 0.0, "house": 0.4, "battery": 0.0, "grid": 0.4})

    assert fake_st.warnings == []
    assert len(fake_st.charts) == 1


def test_warning_explains_push_zero_rule_for_push_backends(monkeypatch):
    monkeypatch.setattr(sankey, "active_ehal_backend", lambda: "loxone")
    monkeypatch.setattr(sankey, "backend_label", lambda _b: "Loxone")
    monkeypatch.setattr(sankey.ehal_live, "is_loxone_backend", lambda: True)
    monkeypatch.setattr(sankey.ehal_live, "is_ha_backend", lambda: False)
    monkeypatch.setenv("EARNIE_PUSH_REPEAT_S", "10")

    text = sankey.dead_telemetry_warning_text()

    assert "länger als 30 s" in text
    assert "0 angenommen (verstummt)" in text
    assert "mindestens alle 10 s" in text
    assert "EHAL-Com → Live-Lesen" in text


def test_warning_without_push_hint_for_openems(monkeypatch):
    monkeypatch.setattr(sankey, "active_ehal_backend", lambda: "openems")
    monkeypatch.setattr(sankey, "backend_label", lambda _b: "OpenEMS")
    monkeypatch.setattr(sankey.ehal_live, "is_loxone_backend", lambda: False)
    monkeypatch.setattr(sankey.ehal_live, "is_ha_backend", lambda: False)

    text = sankey.dead_telemetry_warning_text()

    assert "Alle Live-Leistungswerte von OpenEMS sind 0 kW" in text
    assert "verstummt" not in text
