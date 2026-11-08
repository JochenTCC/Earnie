"""Numbers in the viewer's browser language (ui/number_format.py)."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import pytest

from ui import number_format, simulation_results
from ui.consumer_cost_analysis_charts import battery_flow_balance_caption
from ui.consumer_cost_battery_metrics import BatteryPeriodMetrics
from ui.number_format import (
    decimal_separator,
    format_cent_kwh,
    format_decimal,
    format_euro,
    format_general,
    localized_figure,
    plotly_separators,
    viewer_language,
)
from ui.saving_text import saving_text


def _viewer(monkeypatch: pytest.MonkeyPatch, header: str | None) -> None:
    monkeypatch.setattr(number_format, "_request_accept_language", lambda: header)


@pytest.mark.parametrize(
    ("header", "language"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("en-US,en;q=0.9,de;q=0.8", "en"),
        ("fr-FR,fr;q=0.9,en;q=0.8", "en"),
        ("fr-FR,ja", "de"),
        (None, "de"),
    ],
)
def test_viewer_language_falls_back_to_the_german_ui(
    monkeypatch: pytest.MonkeyPatch, header: str | None, language: str
) -> None:
    _viewer(monkeypatch, header)
    assert viewer_language() == language


def test_without_request_header_the_separator_is_a_comma() -> None:
    assert decimal_separator() == ","
    assert format_euro(12.345) == "12,35 €"
    assert plotly_separators() == ",."


def test_english_viewer_gets_a_point(monkeypatch: pytest.MonkeyPatch) -> None:
    _viewer(monkeypatch, "en-US,en;q=0.9")
    assert format_euro(-3.5, signed=True) == "-3.50 €"
    assert saving_text(-2.18) == "2.18 € mehr ausgegeben"
    assert plotly_separators() == ".,"


def test_signed_and_digits() -> None:
    assert format_decimal(0.2, signed=True) == "+0,20"
    assert format_euro(-100.0, signed=True) == "-100,00 €"
    assert format_cent_kwh(-0.1234, 3, signed=True) == "-0,123 Cent/kWh"
    assert format_cent_kwh(28.5, 1) == "28,5 Cent/kWh"


def test_format_general_follows_the_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    assert format_general(2.5) == "2,5"
    assert format_general(3.0) == "3"
    _viewer(monkeypatch, "en-US,en;q=0.9")
    assert format_general(2.5) == "2.5"


def test_localized_figure_sets_the_viewers_separators(monkeypatch: pytest.MonkeyPatch) -> None:
    fig = go.Figure()
    assert localized_figure(fig) is fig
    assert fig.layout.separators == ",."
    _viewer(monkeypatch, "en-US,en;q=0.9")
    assert localized_figure(go.Figure()).layout.separators == ".,"


def test_battery_caption_follows_the_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    def caption() -> str:
        return battery_flow_balance_caption(
            SimpleNamespace(battery_charge_kwh=1.5, battery_discharge_kwh=0.25),
            BatteryPeriodMetrics(
                eta_measured=None,
                eta_nominal=0.9,
                standby_a_kwh=0.5,
                standby_b_kwh=0.25,
                standby_nominal_kw=0.02,
                recommended_standby_kw=None,
                standby_hint=False,
            ),
        )

    assert "Laden 1,50 kWh · Entladen 0,25 kWh · Δ +1,25 kWh" in caption()
    _viewer(monkeypatch, "en-US,en;q=0.9")
    assert "Laden 1.50 kWh · Entladen 0.25 kWh · Δ +1.25 kWh" in caption()


def test_simulation_table_uses_the_viewers_separator(monkeypatch: pytest.MonkeyPatch) -> None:
    rendered: list[str] = []
    monkeypatch.setattr(
        simulation_results,
        "render_frozen_simulation_table",
        lambda styler: rendered.append(styler.to_html()),
    )
    frame = pd.DataFrame({"Uhrzeit": ["12:00"], "Netz (kW)": [1.5]})
    simulation_results._render_simulation_table(frame, None)
    assert "1,5" in rendered[0]
    assert "1.5" not in rendered[0]


def _figure_is_localized(call: ast.Call) -> bool:
    if not call.args or not isinstance(call.args[0], ast.Call):
        return False
    return getattr(call.args[0].func, "id", None) == "localized_figure"


def test_every_plotly_chart_gets_the_viewers_separators() -> None:
    """A new ``st.plotly_chart`` without ``localized_figure`` would show points next to commas."""
    missing = []
    found = 0
    for path in Path("ui").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "plotly_chart":
                found += 1
                if not _figure_is_localized(node):
                    missing.append(f"{path}:{node.lineno}")
    assert found > 0
    assert missing == []
