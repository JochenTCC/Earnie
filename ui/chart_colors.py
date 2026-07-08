"""
Zentrale Chart-Farben und HSL-Hilfsfunktionen.

Manuell anpassen: ``_HSL_*``-Tripel und ``_ALPHA_*`` in den Farbdefinitionen;
abgeleitete ``COLOR_*`` / ``MUTED_*`` / ``CHART_ZONE_*_FILL`` werden daraus berechnet.

Aufbau: Hilfsfunktionen · Farbdefinitionen (Chart 1 → Chart 2 → Sankey).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# --- Hilfsfunktionen ----------------------------------------------------------


def hsl(h: float, s: float, l: float) -> str:
    """HSL → ``#RRGGBB`` (h: 0–360, s/l: 0–100)."""

    hue = h % 360.0
    sat = max(0.0, min(100.0, s)) / 100.0
    lig = max(0.0, min(100.0, l)) / 100.0

    if sat == 0.0:
        channel = round(lig * 255)
        return f"#{channel:02x}{channel:02x}{channel:02x}"

    def _hue_channel(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p

    q = lig * (1 + sat) if lig < 0.5 else lig + sat - lig * sat
    p = 2 * lig - q
    hk = hue / 360.0
    red = round(_hue_channel(p, q, hk + 1 / 3) * 255)
    green = round(_hue_channel(p, q, hk) * 255)
    blue = round(_hue_channel(p, q, hk - 1 / 3) * 255)
    return f"#{red:02x}{green:02x}{blue:02x}"


def rgba_from_hsl(h: float, s: float, l: float, alpha: float) -> str:
    """HSL + Alpha → Plotly-``rgba(r, g, b, a)``."""
    hex_color = hsl(h, s, l)
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    clamped_alpha = max(0.0, min(1.0, alpha))
    return f"rgba({red}, {green}, {blue}, {clamped_alpha})"


def color_from_hsl(h: float, s: float, l: float, alpha: float = 1.0) -> str:
    """HSL mit optionalem Alpha (Default 1.0 → ``#RRGGBB``, sonst ``rgba(...)``)."""
    if alpha >= 1.0:
        return hsl(h, s, l)
    return rgba_from_hsl(h, s, l, alpha)


def _lerp_hue(h_a: float, h_b: float, weight: float) -> float:
    """Farbton entlang des kürzesten Kreisbogens interpolieren."""
    delta = ((h_b - h_a + 180.0) % 360.0) - 180.0
    return (h_a + delta * weight) % 360.0


def blend_hsl(
    hsl_a: tuple[float, float, float],
    hsl_b: tuple[float, float, float],
    ratio_b: float,
    l_delta: float = 0.0,
) -> str:
    """
    Mischt zwei HSL-Tripel; ``ratio_b`` = Anteil von ``hsl_b`` (0…1).

    ``l_delta`` verschiebt die Lightness nach der Mischung in Prozentpunkten
    (positiv = heller, negativ = dunkler), begrenzt auf 0…100.
    """
    weight = max(0.0, min(1.0, ratio_b))
    hue = _lerp_hue(hsl_a[0], hsl_b[0], weight)
    sat = hsl_a[1] * (1.0 - weight) + hsl_b[1] * weight
    lig = hsl_a[2] * (1.0 - weight) + hsl_b[2] * weight
    lig = max(0.0, min(100.0, lig + l_delta))
    return hsl(hue, sat, lig)


# --- Chart 1 — Hintergrundzonen (SA₀→SA₁ / SA₁→SA₂) --------------------------


# Vergangenheit (Produktiv-Log): kühles neutrales Grau — Kontrast zu Gelb/Blau/Magenta.
_HSL_ZONE_HISTORY = (180.0, 10.0, 80.0)
_ALPHA_ZONE_HISTORY = 0.15

# Vorausschau (extrapolierte Preise): helles Gelb-Grün — bewusst nicht H=120 (Batterie).
_HSL_ZONE_FORECAST = (88.0, 40.0, 80.0)
_ALPHA_ZONE_FORECAST = 0.15

CHART_ZONE_HISTORY_FILL = color_from_hsl(*_HSL_ZONE_HISTORY, _ALPHA_ZONE_HISTORY)
CHART_ZONE_FORECAST_FILL = color_from_hsl(*_HSL_ZONE_FORECAST, _ALPHA_ZONE_FORECAST)


# --- Chart 1 — Energiebilanz-Balken (Rauf/Runter) -----------------------------


_HSL_PV = (60.0, 90.0, 50.0)
_ALPHA_PV = 1.0
_HSL_GRID = (240.0, 90.0, 50.0)
_ALPHA_GRID = 1.0
_HSL_GRID_IMPORT = (240.0, 80.0, 60.0)
_ALPHA_GRID_IMPORT = 1.0
_HSL_BASELOAD = (300.0, 60.0, 50.0)
_ALPHA_BASELOAD = 1.0
_HSL_BATTERY = (120.0, 100.0, 50.0)
_ALPHA_BATTERY = 1.0
_HSL_WHITE = (0.0, 0.0, 100.0)
_ALPHA_WHITE = 1.0

COLOR_PV = color_from_hsl(*_HSL_PV, _ALPHA_PV)
COLOR_GRID = color_from_hsl(*_HSL_GRID, _ALPHA_GRID)
COLOR_BASELOAD = color_from_hsl(*_HSL_BASELOAD, _ALPHA_BASELOAD)
COLOR_BATTERY = color_from_hsl(*_HSL_BATTERY, _ALPHA_BATTERY)
COLOR_GRID_IMPORT = color_from_hsl(*_HSL_GRID_IMPORT, _ALPHA_GRID_IMPORT)

# Gedämpfte Bilanz-Segmente (Opacity in ``chart_flow_balance._MUTED_BAR_OPACITY``).
MUTED_BATTERY_LOAD = blend_hsl(_HSL_BATTERY, _HSL_WHITE, 0.1, 25.0)
MUTED_BATTERY_CHARGE_PV = blend_hsl(_HSL_PV, _HSL_BATTERY, 0.5, 25.0)
MUTED_BATTERY_CHARGE_GRID = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.6, 35.0)
MUTED_BATTERY_EXPORT = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.5, 0.8)
MUTED_EXPORT_PV = blend_hsl(_HSL_PV, _HSL_WHITE, 0.1, 25.0)


# --- Chart 1 — Linien & Overlays ----------------------------------------------


_HSL_SOC = (120.0, 90.0, 40.0)
_ALPHA_SOC = 1.0
COLOR_SOC = color_from_hsl(*_HSL_SOC, _ALPHA_SOC)

_ALPHA_PV_LINE_FILL = 0.15
CHART_PV_LINE_COLOR = color_from_hsl(_HSL_PV[0], _HSL_PV[1], 45.0)
CHART_PV_FILL_COLOR = color_from_hsl(*_HSL_PV, _ALPHA_PV_LINE_FILL)

_HSL_MARKER_NOW = (204.0, 62.0, 58.0)
_ALPHA_MARKER_NOW = 1.0
_HSL_MARKER_SUNRISE = (37.0, 90.0, 52.0)
_ALPHA_MARKER_SUNRISE = 1.0
CHART_MARKER_NOW_COLOR = color_from_hsl(*_HSL_MARKER_NOW, _ALPHA_MARKER_NOW)
CHART_MARKER_SUNRISE_COLOR = color_from_hsl(*_HSL_MARKER_SUNRISE, _ALPHA_MARKER_SUNRISE)

_HSL_MISSING_SLOT = (33.0, 100.0, 85.0)
_ALPHA_MISSING_SLOT = 0.55
CHART_MISSING_SLOT_FILL = color_from_hsl(*_HSL_MISSING_SLOT, _ALPHA_MISSING_SLOT)

CHART_ENTLADESPERRE_BAND_FILL = COLOR_PV
_HSL_ENTLADESPERRE_STRIPE = (0.0, 0.0, 10.0)
_ALPHA_ENTLADESPERRE_STRIPE = 1.0
CHART_ENTLADESPERRE_BAND_STRIPE = color_from_hsl(
    *_HSL_ENTLADESPERRE_STRIPE,
    _ALPHA_ENTLADESPERRE_STRIPE,
)


# --- Chart 1 — Legacy-Batterie-Balken (Steuerbefehl) --------------------------


COLOR_STEER_FORCE_CHARGE = COLOR_BATTERY
_HSL_STEER_FORCE_DISCHARGE = (348.0, 83.0, 47.0)
_ALPHA_STEER_FORCE_DISCHARGE = 1.0
COLOR_STEER_FORCE_DISCHARGE = color_from_hsl(
    *_HSL_STEER_FORCE_DISCHARGE,
    _ALPHA_STEER_FORCE_DISCHARGE,
)
_HSL_STEER_ENTLADESPERRE = (33.0, 100.0, 50.0)
_ALPHA_STEER_ENTLADESPERRE = 1.0
COLOR_STEER_ENTLADESPERRE = color_from_hsl(
    *_HSL_STEER_ENTLADESPERRE,
    _ALPHA_STEER_ENTLADESPERRE,
)
_HSL_STEER_BASELINE = (0.0, 0.0, 82.7)
_ALPHA_STEER_BASELINE = 1.0
COLOR_STEER_BASELINE = color_from_hsl(*_HSL_STEER_BASELINE, _ALPHA_STEER_BASELINE)
COLOR_STEER_DEFAULT = COLOR_GRID_IMPORT


# --- Chart 1 — Flex-Verbraucher (``chart_color_index`` in config) -------------


CONSUMER_PALETTE_SIZE = 8
_HSL_CONSUMER_SAT = 90.0
_HSL_CONSUMER_LIG = 50.0
_ALPHA_CONSUMER = 1.0
_CONSUMER_HUE_START = 260.0
_CONSUMER_HUE_END = 40.0

# Neutraler + Forecast-Bereich: gemeinsame Sättigungsreduktion (P2, nur Chart-1-Flex-Balken).
CONSUMER_CHART_SATURATION_MUTED = 0.8
CHART1_PV_SATURATION_MUTED = CONSUMER_CHART_SATURATION_MUTED
CHART1_BASELOAD_SATURATION_MUTED = CONSUMER_CHART_SATURATION_MUTED
CHART1_PV_LUMINANCE_MUTED = 1.2
CHART1_BASELOAD_LUMINANCE_MUTED = 1.2

CONSUMER_PALETTE_HUES: tuple[float, ...] = tuple(
    _CONSUMER_HUE_START - index * (_CONSUMER_HUE_START - _CONSUMER_HUE_END) / (CONSUMER_PALETTE_SIZE - 1)
    for index in range(CONSUMER_PALETTE_SIZE)
)


def consumer_palette_color(index: int, *, saturation_factor: float = 1.0) -> str:
    """Farbe aus der festen 8er-Palette (Index 0–7)."""
    if index < 0 or index >= CONSUMER_PALETTE_SIZE:
        raise ValueError(
            f"chart_color_index muss 0–{CONSUMER_PALETTE_SIZE - 1} sein, erhalten: {index}"
        )
    hue = CONSUMER_PALETTE_HUES[index]
    saturation = max(0.0, min(100.0, _HSL_CONSUMER_SAT * saturation_factor))
    return color_from_hsl(hue, saturation, _HSL_CONSUMER_LIG, _ALPHA_CONSUMER)


CONSUMER_PALETTE: tuple[str, ...] = tuple(
    consumer_palette_color(index) for index in range(CONSUMER_PALETTE_SIZE)
)

# --- Chart 1 — Manuelle Geräte (gemeinsame Farbe für alle Appliance-Spuren) ----

_HSL_MANUAL_APPLIANCE = (28.0, 72.0, 52.0)
_ALPHA_MANUAL_APPLIANCE = 1.0
COLOR_MANUAL_APPLIANCE = color_from_hsl(
    *_HSL_MANUAL_APPLIANCE,
    _ALPHA_MANUAL_APPLIANCE,
)


def manual_appliance_chart_color(*, saturation_factor: float = 1.0) -> str:
    """Einheitliche Chart-Farbe für alle manuellen Geräte."""
    hue, saturation, luminance = _HSL_MANUAL_APPLIANCE
    saturation = max(0.0, min(100.0, saturation * saturation_factor))
    return color_from_hsl(hue, saturation, luminance, _ALPHA_MANUAL_APPLIANCE)


def flex_bar_chart_color(
    consumer: Mapping[str, Any],
    *,
    saturation_factor: float = 1.0,
) -> str:
    """Flex-Balkenfarbe: Optimizer-Verbraucher oder manuelles Gerät."""
    from optimizer.appliance_schedule import is_manual_appliance_chart_consumer

    if is_manual_appliance_chart_consumer(consumer):
        return manual_appliance_chart_color(saturation_factor=saturation_factor)
    return consumer_chart_color(consumer, saturation_factor=saturation_factor)


def consumer_chart_color(
    consumer: Mapping[str, Any],
    *,
    saturation_factor: float = 1.0,
) -> str:
    """Chart-/Sankey-Farbe für einen Flex-Verbraucher (volle Sättigung per Default)."""
    consumer_id = consumer.get("id", "?")
    raw_index = consumer.get("chart_color_index")
    if raw_index is None:
        raise ValueError(
            f"flexible_consumers[{consumer_id!r}]: chart_color_index fehlt "
            f"(Pflichtfeld, Integer 0–{CONSUMER_PALETTE_SIZE - 1})"
        )
    try:
        index = int(raw_index)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"flexible_consumers[{consumer_id!r}]: chart_color_index muss Integer 0–"
            f"{CONSUMER_PALETTE_SIZE - 1} sein, erhalten: {raw_index!r}"
        ) from exc
    return consumer_palette_color(index, saturation_factor=saturation_factor)


def consumer_chart_saturation_for_zone(zone: str) -> float:
    """Sättigungsfaktor für Flex-Balken: History volle Palette, sonst gedämpft."""
    if zone == "history":
        return 1.0
    return CONSUMER_CHART_SATURATION_MUTED


def chart1_pv_color_for_zone(zone: str) -> str:
    """PV-Farbe in Chart 1: History voll, Live/Forecast gedämpft."""
    saturation = _HSL_PV[1]
    luminance = _HSL_PV[2]
    if zone != "history":
        saturation *= CHART1_PV_SATURATION_MUTED
        luminance *= CHART1_PV_LUMINANCE_MUTED
    return color_from_hsl(_HSL_PV[0], saturation, luminance, _ALPHA_PV)


def chart1_baseload_color_for_zone(zone: str) -> str:
    """Grundlast-Farbe in Chart 1: History voll, Live/Forecast gedämpft."""
    saturation = _HSL_BASELOAD[1]
    luminance = _HSL_BASELOAD[2]
    if zone != "history":
        saturation *= CHART1_BASELOAD_SATURATION_MUTED
        luminance *= CHART1_BASELOAD_LUMINANCE_MUTED
    return color_from_hsl(_HSL_BASELOAD[0], saturation, luminance, _ALPHA_BASELOAD)


# --- Chart 2 — Kostenlinien & Summary -----------------------------------------


_HSL_COST_BASELINE = (210.0, 6.0, 52.5)
_ALPHA_COST_BASELINE = 1.0
_HSL_COST_OPTIMIZED = (28.0, 78.0, 52.0)
_ALPHA_COST_OPTIMIZED = 1.0
_HSL_COST_ACTUAL = _HSL_MARKER_NOW
_ALPHA_COST_ACTUAL = 1.0
_HSL_COST_SAVINGS = (145.0, 63.0, 42.0)
_ALPHA_COST_SAVINGS = 1.0
_HSL_COST_SAVINGS_NEGATIVE = (6.0, 78.0, 57.0)
_ALPHA_COST_SAVINGS_NEGATIVE = 1.0

COLOR_COST_BASELINE = color_from_hsl(*_HSL_COST_BASELINE, _ALPHA_COST_BASELINE)
COLOR_COST_OPTIMIZED = color_from_hsl(*_HSL_COST_OPTIMIZED, _ALPHA_COST_OPTIMIZED)
COLOR_COST_ACTUAL = color_from_hsl(*_HSL_COST_ACTUAL, _ALPHA_COST_ACTUAL)
COLOR_COST_SAVINGS = color_from_hsl(*_HSL_COST_SAVINGS, _ALPHA_COST_SAVINGS)
COLOR_COST_SAVINGS_NEGATIVE = color_from_hsl(
    *_HSL_COST_SAVINGS_NEGATIVE,
    _ALPHA_COST_SAVINGS_NEGATIVE,
)
COLOR_GRID_POWER = COLOR_COST_BASELINE


# --- Sankey Live --------------------------------------------------------------


SANKEY_NODE_PV = COLOR_PV
SANKEY_NODE_SYSTEM = COLOR_COST_BASELINE
SANKEY_NODE_BASELOAD = COLOR_COST_ACTUAL
SANKEY_NODE_HOUSE = COLOR_COST_ACTUAL

_HSL_SANKEY_GRID_IMPORT = (348.0, 83.0, 47.0)
_ALPHA_SANKEY_GRID_IMPORT = 1.0
_HSL_SANKEY_GRID_EXPORT = (0.0, 0.0, 61.6)
_ALPHA_SANKEY_GRID_EXPORT = 1.0
SANKEY_GRID_IMPORT_COLOR = color_from_hsl(*_HSL_SANKEY_GRID_IMPORT, _ALPHA_SANKEY_GRID_IMPORT)
SANKEY_GRID_EXPORT_COLOR = color_from_hsl(*_HSL_SANKEY_GRID_EXPORT, _ALPHA_SANKEY_GRID_EXPORT)

SANKEY_BATTERY_DISCHARGE_COLOR = COLOR_BATTERY
SANKEY_BATTERY_CHARGE_COLOR = SANKEY_GRID_IMPORT_COLOR
SANKEY_BATTERY_IDLE_COLOR = SANKEY_GRID_EXPORT_COLOR

_HSL_SANKEY_FLEX_MISMATCH = (24.0, 70.0, 45.0)
_ALPHA_SANKEY_FLEX_MISMATCH = 1.0
SANKEY_FLEX_MISMATCH_COLOR = color_from_hsl(*_HSL_SANKEY_FLEX_MISMATCH, _ALPHA_SANKEY_FLEX_MISMATCH)
_ALPHA_SANKEY_SOLL_LINK = 0.45
SANKEY_SOLL_PLACEHOLDER_LINK_COLOR = color_from_hsl(
    *_HSL_SANKEY_FLEX_MISMATCH,
    _ALPHA_SANKEY_SOLL_LINK,
)
_ALPHA_SANKEY_DEFAULT_LINK = 0.25
SANKEY_DEFAULT_LINK_COLOR = color_from_hsl(0.0, 0.0, 70.0, _ALPHA_SANKEY_DEFAULT_LINK)
