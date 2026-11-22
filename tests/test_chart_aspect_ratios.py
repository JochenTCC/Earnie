"""Monitor charts keep a constant width:height ratio per chart (``ui.chart_aspect_ratios``).

The fixed doubled height of Chart 1 (900 px) was too tall in narrow and too flat in wide
windows. Chart 1, Chart 2 and the Sankey now sit in a box whose height the browser derives
from its width (CSS aspect-ratio); each chart has its own ratio (default 3:1). Phones keep
the figure's own height.
"""
from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import plotly.graph_objects as go
import pytest

from settings.system_settings import load_ui_chart_aspect_ratios
from ui import chart_aspect


# --- config ------------------------------------------------------------------------


def test_every_chart_defaults_to_three():
    assert load_ui_chart_aspect_ratios({}) == {"chart1": 3.0, "chart2": 3.0, "sankey": 3.0}


def test_each_chart_has_its_own_ratio():
    ratios = load_ui_chart_aspect_ratios(
        {"ui": {"chart_aspect_ratios": {"chart1": 4, "sankey": 2.5}}}
    )
    assert ratios == {"chart1": 4.0, "chart2": 3.0, "sankey": 2.5}


@pytest.mark.parametrize(
    "raw",
    [
        {"chart1": 0},
        {"chart2": -1},
        {"sankey": 11},
        {"chart1": "breit"},
        {"chart1": True},
        {"chart3": 3},
        [3, 3, 3],
    ],
)
def test_invalid_ratios_fail_loud(raw):
    with pytest.raises(ValueError, match="chart_aspect_ratios"):
        load_ui_chart_aspect_ratios({"ui": {"chart_aspect_ratios": raw}})


# --- CSS and rendering -------------------------------------------------------------


def test_css_targets_every_box_of_the_chart():
    css = chart_aspect.aspect_css("chart2", 2.5, min_height_px=400)
    assert '[class*="st-key-chart_aspect_chart2__"]' in css
    assert "aspect-ratio: 2.5 / 1" in css
    assert "min-height: 400px" in css


def test_css_rejects_a_ratio_that_is_not_positive():
    with pytest.raises(ValueError):
        chart_aspect.aspect_css("chart1", 0.0, min_height_px=320)


@pytest.fixture
def captured(monkeypatch):
    calls: dict = {"plotly": [], "containers": [], "markdown": []}
    monkeypatch.setattr(
        chart_aspect.st, "plotly_chart", lambda fig, **kw: calls["plotly"].append((fig, kw))
    )
    monkeypatch.setattr(
        chart_aspect.st, "markdown", lambda text, **kw: calls["markdown"].append(text)
    )

    @contextmanager
    def container(**kw):
        calls["containers"].append(kw)
        yield

    monkeypatch.setattr(chart_aspect.st, "container", container)
    return calls


def test_desktop_chart_drops_its_height_and_stretches_into_its_box(captured, monkeypatch):
    import config

    monkeypatch.setattr(chart_aspect, "is_phone_request", lambda: False)
    monkeypatch.setattr(
        config, "get_ui_chart_aspect_ratio", lambda cid: {"sankey": 2.0}[cid]
    )
    fig = go.Figure()
    fig.update_layout(height=660)
    chart_aspect.render_plotly_with_aspect(
        fig, chart_id="sankey", min_height_px=660, key="live_power_flow_sankey"
    )
    drawn, kwargs = captured["plotly"][0]
    assert drawn.layout.height is None
    assert kwargs == {"height": "stretch", "key": "live_power_flow_sankey"}
    assert captured["containers"] == [{"key": "chart_aspect_sankey__main"}]
    assert "aspect-ratio: 2 / 1" in captured["markdown"][0]
    assert "min-height: 660px" in captured["markdown"][0]


def test_phone_chart_keeps_its_own_height(captured, monkeypatch):
    monkeypatch.setattr(chart_aspect, "is_phone_request", lambda: True)
    fig = go.Figure()
    fig.update_layout(height=520)
    chart_aspect.render_plotly_with_aspect(fig, chart_id="chart2", key="c2")
    drawn, kwargs = captured["plotly"][0]
    assert drawn.layout.height == 520
    assert kwargs == {"key": "c2"}
    assert captured["containers"] == []


def test_boxes_of_one_chart_on_one_page_get_distinct_keys():
    assert chart_aspect.aspect_box_key("chart2", "se:a") != chart_aspect.aspect_box_key(
        "chart2", "se:b"
    )


def test_chart1_goes_through_its_aspect_box(monkeypatch):
    from ui import charts

    seen: dict = {}
    monkeypatch.setattr(charts, "build_power_soc_chart_figure", lambda *a, **k: go.Figure())
    monkeypatch.setattr(charts, "inject_mobile_legend_css", lambda: None)
    monkeypatch.setattr(charts, "render_collapsible_legend_from_figure", lambda fig: None)
    monkeypatch.setattr(
        charts, "render_plotly_with_aspect", lambda fig, **kw: seen.update(kw)
    )
    charts.render_power_soc_chart(pd.DataFrame(), chart_key="live_chart1")
    assert seen["chart_id"] == "chart1" and seen["instance"] == "live_chart1"
