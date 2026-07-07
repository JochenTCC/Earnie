"""Tests für zentrale Chart-Farben (ui.chart_colors)."""
from __future__ import annotations

from ui.chart_colors import (
    CHART_PV_LINE_COLOR,
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
    SANKEY_FLEX_PALETTE,
    consumer_bar_palette,
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
    hsl,
    rgba_from_hsl,
)


def test_rgba_from_hsl_matches_hsl_hex() -> None:
    assert rgba_from_hsl(0, 100, 50, 0.5) == "rgba(255, 0, 0, 0.5)"


def test_zone_fills_use_central_constants() -> None:
    assert CHART_ZONE_HISTORY_FILL.startswith("rgba(")
    assert CHART_ZONE_FORECAST_FILL.startswith("rgba(")
    assert CHART_ZONE_HISTORY_FILL != CHART_ZONE_FORECAST_FILL


def test_hsl_converts_to_hex() -> None:
    assert hsl(0, 100, 50) == "#ff0000"
    assert hsl(0, 0, 100) == "#ffffff"


def test_flow_balance_base_colors_match_hsl_constants() -> None:
    assert hsl(*_HSL_PV) == COLOR_PV
    assert hsl(*_HSL_GRID_IMPORT) == COLOR_GRID_IMPORT
    assert hsl(*_HSL_BASELOAD) == COLOR_BASELOAD


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
    assert CHART_PV_LINE_COLOR == COLOR_PV


def test_chart1_soc_color_from_hsl_constant() -> None:
    assert COLOR_SOC == hsl(*_HSL_SOC)


def test_chart2_cost_colors_from_hsl_constants() -> None:
    assert COLOR_COST_BASELINE == hsl(*_HSL_COST_BASELINE)
    assert COLOR_COST_OPTIMIZED == hsl(*_HSL_COST_OPTIMIZED)
    assert COLOR_COST_ACTUAL == hsl(*_HSL_COST_ACTUAL)
    assert COLOR_COST_SAVINGS == hsl(*_HSL_COST_SAVINGS)
    assert COLOR_COST_SAVINGS_NEGATIVE == hsl(*_HSL_COST_SAVINGS_NEGATIVE)
    assert COLOR_GRID_POWER == COLOR_COST_BASELINE


def test_sankey_palette_uses_chart_cost_orange() -> None:
    assert SANKEY_FLEX_PALETTE[0] == COLOR_COST_OPTIMIZED


def test_consumer_bar_palette_interpolates_rgb() -> None:
    colors = consumer_bar_palette(3)
    assert len(colors) == 3
    assert colors[0] != colors[-1]
