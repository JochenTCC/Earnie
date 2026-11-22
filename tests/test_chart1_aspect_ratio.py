"""Chart 1 keeps a constant width:height ratio on desktop and tablet (phones: Plotly default).

The fixed doubled height (900 px) made the chart too tall in narrow and too flat in wide
windows; the box now takes its height from its width (CSS aspect-ratio) and the figure
stretches to it.
"""
from __future__ import annotations

from contextlib import contextmanager

import pandas as pd
import pytest

from ui import charts


def test_css_sets_the_ratio_and_the_floor_on_the_chart1_box():
    css = charts.chart1_aspect_css(4.0, min_height_px=320)
    assert f".st-key-{charts.CHART1_BOX_KEY}" in css
    assert "aspect-ratio: 4 / 1" in css
    assert "min-height: 320px" in css


def test_css_rejects_a_ratio_that_is_not_positive():
    with pytest.raises(ValueError):
        charts.chart1_aspect_css(0.0)


@pytest.fixture
def captured(monkeypatch):
    calls: dict = {"plotly": [], "containers": [], "markdown": []}
    monkeypatch.setattr(charts, "build_power_soc_chart_figure", lambda *a, **k: _Fig())
    monkeypatch.setattr(charts, "localized_figure", lambda fig: fig)
    monkeypatch.setattr(charts, "inject_mobile_legend_css", lambda: None)
    monkeypatch.setattr(charts, "render_collapsible_legend_from_figure", lambda fig: None)
    monkeypatch.setattr(
        charts.st, "plotly_chart", lambda fig, **kw: calls["plotly"].append(kw)
    )
    monkeypatch.setattr(
        charts.st, "markdown", lambda text, **kw: calls["markdown"].append(text)
    )

    @contextmanager
    def container(**kw):
        calls["containers"].append(kw)
        yield

    monkeypatch.setattr(charts.st, "container", container)
    return calls


class _Fig:
    def update_layout(self, **kw):  # a fixed height must no longer be set
        raise AssertionError(f"unexpected layout update {kw}")


def test_desktop_chart_stretches_into_the_aspect_box(captured, monkeypatch):
    monkeypatch.setattr(charts, "is_phone_request", lambda: False)
    charts.render_power_soc_chart(pd.DataFrame())
    assert captured["containers"] == [{"key": charts.CHART1_BOX_KEY}]
    assert captured["plotly"][0]["height"] == "stretch"
    assert any("aspect-ratio" in text for text in captured["markdown"])


def test_phone_chart_keeps_the_plotly_default_height(captured, monkeypatch):
    monkeypatch.setattr(charts, "is_phone_request", lambda: True)
    charts.render_power_soc_chart(pd.DataFrame())
    assert captured["containers"] == []
    assert "height" not in captured["plotly"][0]
