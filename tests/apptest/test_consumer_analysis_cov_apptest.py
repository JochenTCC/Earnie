"""AppTest: Analyse Verbrauch & Kosten with a synthetic cost-analysis series.

The page smoke covers only the empty state. Here the series builder, the clock,
the account chart and the Live heat-content source are replaced, so window
selection, cost charts / KPIs and the heat-content section render.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean, messages
from ui.consumer_cost_analysis_data import (
    CostAnalysisSeries,
    _consumer_labels,
    build_slot_from_powers,
)
from ui.consumption_display.heat_content_history import LiveHeatContentSeries
from ui.pages import page_consumer_analysis

_SCRIPT = Path(__file__).parent / "scripts" / "run_cov_consumer_analysis.py"
_NOW = datetime(2026, 9, 20, 12, 0)
_FIRST = datetime(2026, 9, 8, 0, 0)
_SLOT_COUNT = 12 * 24 + 12  # hourly 08.09. 00:00 … 20.09. 11:00


def _series() -> CostAnalysisSeries:
    slots = []
    for i in range(_SLOT_COUNT):
        start = _FIRST + timedelta(hours=i)
        pv = 1.0 if 10 <= start.hour < 16 else 0.0
        load = {"baseload": 0.5, "wp": 1.5}
        slots.append(
            build_slot_from_powers(
                slot_start=start,
                price_cent=30.0,
                pv_kw=pv,
                load_by_id=load,
                battery_charge_kw=0.0,
                battery_discharge_kw=0.0,
                grid_import_kw=2.0 - pv,
                grid_export_kw=0.0,
            )
        )
    return CostAnalysisSeries(
        slots=tuple(slots),
        consumer_labels=_consumer_labels([{"id": "wp", "name": "Wärmepumpe"}]),
        data_start=slots[0].slot_start,
        data_end=slots[-1].slot_start,
    )


def _heat(sim, meas) -> LiveHeatContentSeries:
    return LiveHeatContentSeries(
        timestamps=["2026-09-20 10:00:00", "2026-09-20 11:00:00"],
        q_sim_by_key={"pool": sim},
        q_meas_by_key={"pool": meas},
        labels={"pool": "Pool"},
    )


@pytest.fixture
def page(monkeypatch):
    def _set(*, heat=None, account_error: str | None = None, fan_chart=None) -> AppTest:
        series = _series()
        monkeypatch.setattr(page_consumer_analysis, "live_now", lambda: _NOW)
        monkeypatch.setattr(
            page_consumer_analysis, "build_cost_analysis_series", lambda now: series
        )

        def _account(start, end):
            if account_error:
                raise ValueError(account_error)
            st.markdown(f"ACCOUNT {start:%d.%m.%Y %H:%M}–{end:%d.%m.%Y %H:%M}")

        monkeypatch.setattr(page_consumer_analysis, "render_period_account_chart", _account)
        monkeypatch.setattr(
            page_consumer_analysis, "live_heat_content_for_window", lambda s, e: heat
        )
        monkeypatch.setattr(
            page_consumer_analysis, "live_heat_content_forecast_fan", lambda end: None
        )
        if fan_chart is not None:
            monkeypatch.setattr(page_consumer_analysis, "live_heat_content_chart", fan_chart)
        return AppTest.from_file(str(_SCRIPT), default_timeout=30).run()

    return _set


def _chart_titles(at: AppTest) -> list[str]:
    titles = []
    for chart in at.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        title = spec.get("layout", {}).get("title", {})
        titles.append(title.get("text", "") if isinstance(title, dict) else str(title))
    return titles


def _chart(at: AppTest, title_prefix: str) -> dict:
    for chart in at.get("plotly_chart"):
        spec = json.loads(chart.proto.spec)
        title = spec.get("layout", {}).get("title", {})
        text = title.get("text", "") if isinstance(title, dict) else str(title)
        if text.startswith(title_prefix):
            return spec
    raise AssertionError(f"no chart {title_prefix!r} in {_chart_titles(at)}")


_LATEST_LABEL = "13.09.2026–20.09.2026 (7 Tage)"


def test_window_selection_defaults_to_latest_7_days(page):
    at = page()
    assert_clean(at)
    radio = at.radio(key="cost_analysis_period_length")
    assert radio.options == ["7 Tage", "28 Tage"] and radio.value == "7 Tage"
    assert any(m.value == f"**{_LATEST_LABEL}**" for m in at.markdown)
    assert any(m.value == "ACCOUNT 13.09.2026 11:00–20.09.2026 11:00" for m in at.markdown)
    assert at.button(key="cost_analysis_period_forward").disabled


def test_switch_to_28_days_shows_whole_log(page):
    at = page()
    at.radio(key="cost_analysis_period_length").set_value("28 Tage").run()
    assert_clean(at)
    assert any(m.value == "**23.08.2026–20.09.2026 (28 Tage)**" for m in at.markdown)
    caption = next(c for c in messages(at)["caption"] if c.startswith("Datengrundlage"))
    assert f"({_SLOT_COUNT} Slots)" in caption


def test_date_jump_moves_account_and_cost_window(page):
    at = page()
    at.text_input(key="cost_analysis_period_jump").input("10.09.2026")
    at.button(key="cost_analysis_period_jump_btn").click().run()
    assert_clean(at)
    assert any(m.value.startswith("ACCOUNT 06.09.2026 11:00") for m in at.markdown)
    assert any(t.endswith("06.09.2026–13.09.2026 (7 Tage)") for t in _chart_titles(at))


def test_account_error_is_shown_and_rest_still_renders(page):
    at = page(account_error="kein Ledger")
    assert_clean(at)
    assert "Kontostand kann nicht gezeichnet werden: kein Ledger" in messages(at)["error"]
    assert any(t.startswith("Kosten (nur Netzanteil)") for t in _chart_titles(at))


def test_cost_section_charts_kpis_and_table(page):
    at = page()
    assert_clean(at)
    titles = _chart_titles(at)
    assert f"Herkunft je Verbraucher — {_LATEST_LABEL}" in titles
    assert f"Kosten (nur Netzanteil) — {_LATEST_LABEL}" in titles
    assert f"Batterie-Energieflüsse — {_LATEST_LABEL}" in titles

    # 7 days × 24 h of hourly slots in the window; per slot 0.25 h (QH weight).
    mix = _chart(at, "Herkunft je Verbraucher")
    bars = {trace["name"]: trace for trace in mix["data"]}
    assert list(bars) == ["PV", "Batterie", "Netz"]
    assert bars["PV"]["x"] == ["Grundlast", "Wärmepumpe"]
    # Wärmepumpe has 3× the baseload share of every source.
    assert bars["Netz"]["y"][1] == pytest.approx(3 * bars["Netz"]["y"][0])
    assert sum(bars["Batterie"]["y"]) == pytest.approx(0.0)

    cost = _chart(at, "Kosten (nur Netzanteil)")
    (trace,) = cost["data"]
    assert trace["x"] == ["Grundlast", "Wärmepumpe"]
    assert trace["y"][1] == pytest.approx(3 * trace["y"][0])

    metrics = {m.label: m.value for m in at.metric}
    assert set(metrics) == {_LATEST_LABEL, "Letzte 365 Tage"}
    assert metrics[_LATEST_LABEL].endswith("€")

    (table,) = at.dataframe
    assert list(table.value["Verbraucher"]) == ["Grundlast", "Wärmepumpe"]


def test_heat_content_missing_shows_info(page):
    at = page(heat=None)
    assert_clean(at)
    assert any("#### Wärmeinhalt" == m.value for m in at.markdown)
    assert any(
        i.startswith("Keine Wärmeinhalt-Daten") and _LATEST_LABEL in i
        for i in messages(at)["info"]
    )


def test_heat_content_without_values_shows_info(page):
    at = page(heat=_heat([None, None], [None, None]))
    assert_clean(at)
    assert any(i.startswith("Keine Wärmeinhalt-Daten") for i in messages(at)["info"])


def test_heat_content_sim_only_hints_missing_measurement(page):
    at = page(heat=_heat([10.0, 11.0], [None, None]))
    assert_clean(at)
    assert f"Wärmeinhalt — {_LATEST_LABEL}" in _chart_titles(at)
    assert any(c.startswith("Ist-Wärmeinhalt erscheint") for c in messages(at)["caption"])


def test_heat_content_measured_only_hints_missing_sim(page):
    at = page(heat=_heat([None, None], [10.0, 11.0]))
    assert_clean(at)
    captions = messages(at)["caption"]
    assert any(c.startswith("Sim-Wärmeinhalt (`Q_sim`) fehlt") for c in captions)
    assert not any(c.startswith("Ist-Wärmeinhalt erscheint") for c in captions)


def test_heat_content_forecast_fan_caption(page):
    import plotly.graph_objects as go

    def _fan_chart(*_args, **_kwargs):
        fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
        fig.layout.meta = {
            "has_measured": True,
            "has_sim": True,
            "forecast_fan_traces": 3,
            "forecast_fan_horizon_h": 18,
        }
        return fig

    at = page(heat=_heat([10.0, 11.0], [10.0, 11.0]), fan_chart=_fan_chart)
    assert_clean(at)
    captions = messages(at)["caption"]
    assert any("gemeinsamer Horizont 18 h" in c for c in captions)
    assert not any(c.startswith(("Ist-Wärmeinhalt", "Sim-Wärmeinhalt")) for c in captions)
