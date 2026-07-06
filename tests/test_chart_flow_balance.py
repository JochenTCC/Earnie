"""Tests für Chart-1-Rauf/Runter-Energiebilanz (ui.chart_flow_balance)."""
from __future__ import annotations

import pytest

from scripts.flow_balance_test_data import (
    FlowBalanceScenario,
    flow_balance_flex_pairs,
    flow_balance_scenario_dataframe,
    flow_balance_scenario_rows,
)
from ui.chart_flow_balance import (
    COLOR_BASELOAD,
    COLOR_GRID_IMPORT,
    COLOR_PV,
    FLOW_BALANCE_TRACE_ORDER,
    KIND_BATTERY_CHARGE_GRID,
    KIND_BATTERY_CHARGE_PV,
    KIND_BATTERY_DISCHARGE_LOAD,
    KIND_EXPORT_BATTERY,
    KIND_BASELOAD,
    KIND_EXPORT_PV,
    KIND_FLEX,
    KIND_GRID_IMPORT,
    KIND_PV,
    MUTED_BATTERY_CHARGE_GRID,
    MUTED_BATTERY_CHARGE_PV,
    MUTED_BATTERY_EXPORT,
    MUTED_BATTERY_LOAD,
    MUTED_EXPORT_PV,
    blend_hsl,
    build_flow_balance_segments,
    build_flow_balance_slots_from_df,
    energy_balance_residual_kw,
    flow_balance_plotly_trace_specs,
    flow_balance_plotly_traces,
    hsl,
)
from ui.charts import ChartSlotAxis


def _flex_pairs() -> list[tuple[dict, str]]:
    return flow_balance_flex_pairs()


@pytest.fixture
def flow_balance_scenarios() -> tuple[FlowBalanceScenario, ...]:
    return flow_balance_scenario_rows()


@pytest.fixture
def flow_balance_df():
    return flow_balance_scenario_dataframe()


@pytest.mark.parametrize(
    "scenario_id",
    [scenario.scenario_id for scenario in flow_balance_scenario_rows()],
)
def test_flow_balance_scenario_dataset(scenario_id: str) -> None:
    scenario = next(item for item in flow_balance_scenario_rows() if item.scenario_id == scenario_id)
    slot = build_flow_balance_segments(scenario.row, flex_consumers=_flex_pairs())

    assert slot.offset_kw == pytest.approx(scenario.offset_kw)
    assert tuple(segment.kind for segment in slot.up) == scenario.kinds_up
    assert tuple(segment.kind for segment in slot.down) == scenario.kinds_down
    assert slot.is_visually_balanced
    assert slot.up_total_kw == pytest.approx(slot.down_total_kw)
    if scenario.balanced:
        assert abs(energy_balance_residual_kw(scenario.row)) < 1e-6


def test_scenario_dataset_covers_core_trace_kinds(flow_balance_scenarios) -> None:
    kinds_seen: set[str] = set()
    for scenario in flow_balance_scenarios:
        slot = build_flow_balance_segments(scenario.row, flex_consumers=_flex_pairs())
        for segment in (*slot.up, *slot.down):
            kinds_seen.add(segment.kind)

    assert KIND_PV in kinds_seen
    assert KIND_GRID_IMPORT in kinds_seen
    assert KIND_EXPORT_PV in kinds_seen
    assert KIND_BASELOAD in kinds_seen
    assert KIND_FLEX in kinds_seen
    assert KIND_BATTERY_CHARGE_PV in kinds_seen
    assert KIND_BATTERY_DISCHARGE_LOAD in kinds_seen


def test_trace_specs_balance_segments_on_opposite_side(flow_balance_df) -> None:
    flex = _flex_pairs()
    slots = build_flow_balance_slots_from_df(flow_balance_df, flex_consumers=flex)
    axis = ChartSlotAxis.from_dataframe(flow_balance_df)
    from ui.charts import _battery_bar_times

    x_values = list(_battery_bar_times(axis, slice(0, len(flow_balance_df))))
    specs = flow_balance_plotly_trace_specs(
        slots,
        x_values=x_values,
        uhrzeit=list(flow_balance_df["Uhrzeit"]),
        start=0,
        end=len(flow_balance_df),
        df=flow_balance_df,
        flex_consumers=flex,
        axis=axis,
    )
    by_kind = {spec.kind: spec for spec in specs}

    surplus = by_kind[KIND_EXPORT_PV]
    discharge = by_kind[KIND_BATTERY_DISCHARGE_LOAD]
    e_time = flow_balance_df.loc[flow_balance_df["scenario_id"] == "E", "Uhrzeit"].iloc[0]
    c_time = flow_balance_df.loc[flow_balance_df["scenario_id"] == "C", "Uhrzeit"].iloc[0]
    surplus_pos = next(index for index, cd in enumerate(surplus.customdata) if cd[0] == e_time)
    discharge_pos = next(index for index, cd in enumerate(discharge.customdata) if cd[0] == c_time)
    assert surplus.y[surplus_pos] == pytest.approx(-2.0)
    assert surplus.base[surplus_pos] == pytest.approx(-5.0)
    assert discharge.y[discharge_pos] == pytest.approx(4.0)
    assert discharge.base[discharge_pos] == pytest.approx(1.0)


def test_muted_balance_traces_use_lower_opacity(flow_balance_df) -> None:
    scenario_e = flow_balance_df.loc[flow_balance_df["scenario_id"] == "E"].reset_index(drop=True)
    flex = _flex_pairs()
    slots = build_flow_balance_slots_from_df(scenario_e, flex_consumers=flex)
    axis = ChartSlotAxis.from_dataframe(scenario_e)
    traces, _legend = flow_balance_plotly_traces(
        scenario_e,
        slots,
        axis,
        0,
        1,
        flex_consumers=flex,
    )
    by_name = {trace.name: trace for trace in traces}
    assert by_name["PV"].opacity > by_name["Einspeisung (PV)"].opacity


def test_hsl_converts_to_hex() -> None:
    assert hsl(0, 100, 50) == "#ff0000"
    assert hsl(0, 0, 100) == "#ffffff"


def test_flow_balance_base_colors_match_hsl_constants() -> None:
    from ui.chart_flow_balance import (
        _HSL_BASELOAD,
        _HSL_GRID_IMPORT,
        _HSL_PV,
    )

    assert hsl(*_HSL_PV) == COLOR_PV
    assert hsl(*_HSL_GRID_IMPORT) == COLOR_GRID_IMPORT
    assert hsl(*_HSL_BASELOAD) == COLOR_BASELOAD


def test_flow_balance_muted_colors_match_module_constants() -> None:
    from ui.chart_flow_balance import (
        _MUTED_BATTERY_CHARGE_GRID,
        _MUTED_BATTERY_CHARGE_PV,
        _MUTED_BATTERY_EXPORT,
        _MUTED_BATTERY_LOAD,
        _MUTED_EXPORT_PV,
    )

    assert MUTED_BATTERY_LOAD == _MUTED_BATTERY_LOAD
    assert MUTED_BATTERY_CHARGE_PV == _MUTED_BATTERY_CHARGE_PV
    assert MUTED_BATTERY_CHARGE_GRID == _MUTED_BATTERY_CHARGE_GRID
    assert MUTED_BATTERY_EXPORT == _MUTED_BATTERY_EXPORT
    assert MUTED_EXPORT_PV == _MUTED_EXPORT_PV


def test_blend_hsl_interpolates_hue_on_short_arc() -> None:
    assert blend_hsl((350.0, 100.0, 50.0), (10.0, 100.0, 50.0), 0.5) == "#ff0000"


def test_blend_hsl_l_delta_shifts_lightness() -> None:
    assert blend_hsl((0.0, 100.0, 50.0), (0.0, 100.0, 50.0), 0.5, l_delta=20.0) == hsl(
        0.0, 100.0, 70.0
    )
    assert blend_hsl((0.0, 100.0, 50.0), (0.0, 100.0, 50.0), 0.5, l_delta=-20.0) == hsl(
        0.0, 100.0, 30.0
    )
    assert blend_hsl((0.0, 100.0, 95.0), (0.0, 100.0, 95.0), 0.5, l_delta=10.0) == hsl(
        0.0, 100.0, 100.0
    )


def test_slots_from_dataframe_length(flow_balance_df) -> None:
    slots = build_flow_balance_slots_from_df(flow_balance_df, flex_consumers=_flex_pairs())
    assert len(slots) == len(flow_balance_df) == 8


@pytest.mark.parametrize(
    "scenario_id,kind,expected",
    [
        ("A", KIND_EXPORT_PV, MUTED_EXPORT_PV),
        ("B", KIND_BATTERY_CHARGE_PV, MUTED_BATTERY_CHARGE_PV),
        ("F", KIND_GRID_IMPORT, COLOR_GRID_IMPORT),
        ("F", KIND_BASELOAD, COLOR_BASELOAD),
        ("G", KIND_BATTERY_CHARGE_GRID, MUTED_BATTERY_CHARGE_GRID),
        ("C", KIND_BATTERY_DISCHARGE_LOAD, MUTED_BATTERY_LOAD),
    ],
)
def test_flow_balance_segment_colors(scenario_id: str, kind: str, expected: str) -> None:
    scenario = next(item for item in flow_balance_scenario_rows() if item.scenario_id == scenario_id)
    slot = build_flow_balance_segments(scenario.row, flex_consumers=_flex_pairs())
    segments = {segment.kind: segment for segment in (*slot.up, *slot.down)}
    assert segments[kind].color == expected


def test_battery_export_and_discharge_use_distinct_colors() -> None:
    row = {
        "PV-Prognose (kW)": 0.0,
        "Verbrauch-Prognose (kW)": 1.0,
        "SwimSpa (kW)": 0.0,
        "Geplante Batterie-Aktion (kW)": -5.0,
        "Netzbezug (kW)": -2.0,
    }
    slot = build_flow_balance_segments(row, flex_consumers=_flex_pairs())
    by_kind = {segment.kind: segment for segment in (*slot.up, *slot.down)}
    assert by_kind[KIND_BATTERY_DISCHARGE_LOAD].color == MUTED_BATTERY_LOAD
    assert by_kind[KIND_EXPORT_BATTERY].color == MUTED_BATTERY_EXPORT
    assert by_kind[KIND_BATTERY_DISCHARGE_LOAD].color != by_kind[KIND_EXPORT_BATTERY].color
    assert MUTED_BATTERY_CHARGE_PV != COLOR_PV
    assert MUTED_BATTERY_CHARGE_GRID != MUTED_BATTERY_EXPORT
    assert MUTED_BATTERY_CHARGE_PV != MUTED_BATTERY_CHARGE_GRID
    assert MUTED_EXPORT_PV != COLOR_PV


def test_trace_order_constant_covers_all_kinds() -> None:
    assert KIND_BATTERY_DISCHARGE_LOAD in FLOW_BALANCE_TRACE_ORDER
    assert FLOW_BALANCE_TRACE_ORDER.index(KIND_BASELOAD) < FLOW_BALANCE_TRACE_ORDER.index(KIND_PV)


def test_flow_balance_trace_specs_use_sliced_x_axis(flow_balance_df) -> None:
    """Regression: Segment [start:end) liefert x/uhrzeit gesliced — kein IndexError."""
    flex = _flex_pairs()
    slots = build_flow_balance_slots_from_df(flow_balance_df, flex_consumers=flex)
    axis = ChartSlotAxis.from_dataframe(flow_balance_df)
    from ui.charts import _battery_bar_times

    start, end = 3, 6
    specs = flow_balance_plotly_trace_specs(
        slots,
        x_values=list(_battery_bar_times(axis, slice(start, end))),
        uhrzeit=list(flow_balance_df["Uhrzeit"].iloc[start:end]),
        start=start,
        end=end,
        df=flow_balance_df,
        flex_consumers=flex,
        axis=axis,
    )
    assert specs
    pv_spec = next(spec for spec in specs if spec.kind == KIND_PV)
    assert 1 <= len(pv_spec.x) <= end - start


def test_build_power_soc_chart_flow_balance_with_extrapolation_split() -> None:
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import pandas as pd
    import plotly.graph_objects as go

    from ui.charts import build_power_soc_chart_figure

    tz = ZoneInfo("Europe/Vienna")
    slots = [datetime(2026, 7, 6, 8, 0, tzinfo=tz) + timedelta(hours=index) for index in range(6)]
    df = pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "PV-Prognose (kW)": [4.0] * 6,
            "Verbrauch-Prognose (kW)": [1.0] * 6,
            "Geplante Batterie-Aktion (kW)": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Netzbezug (kW)": [-2.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "Steuerbefehl": ["IDLE"] * 6,
            "Simulierter SoC (%)": [50.0] * 6,
            "Preis extrapoliert": [False, False, False, True, True, True],
        }
    )
    fig = build_power_soc_chart_figure(df, show_baseline_soc=False)
    export_traces = [
        trace for trace in fig.data if isinstance(trace, go.Bar) and trace.name == "Einspeisung (PV)"
    ]
    assert export_traces
    assert any(len(trace.x) >= 1 for trace in export_traces)


def test_flow_balance_bar_widths_follow_per_slot_resolution() -> None:
    """Jeder Balkenpunkt bekommt die Breite seines Slots (15 min vs. 1 h)."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    import pandas as pd
    import plotly.graph_objects as go

    tz = ZoneInfo("Europe/Vienna")
    quarters = [datetime(2026, 7, 6, 6, minute, tzinfo=tz) for minute in (0, 15, 30, 45)]
    hours = [datetime(2026, 7, 6, hour, 0, tzinfo=tz) for hour in range(7, 10)]
    slots = quarters + hours
    df = pd.DataFrame(
        {
            "slot_datetime": slots,
            "Uhrzeit": [slot.strftime("%d.%m. %H:%M") for slot in slots],
            "PV-Prognose (kW)": [2.0] * len(slots),
            "Verbrauch-Prognose (kW)": [1.0] * len(slots),
            "Geplante Batterie-Aktion (kW)": [0.0] * len(slots),
            "Netzbezug (kW)": [-1.0] * len(slots),
            "Steuerbefehl": ["IDLE"] * len(slots),
            "SwimSpa (kW)": [0.0] * len(slots),
        }
    )
    axis = ChartSlotAxis.from_dataframe(df)
    flex = _flex_pairs()
    slot_models = build_flow_balance_slots_from_df(df, flex_consumers=flex)
    traces, _ = flow_balance_plotly_traces(df, slot_models, axis, 0, len(df), flex_consumers=flex)
    quarter_ms = 15 * 60 * 1000 * 0.9
    hour_ms = 60 * 60 * 1000 * 0.9
    pv_trace = next(t for t in traces if isinstance(t, go.Bar) and t.name == "PV")
    assert len(pv_trace.width) == len(pv_trace.x)
    assert pv_trace.width[0] == quarter_ms
    assert pv_trace.width[3] == quarter_ms
    assert pv_trace.width[4] == hour_ms
    baseload = next(t for t in traces if isinstance(t, go.Bar) and t.name == "Grundlast")
    assert baseload.width[4] == hour_ms
