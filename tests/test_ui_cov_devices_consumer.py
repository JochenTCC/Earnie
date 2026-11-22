"""Unit tests for pure helpers of Manuelle Geräte and Analyse Verbrauch & Kosten.

Render paths are covered by tests/apptest/test_devices_cov_apptest.py,
test_consumer_analysis_cov_apptest.py and test_period_navigation_cov_apptest.py.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import config
from ui import consumer_cost_analysis_charts as charts
from ui import sankey, support_package
from ui.consumer_cost_analysis_data import (
    BASELOAD_ID,
    BASELOAD_LABEL,
    CostAnalysisSeries,
    _consumer_labels,
    _entries_by_slot,
    build_slot_from_powers,
)
from ui.consumption_display.period import (
    PeriodKind,
    TimeWindow,
    list_rolling_windows_for_kind,
    rolling_days,
    window_containing_date,
)
from ui.pages import page_devices

# --- page_devices ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("appliance", "expected"),
    [({}, 6), ({"recommendation_horizon_h": 0}, 1), ({"recommendation_horizon_h": "3"}, 3)],
)
def test_recommendation_horizon_defaults_and_clamps(appliance, expected):
    assert page_devices._recommendation_horizon_h(appliance) == expected


def test_star_threshold_settings_come_from_config(monkeypatch):
    monkeypatch.setattr(
        page_devices.config,
        "get_appliance_recommendation_settings",
        lambda: {"abs_margin_cent": "0.2", "pct_stars_4": 5, "pct_stars_1": 40},
    )
    settings = page_devices._star_threshold_settings()
    assert (settings.abs_margin_cent, settings.pct_stars_4, settings.pct_stars_1) == (
        0.2,
        5.0,
        40.0,
    )


def test_rec_table_col_rules_one_width_rule_per_column():
    rules = page_devices._rec_table_col_rules()
    for index, width in enumerate(page_devices._REC_TABLE_COL_REM, start=1):
        assert f'[data-testid="stColumn"]:nth-child({index}) {{' in rules
        assert f"width: {width}rem !important;" in rules
        assert f"max-width: {width}rem;" in rules
    assert ":nth-child(5)" not in rules


def test_recommendation_table_css_is_one_style_block_with_all_parts():
    css = page_devices._recommendation_table_css()
    assert css.strip().startswith("<style>") and css.strip().endswith("</style>")
    assert css.count("<style>") == 1
    assert page_devices._rec_table_col_rules() in css
    assert "flex-wrap: nowrap" in css  # layout part
    assert "line-height: 0.8" in css  # cell part


def test_schedule_matches_option_compares_in_planning_timezone():
    tz = ZoneInfo(config.get_planning_timezone())
    option = datetime(2026, 9, 20, 14, 30, tzinfo=tz)
    same_instant_utc = option.astimezone(ZoneInfo("UTC")).isoformat()
    assert page_devices._schedule_matches_option({"start_at": same_instant_utc}, option)
    # Naive stored value means planning-local time.
    assert page_devices._schedule_matches_option({"start_at": "2026-09-20T14:30:00"}, option)
    assert not page_devices._schedule_matches_option(
        {"start_at": "2026-09-20T15:00:00"}, option
    )
    assert not page_devices._schedule_matches_option({}, option)
    assert not page_devices._schedule_matches_option({"start_at": ""}, option)


# --- consumer_cost_analysis_data -------------------------------------------------------


def test_entries_by_slot_keeps_latest_entry_per_quarter_hour():
    early = {"completed_at": "2026-09-20T10:01:00", "tag": "early"}
    late = {"completed_at": "2026-09-20T10:14:00", "tag": "late"}
    other = {"completed_at": "2026-09-20T10:16:00", "tag": "other"}
    broken = {"completed_at": "kaputt"}
    by_slot = _entries_by_slot([late, early, other, broken])
    assert {k.strftime("%H:%M"): v["tag"] for k, v in by_slot.items()} == {
        "10:00": "late",
        "10:15": "other",
    }


def test_entries_by_slot_empty_and_unparsable():
    assert _entries_by_slot([]) == {}
    assert _entries_by_slot([{"completed_at": None}, {}]) == {}


def test_consumer_labels_prefer_name_then_label_then_id():
    labels = _consumer_labels(
        [
            {"id": "wp", "name": "Wärmepumpe", "label": "WP"},
            {"id": 7, "label": "Pool"},
            {"id": "ev"},
        ]
    )
    assert labels == {BASELOAD_ID: BASELOAD_LABEL, "wp": "Wärmepumpe", "7": "Pool", "ev": "ev"}


# --- consumer_cost_analysis_charts -----------------------------------------------------

_WINDOW = TimeWindow(
    start=datetime(2026, 9, 13), end=datetime(2026, 9, 20), kind=PeriodKind.ROLLING_7
)
_LABELS = {BASELOAD_ID: BASELOAD_LABEL, "wp": "Wärmepumpe"}


def _slot(hour: int, *, pv: float = 0.0):
    # Consumer listed before baseload: the charts must still put baseload first.
    return build_slot_from_powers(
        slot_start=datetime(2026, 9, 19, hour),
        price_cent=40.0,
        pv_kw=pv,
        load_by_id={"wp": 3.0, BASELOAD_ID: 1.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0 - pv,
        grid_export_kw=0.0,
    )


def test_window_source_mix_chart_stacks_sources_per_consumer():
    fig = charts.window_source_mix_chart(
        [_slot(10), _slot(12, pv=2.0)], labels=_LABELS, window=_WINDOW
    )
    assert fig.layout.barmode == "stack"
    assert fig.layout.title.text == "Herkunft je Verbraucher — 13.09.2026–20.09.2026 (7 Tage)"
    bars = {trace.name: trace for trace in fig.data}
    assert list(bars) == ["PV", "Batterie", "Netz"]
    assert list(bars["PV"].x) == ["Grundlast", "Wärmepumpe"]
    # 0.25 h slots: slot 1 grid 4 kW, slot 2 PV 2 kW + grid 2 kW; split 1:3.
    assert list(bars["PV"].y) == pytest.approx([0.125, 0.375])
    assert list(bars["Netz"].y) == pytest.approx([0.375, 1.125])
    assert list(bars["Batterie"].y) == pytest.approx([0.0, 0.0])


def test_window_cost_chart_grid_cost_per_consumer(monkeypatch):
    monkeypatch.setattr(charts, "_consumers_by_id", lambda: {})
    fig = charts.window_cost_chart([_slot(10)], labels=_LABELS, window=_WINDOW)
    (trace,) = fig.data
    assert list(trace.x) == ["Grundlast", "Wärmepumpe"]
    # 4 kW × 0.25 h × 0.40 €/kWh = 0.40 €, split 1:3.
    assert list(trace.y) == pytest.approx([0.1, 0.3])
    assert trace.marker.color[0] == charts.COLOR_BASELOAD
    assert trace.marker.color[1] == charts.COLOR_GRID_IMPORT  # unknown consumer
    assert fig.layout.title.text.startswith("Kosten (nur Netzanteil)")
    assert fig.layout.showlegend is False


def test_format_coverage_with_and_without_data():
    slots = (_slot(10), _slot(11))
    series = CostAnalysisSeries(
        slots=slots,
        consumer_labels=_LABELS,
        data_start=slots[0].slot_start,
        data_end=slots[1].slot_start,
    )
    text = charts._format_coverage(series)
    assert text.startswith("Datengrundlage Produktiv-Log: 19.09.2026 10:00 – 19.09.2026 11:00 (2 Slots).")
    empty = CostAnalysisSeries(slots=(), consumer_labels={}, data_start=None, data_end=None)
    assert charts._format_coverage(empty) == "Keine Produktiv-Log-Daten."


class _FakeColumn:
    def __init__(self, fake):
        self._fake = fake

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def metric(self, label, value, help=None):
        self._fake.calls.append(("metric", (label, value), {"help": help}))


class _FakeSt:
    """Records the Streamlit calls of the chart renderers (no script context needed)."""

    def __init__(self):
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _record

    def columns(self, n):
        return [_FakeColumn(self) for _ in range(n)]


def test_render_period_kpis_window_and_trailing_year(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(charts, "st", fake)
    old = build_slot_from_powers(
        slot_start=datetime(2025, 1, 1, 10),  # > 365 days before now
        price_cent=40.0,
        pv_kw=0.0,
        load_by_id={BASELOAD_ID: 4.0},
        battery_charge_kw=0.0,
        battery_discharge_kw=0.0,
        grid_import_kw=4.0,
        grid_export_kw=0.0,
    )
    window_slots = [_slot(10)]
    series = CostAnalysisSeries(
        slots=(old, *window_slots, _slot(11)),
        consumer_labels=_LABELS,
        data_start=old.slot_start,
        data_end=datetime(2026, 9, 19, 11),
    )
    charts.render_period_kpis(
        series, window_slots=window_slots, window=_WINDOW, now=datetime(2026, 9, 20)
    )
    metrics = {c[1][0]: (c[1][1], c[2]["help"]) for c in fake.calls if c[0] == "metric"}
    assert metrics[_WINDOW_LABEL][0] == charts.format_euro(0.4)
    assert "1 Slots" in metrics[_WINDOW_LABEL][1]
    # Trailing year: the two 2026 slots only (old slot outside 365 days).
    assert metrics["Letzte 365 Tage"][0] == charts.format_euro(0.8)
    assert "2 Slots" in metrics["Letzte 365 Tage"][1]
    (frame_call,) = [c for c in fake.calls if c[0] == "dataframe"]
    rows = frame_call[1][0]
    assert [r["Verbraucher"] for r in rows] == ["Grundlast", "Wärmepumpe"]
    assert [r["Kosten €"] for r in rows] == [0.1, 0.3]
    assert rows[1]["kWh"] == 0.75


_WINDOW_LABEL = "13.09.2026–20.09.2026 (7 Tage)"


def test_render_period_kpis_without_shares_skips_table(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(charts, "st", fake)
    series = CostAnalysisSeries(slots=(), consumer_labels={}, data_start=None, data_end=None)
    charts.render_period_kpis(series, window_slots=[], window=_WINDOW, now=datetime(2026, 9, 20))
    assert ("caption", ("Keine Produktiv-Log-Daten.",), {}) in fake.calls
    assert not [c for c in fake.calls if c[0] == "dataframe"]


def test_render_window_analysis_empty_window_shows_info(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(charts, "st", fake)
    series = CostAnalysisSeries(
        slots=(_slot(10),),
        consumer_labels=_LABELS,
        data_start=datetime(2026, 9, 19, 10),
        data_end=datetime(2026, 9, 19, 10),
    )
    far = TimeWindow(start=datetime(2026, 1, 1), end=datetime(2026, 1, 8), kind=PeriodKind.ROLLING_7)
    charts.render_window_analysis(series, window=far, now=datetime(2026, 9, 20))
    assert fake.calls == [("info", ("Keine Log-Slots für 01.01.2026–08.01.2026 (7 Tage).",), {})]


def test_render_window_analysis_draws_four_charts_and_battery_caption(monkeypatch):
    fake = _FakeSt()
    monkeypatch.setattr(charts, "st", fake)
    monkeypatch.setattr(charts, "_consumers_by_id", lambda: {})
    monkeypatch.setattr(
        charts.config, "get_battery_params", lambda: {"efficiency": 0.9, "standby_power_kw": 0.0}
    )
    series = CostAnalysisSeries(
        slots=(_slot(10), _slot(11)),
        consumer_labels=_LABELS,
        data_start=datetime(2026, 9, 19, 10),
        data_end=datetime(2026, 9, 19, 11),
    )
    charts.render_window_analysis(series, window=_WINDOW, now=datetime(2026, 9, 20))
    figs = [c[1][0] for c in fake.calls if c[0] == "plotly_chart"]
    titles = [json.loads(f.to_json())["layout"]["title"]["text"] for f in figs]
    assert len(figs) == 4
    assert [t.split(" — ")[0] for t in titles[1:]] == [
        "Herkunft je Verbraucher",
        "Kosten (nur Netzanteil)",
        "Batterie-Energieflüsse",
    ]
    assert all(t.endswith(_WINDOW_LABEL) for t in titles[1:])
    captions = [c[1][0] for c in fake.calls if c[0] == "caption"]
    assert any(c.startswith("Datengrundlage") for c in captions)
    assert captions[-1].startswith("Laden ")


# --- consumption_display.period --------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "days"),
    [(PeriodKind.ROLLING_7, 7), (PeriodKind.ROLLING_28, 28), (PeriodKind.ROLLING_365, 365)],
)
def test_rolling_days(kind, days):
    assert rolling_days(kind) == days


def test_rolling_days_rejects_iso_week():
    with pytest.raises(ValueError, match="not a rolling window"):
        rolling_days(PeriodKind.ISO_WEEK)


def test_list_rolling_windows_for_kind_steps_back_from_latest():
    stamps = [
        (datetime(2026, 9, 1, 12) + timedelta(days=i)).isoformat() for i in range(15)
    ]  # 01.09. … 15.09.
    windows = list_rolling_windows_for_kind(stamps, PeriodKind.ROLLING_7)
    assert [(w.start.date(), w.end.date()) for w in windows] == [
        (date(2026, 8, 25), date(2026, 9, 1)),
        (date(2026, 9, 1), date(2026, 9, 8)),
        (date(2026, 9, 8), date(2026, 9, 15)),
    ]
    assert {w.kind for w in windows} == {PeriodKind.ROLLING_7}
    bounded = list_rolling_windows_for_kind(
        stamps,
        PeriodKind.ROLLING_7,
        nav_bounds=(datetime(2026, 9, 10), datetime(2026, 9, 12, 23)),
    )
    assert [w.end for w in bounded] == [datetime(2026, 9, 12, 12)]
    with pytest.raises(ValueError):
        list_rolling_windows_for_kind(stamps, PeriodKind.ISO_WEEK)


def test_window_containing_date_first_match_or_none():
    w1 = TimeWindow(datetime(2026, 9, 1), datetime(2026, 9, 8), PeriodKind.ROLLING_7)
    w2 = TimeWindow(datetime(2026, 9, 8), datetime(2026, 9, 15), PeriodKind.ROLLING_7)
    assert window_containing_date([w1, w2], date(2026, 9, 3)) is w1
    assert window_containing_date([w1, w2], date(2026, 9, 8)) is w1  # shared boundary day
    assert window_containing_date([w1, w2], date(2026, 9, 15)) is w2
    assert window_containing_date([w1, w2], date(2026, 9, 16)) is None
    assert window_containing_date([], date(2026, 9, 3)) is None


# --- sankey ------------------------------------------------------------------------------


def test_house_sankey_without_breakdown_routes_via_system_node():
    data = {"pv": 3.0, "grid": -1.0, "battery": 0.5, "house": 2.5}
    labels, links, colors = sankey._prepare_sankey_data(data, 60.0)
    assert len(labels) == len(colors) == 5
    assert labels[3].startswith("🏠 Wohnhaus (2")
    assert labels[4] == "⚙️ System-Knoten"
    flows = {(s, t): v for s, t, v in zip(links.sources, links.targets, links.values)}
    assert flows == {(0, 4): 3.0, (2, 4): 0.5, (4, 3): 2.5, (4, 1): 1.0}
    assert colors[0] == sankey.SANKEY_NODE_PV and colors[3] == sankey.SANKEY_NODE_HOUSE
    assert any(h.startswith("Netz Einspeisung") for h in links.hover)


def test_house_sankey_grid_import_and_battery_charge():
    data = {"pv": 0.0, "grid": 3.0, "battery": -1.0, "house": 2.0}
    _labels, links, _colors = sankey._prepare_sankey_data(data, 40.0)
    flows = {(s, t): v for s, t, v in zip(links.sources, links.targets, links.values)}
    assert flows == {(1, 4): 3.0, (4, 3): 2.0, (4, 2): 1.0}
    assert any(h.startswith("Batterie Laden") for h in links.hover)


def test_house_sankey_skips_tiny_flows():
    data = {"pv": 0.0, "grid": 0.0, "battery": -0.0, "house": 0.0}
    _labels, links, _colors = sankey._prepare_sankey_data(data, None)
    assert links.values == []


def test_sankey_breakdown_consumers_adds_metered_known_generics(monkeypatch):
    import house_config.known_chart_display as known_display
    import integrations.ehal_live as ehal_live
    import simulation.engine as engine

    flex = [{"id": "wp", "chart_color_index": 2}, {"id": "ev"}]
    seen_used: list[set[int]] = []

    def _known(used_color_indices):
        seen_used.append(set(used_color_indices))
        return [
            {"id": "pool", "chart_color_index": 4},  # metered → added
            {"id": "sauna", "chart_color_index": 5},  # no meter → skipped
            {"id": "wp", "chart_color_index": 6},  # already flex → skipped
            {"id": "", "chart_color_index": 7},  # no id → skipped
            {"id": "teich", "chart_color_index": "x"},  # metered, bad index kept out of used
        ]

    monkeypatch.setattr(sankey.config, "get_resolved_runtime_settings", lambda: {})
    monkeypatch.setattr(engine, "resolved_flexible_consumers", lambda settings, optimizer_only: list(flex))
    monkeypatch.setattr(
        ehal_live,
        "house_profile_power_consumers",
        lambda: [{"id": "pool"}, {"id": "teich"}, {"id": "wp"}, {"id": ""}],
    )
    monkeypatch.setattr(known_display, "chart_known_generics", _known)

    consumers = sankey._sankey_breakdown_consumers()
    assert [c["id"] for c in consumers] == ["wp", "ev", "pool", "teich"]
    assert seen_used == [{2}]  # colour indices of the flex consumers


# --- support_package ---------------------------------------------------------------------


def test_remember_live_soc_stores_value_in_session(monkeypatch):
    fake = SimpleNamespace(session_state={})
    monkeypatch.setattr(support_package, "st", fake)
    support_package.remember_live_soc(57.5)
    assert fake.session_state["support_package_live_soc"] == 57.5
    support_package.remember_live_soc(None)
    assert fake.session_state["support_package_live_soc"] is None


def test_session_meta_collects_cache_key_and_s2_navigation(monkeypatch):
    monkeypatch.setattr(
        support_package, "st", SimpleNamespace(session_state={"live_optimization_cache_key": "k1"})
    )
    monkeypatch.setattr(support_package, "get_s2_cycle_offset", lambda: 2)
    monkeypatch.setattr(support_package, "get_s2_segment_index", lambda: 1)
    monkeypatch.setattr(support_package, "get_s2_span", lambda: "segment")
    assert support_package._session_meta() == {
        "live_optimization_cache_key": "k1",
        "s2_cycle_offset": 2,
        "s2_segment_index": 1,
        "s2_span": "segment",
    }


def _bundle(chart_context):
    return SimpleNamespace(
        display_df="display",
        baseline_df="baseline",
        display_matched=True,
        chart_context=chart_context,
        chart_zones=["z"],
        sun_markers=["s"],
        chart_qualities=["q"],
        history_slot_count=4,
        chart_header_label="Kopf",
        slot_deviation_events=[],
        optimization_matrix=[{"m": 1}],
    )


def test_chart1_plotly_json_passes_bundle_and_chart_context(monkeypatch):
    calls = []

    def _figure(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(to_json=lambda: '{"ok": true}')

    monkeypatch.setattr(support_package, "build_power_soc_chart_figure", _figure)
    ctx = SimpleNamespace(zone_reference="NOW", chart_window="WIN")
    assert support_package._chart1_plotly_json(_bundle(ctx)) == '{"ok": true}'
    args, kwargs = calls[0]
    assert args == ("display", "baseline", True)
    assert kwargs["chart_now"] == "NOW" and kwargs["chart_window"] == "WIN"
    assert kwargs["history_slot_count"] == 4 and kwargs["battery_params"] is None

    assert support_package._chart1_plotly_json(_bundle(None)) == '{"ok": true}'
    assert calls[1][1]["chart_now"] is None and calls[1][1]["chart_window"] is None


def test_chart1_plotly_json_returns_none_and_logs_on_error(monkeypatch, caplog):
    def _boom(*_a, **_k):
        raise RuntimeError("kaputt")

    monkeypatch.setattr(support_package, "build_power_soc_chart_figure", _boom)
    with caplog.at_level("WARNING", logger="app"):
        assert support_package._chart1_plotly_json(_bundle(None)) is None
    assert "kaputt" in caplog.text


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("C:\\Users\\x\\dumps\\earnie_debug_1.zip", "earnie_debug_1.zip"),
        ("/var/lib/earnie/dumps/earnie_debug_2.zip", "earnie_debug_2.zip"),
        ("C:/mixed\\sep/earnie_debug_3.zip", "earnie_debug_3.zip"),
        ("plain.zip", "plain.zip"),
    ],
)
def test_zip_file_name_strips_any_directory(path, name):
    assert support_package._zip_file_name(path) == name
