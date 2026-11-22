"""Coverage: chart helpers that no other test executed (pure functions, no Streamlit run)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from data.planning_window import UiChartWindow
from ui.chart_consumer_stack import chart_flex_consumers_context
from ui.chart_decorations import _power_chart_ymax, _sunrise_chart_title
from ui.chart_flow_traces import _flex_legend_placeholder_traces
from ui.chart_slot_axis import ChartSlotAxis, _slot_index_at_or_after, _slot_time_in_chart
from ui.chart_trace_segments import _segment_hover_labels
from ui.flow_balance_allocate import FlowAllocation, allocate_slot_flows

_TZ = ZoneInfo("Europe/Vienna")


def _window(
    start: datetime, end: datetime, slots: tuple[datetime, ...] = ()
) -> UiChartWindow:
    return UiChartWindow(
        start=start,
        end=end,
        sa0=start,
        sa1=end,
        sa2=end + timedelta(days=1),
        segment_index=0,
        slot_datetimes=slots,
    )


# --- chart_decorations -----------------------------------------------------------------


def test_sunrise_chart_title_shows_both_window_ends() -> None:
    window = _window(
        datetime(2026, 7, 5, 5, 12, tzinfo=_TZ), datetime(2026, 7, 6, 5, 13, tzinfo=_TZ)
    )
    assert _sunrise_chart_title(window) == (
        "Sonnenaufgang→Sonnenaufgang (05.07.2026 05:12 – 06.07.2026 05:13)"
    )


def test_power_chart_ymax_takes_the_largest_absolute_power_incl_flex_columns() -> None:
    df = pd.DataFrame(
        {
            "PV-Prognose (kW)": [1.0, 2.5],
            "Geplante Batterie-Aktion (kW)": [-3.2, 0.0],  # discharge counts by magnitude
            "Netzbezug (kW)": ["x", None],  # non-numeric is ignored
            "Pool (kW)": [4.4, 0.1],
            "Unrelated (kW)": [99.0, 99.0],  # not a chart power column
        }
    )
    with chart_flex_consumers_context([{"name": "Pool"}]):
        assert _power_chart_ymax(df) == pytest.approx(4.4)
    with chart_flex_consumers_context([]):
        assert _power_chart_ymax(df) == pytest.approx(3.2)


def test_power_chart_ymax_has_a_floor_for_empty_or_flat_charts() -> None:
    with chart_flex_consumers_context([]):
        assert _power_chart_ymax(pd.DataFrame()) == 0.5
        assert _power_chart_ymax(pd.DataFrame({"PV-Prognose (kW)": [0.1, 0.0]})) == 0.5
        assert _power_chart_ymax(pd.DataFrame({"PV-Prognose (kW)": []})) == 0.5


# --- chart_flow_traces -----------------------------------------------------------------


def test_flex_legend_placeholders_only_for_groups_not_yet_shown() -> None:
    shown = {"flex_pool"}
    traces = _flex_legend_placeholder_traces(
        {"flex_pool": ("Pool", "#111111"), "flex_ev": ("E-Auto", "#222222")},
        shown,
    )
    assert [trace.name for trace in traces] == ["E-Auto"]
    trace = traces[0]
    assert trace.legendgroup == "flex_ev"
    assert trace.marker.color == "#222222"
    assert trace.visible == "legendonly"
    assert trace.showlegend is True
    assert list(trace.x) == [None]
    assert shown == {"flex_pool", "flex_ev"}  # extended in place
    # Second call: everything already shown -> nothing new.
    assert _flex_legend_placeholder_traces({"flex_ev": ("E-Auto", "#222222")}, shown) == []


# --- chart_slot_axis -------------------------------------------------------------------


def test_slot_time_in_chart_normalizes_to_the_quarter_hour_slot() -> None:
    slots = tuple(datetime(2026, 7, 5, 10, 0, tzinfo=_TZ) + timedelta(minutes=15 * i) for i in range(4))
    assert _slot_time_in_chart(slots, datetime(2026, 7, 5, 10, 22, tzinfo=_TZ)) == slots[1]
    assert _slot_time_in_chart(slots, slots[3]) == slots[3]
    # Outside the chart -> None; empty axis -> None.
    assert _slot_time_in_chart(slots, datetime(2026, 7, 5, 12, 0, tzinfo=_TZ)) is None
    assert _slot_time_in_chart((), slots[0]) is None


def test_slot_time_in_chart_falls_back_to_an_exact_off_grid_slot() -> None:
    off_grid = datetime(2026, 7, 5, 10, 7, tzinfo=_TZ)
    slots = (datetime(2026, 7, 5, 9, 0, tzinfo=_TZ), off_grid)
    assert _slot_time_in_chart(slots, off_grid) == off_grid


def test_slot_index_at_or_after() -> None:
    starts = [datetime(2026, 7, 5, 10, 0, tzinfo=_TZ) + timedelta(hours=i) for i in range(3)]
    axis = ChartSlotAxis.from_dataframe(pd.DataFrame({"slot_datetime": starts}))
    assert _slot_index_at_or_after(axis, starts[0] - timedelta(minutes=1)) == 0
    assert _slot_index_at_or_after(axis, starts[1]) == 1
    assert _slot_index_at_or_after(axis, starts[1] + timedelta(minutes=1)) == 2
    assert _slot_index_at_or_after(axis, starts[2] + timedelta(minutes=1)) is None


# --- chart_trace_segments --------------------------------------------------------------


_UHRZEIT = pd.Series(["10:00", "11:00", "12:00", "13:00"])


def test_segment_hover_labels_step_line_repeats_last_and_bridges_left() -> None:
    assert _segment_hover_labels(_UHRZEIT, 0, 2) == ["10:00", "11:00", "11:00"]
    assert _segment_hover_labels(_UHRZEIT, 1, 3) == ["10:00", "11:00", "12:00", "12:00"]
    assert _segment_hover_labels(_UHRZEIT, 1, 3, point_count=2) == ["10:00", "11:00"]


def test_segment_hover_labels_plain_line() -> None:
    assert _segment_hover_labels(_UHRZEIT, 0, 2, step_line=False) == ["10:00", "11:00"]
    assert _segment_hover_labels(_UHRZEIT, 2, 4, step_line=False) == [
        "11:00",
        "12:00",
        "13:00",
        "13:00",
    ]
    assert _segment_hover_labels(_UHRZEIT, 2, 4, step_line=False, point_count=3) == [
        "11:00",
        "12:00",
        "13:00",
    ]


def test_segment_hover_labels_empty_segment() -> None:
    assert _segment_hover_labels(_UHRZEIT, 2, 2) == []
    assert _segment_hover_labels(_UHRZEIT, 3, 1, step_line=False) == []


# --- flow_balance_allocate -------------------------------------------------------------


def test_flow_allocation_export_kw_sums_pv_and_battery_export() -> None:
    alloc = FlowAllocation(
        pv_to_load=0.0,
        grid_to_load=0.0,
        discharge_to_load=0.0,
        charge_from_pv=0.0,
        charge_from_grid=0.0,
        export_from_pv=1.25,
        export_from_battery=0.5,
    )
    assert alloc.export_kw == pytest.approx(1.75)


def test_allocated_pv_surplus_shows_up_as_export() -> None:
    alloc = allocate_slot_flows(
        pv=5.0,
        load_kw=1.0,
        battery_charge=1.0,
        battery_discharge=0.0,
        grid_import=0.0,
        grid_export=3.0,
    )
    assert alloc.export_kw == pytest.approx(3.0)
    assert alloc.load_kw + alloc.charge_kw + alloc.export_kw == pytest.approx(5.0)


# --- chart_context._milp_tail_context ---------------------------------------------------


def test_build_chart_display_context_at_sunrise_shows_only_the_milp_tail() -> None:
    """Live segment whose history ends at the window start: no log rows, only MILP rows."""
    from data.planning_window import UiChartZones
    from ui.chart_context import SLOT_MILP, LiveChartContext, build_chart_display_context

    start = datetime(2026, 7, 5, 5, 0, tzinfo=_TZ)
    end = start + timedelta(hours=4)
    window = _window(start, end, tuple(start + timedelta(hours=i) for i in range(4)))
    ctx = LiveChartContext(
        now=start,  # minute 0 -> hourly tail
        chart_window=window,
        zones=UiChartZones.__new__(UiChartZones),
        cycle_offset=0,
        segment_index=0,
        zone_reference=start,
    )
    rows = [
        {"slot_datetime": (start + timedelta(hours=i)).isoformat(), "Simulierter SoC (%)": 40.0 + i}
        for i in range(4)
    ]
    display = build_chart_display_context(ctx, rows)
    assert display.history_slot_count == 0
    assert display.history_result is None
    assert display.gap_notice is None
    assert display.slot_qualities and set(display.slot_qualities) == {SLOT_MILP}
    assert display.slot_datetimes[0] == start
    assert [row["Simulierter SoC (%)"] for row in display.rows][:2] == [40.0, 41.0]
