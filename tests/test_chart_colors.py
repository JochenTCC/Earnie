"""Tests für zentrale Chart-Farben (ui.chart_colors)."""
from __future__ import annotations

import pytest

from ui.chart_colors import (
    CHART_PV_LINE_COLOR,
    CHART1_BASELOAD_LUMINANCE_MUTED,
    CHART1_BASELOAD_SATURATION_MUTED,
    CHART1_PV_LUMINANCE_MUTED,
    CHART1_PV_SATURATION_MUTED,
    CHART_ZONE_FORECAST_FILL,
    CHART_ZONE_HISTORY_FILL,
    COLOR_BASELOAD,
    COLOR_COST_ACTUAL,
    COLOR_COST_BASELINE,
    COLOR_COST_OPTIMIZED,
    COLOR_COST_SAVINGS,
    COLOR_COST_SAVINGS_NEGATIVE,
    COLOR_GRID_IMPORT,
    COLOR_GRID_POWER,
    COLOR_PV,
    COLOR_SOC,
    CONSUMER_PALETTE,
    CONSUMER_PALETTE_HUES,
    CONSUMER_PALETTE_SIZE,
    CONSUMER_CHART_SATURATION_MUTED,
    MUTED_BATTERY_CHARGE_GRID,
    MUTED_BATTERY_CHARGE_PV,
    MUTED_BATTERY_EXPORT,
    MUTED_BATTERY_LOAD,
    MUTED_EXPORT_PV,
    _HSL_BASELOAD,
    _HSL_COST_ACTUAL,
    _HSL_COST_BASELINE,
    _HSL_COST_OPTIMIZED,
    _HSL_COST_SAVINGS,
    _HSL_COST_SAVINGS_NEGATIVE,
    _HSL_GRID_IMPORT,
    _HSL_PV,
    _HSL_SOC,
    blend_hsl,
    chart1_baseload_color_for_zone,
    chart1_pv_color_for_zone,
    color_from_hsl,
    consumer_chart_color,
    consumer_chart_saturation_for_zone,
    consumer_palette_color,
    hsl,
    rgba_from_hsl,
)


def test_rgba_from_hsl_matches_hsl_hex() -> None:
    assert rgba_from_hsl(0, 100, 50, 0.5) == "rgba(255, 0, 0, 0.5)"


def test_color_from_hsl_uses_hex_when_alpha_one() -> None:
    assert color_from_hsl(0, 100, 50) == "#ff0000"
    assert color_from_hsl(0, 100, 50, 1.0) == "#ff0000"


def test_color_from_hsl_uses_rgba_when_alpha_below_one() -> None:
    assert color_from_hsl(0, 100, 50, 0.5) == "rgba(255, 0, 0, 0.5)"


def test_zone_fills_use_central_constants() -> None:
    assert CHART_ZONE_HISTORY_FILL.startswith("rgba(")
    assert CHART_ZONE_FORECAST_FILL.startswith("rgba(")
    assert CHART_ZONE_HISTORY_FILL != CHART_ZONE_FORECAST_FILL


def test_hsl_converts_to_hex() -> None:
    assert hsl(0, 100, 50) == "#ff0000"
    assert hsl(0, 0, 100) == "#ffffff"


def test_flow_balance_base_colors_match_hsl_constants() -> None:
    assert color_from_hsl(*_HSL_PV) == COLOR_PV
    assert color_from_hsl(*_HSL_GRID_IMPORT) == COLOR_GRID_IMPORT
    assert color_from_hsl(*_HSL_BASELOAD) == COLOR_BASELOAD


def test_flow_balance_muted_colors_are_stable() -> None:
    assert MUTED_BATTERY_LOAD == blend_hsl((120.0, 100.0, 50.0), (0.0, 0.0, 100.0), 0.1, 25.0)
    assert MUTED_BATTERY_CHARGE_PV == blend_hsl((60.0, 90.0, 50.0), (120.0, 100.0, 50.0), 0.5, 25.0)
    assert MUTED_BATTERY_CHARGE_GRID == blend_hsl((120.0, 100.0, 50.0), (240.0, 90.0, 50.0), 0.6, 35.0)
    assert MUTED_BATTERY_EXPORT == blend_hsl((120.0, 100.0, 50.0), (240.0, 90.0, 50.0), 0.5, 0.8)
    assert MUTED_EXPORT_PV == blend_hsl((60.0, 90.0, 50.0), (0.0, 0.0, 100.0), 0.1, 25.0)


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


def test_chart1_pv_line_matches_balance_bar_color() -> None:
    assert CHART_PV_LINE_COLOR != COLOR_PV
    assert CHART_PV_LINE_COLOR == color_from_hsl(_HSL_PV[0], _HSL_PV[1], 45.0)


def test_chart1_soc_color_from_hsl_constant() -> None:
    assert COLOR_SOC == color_from_hsl(*_HSL_SOC)


def test_chart2_cost_colors_from_hsl_constants() -> None:
    assert COLOR_COST_BASELINE == color_from_hsl(*_HSL_COST_BASELINE)
    assert COLOR_COST_OPTIMIZED == color_from_hsl(*_HSL_COST_OPTIMIZED)
    assert COLOR_COST_ACTUAL == color_from_hsl(*_HSL_COST_ACTUAL)
    assert COLOR_COST_SAVINGS == color_from_hsl(*_HSL_COST_SAVINGS)
    assert COLOR_COST_SAVINGS_NEGATIVE == color_from_hsl(*_HSL_COST_SAVINGS_NEGATIVE)
    assert COLOR_GRID_POWER == COLOR_COST_BASELINE


def test_consumer_palette_has_eight_distinct_hues() -> None:
    assert len(CONSUMER_PALETTE) == CONSUMER_PALETTE_SIZE == 8
    assert len(CONSUMER_PALETTE_HUES) == 8
    assert CONSUMER_PALETTE_HUES[0] == pytest.approx(260.0)
    assert CONSUMER_PALETTE_HUES[-1] == pytest.approx(40.0)
    assert len(set(CONSUMER_PALETTE)) == 8


def test_consumer_palette_color_matches_precomputed_palette() -> None:
    for index, color in enumerate(CONSUMER_PALETTE):
        assert consumer_palette_color(index) == color


def test_consumer_palette_rejects_out_of_range_index() -> None:
    with pytest.raises(ValueError, match="chart_color_index"):
        consumer_palette_color(-1)
    with pytest.raises(ValueError, match="chart_color_index"):
        consumer_palette_color(8)


def test_consumer_chart_color_reads_index_from_config() -> None:
    consumer = {"id": "eauto", "chart_color_index": 2}
    assert consumer_chart_color(consumer) == CONSUMER_PALETTE[2]


def test_consumer_chart_color_requires_index() -> None:
    with pytest.raises(ValueError, match="chart_color_index fehlt"):
        consumer_chart_color({"id": "swimspa"})


def test_consumer_chart_saturation_for_zone() -> None:
    assert consumer_chart_saturation_for_zone("history") == 1.0
    assert consumer_chart_saturation_for_zone("live_plan") == pytest.approx(
        CONSUMER_CHART_SATURATION_MUTED
    )
    assert consumer_chart_saturation_for_zone("forecast") == pytest.approx(
        CONSUMER_CHART_SATURATION_MUTED
    )


def test_chart1_pv_and_baseload_colors_are_muted_outside_history() -> None:
    assert chart1_pv_color_for_zone("history") == COLOR_PV
    assert chart1_baseload_color_for_zone("history") == COLOR_BASELOAD
    assert CHART1_PV_SATURATION_MUTED == CONSUMER_CHART_SATURATION_MUTED
    assert CHART1_BASELOAD_SATURATION_MUTED == CONSUMER_CHART_SATURATION_MUTED
    assert CHART1_PV_LUMINANCE_MUTED > 0.0
    assert CHART1_BASELOAD_LUMINANCE_MUTED > 0.0
    assert chart1_pv_color_for_zone("forecast") != COLOR_PV
    assert chart1_baseload_color_for_zone("live_plan") != COLOR_BASELOAD
