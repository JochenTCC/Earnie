"""
Zentrale Chart-Farben und HSL-Hilfsfunktionen.

Manuell anpassen: ``_HSL_*``-Tripel und ``_ALPHA_*`` in den Farbdefinitionen;
abgeleitete ``COLOR_*`` / ``MUTED_*`` / ``CHART_ZONE_*_FILL`` werden daraus berechnet.

Aufbau: Hilfsfunktionen · Farbdefinitionen (Chart 1 → Chart 2 → Sankey).
"""
from __future__ import annotations


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


def rgba_from_hsl(h: float, s: float, l: float, alpha: float) -> str:
    """HSL + Alpha → Plotly-``rgba(r, g, b, a)``."""
    hex_color = hsl(h, s, l)
    red = int(hex_color[1:3], 16)
    green = int(hex_color[3:5], 16)
    blue = int(hex_color[5:7], 16)
    clamped_alpha = max(0.0, min(1.0, alpha))
    return f"rgba({red}, {green}, {blue}, {clamped_alpha})"


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def lerp_rgb(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    factor: float,
) -> tuple[int, int, int]:
    return tuple(
        int(round(start[channel] + (end[channel] - start[channel]) * factor))
        for channel in range(3)
    )


# --- Chart 1 — Hintergrundzonen (SA₀→SA₁ / SA₁→SA₂) --------------------------


# Vergangenheit (Produktiv-Log): kühles neutrales Grau — Kontrast zu Gelb/Blau/Magenta.
_HSL_ZONE_HISTORY = (220.0, 25.0, 80.0)
_ALPHA_ZONE_HISTORY = 0.15

# Vorausschau (extrapolierte Preise): helles Gelb-Grün — bewusst nicht H=120 (Batterie).
_HSL_ZONE_FORECAST = (88.0, 40.0, 80.0)
_ALPHA_ZONE_FORECAST = 0.15

CHART_ZONE_HISTORY_FILL = rgba_from_hsl(*_HSL_ZONE_HISTORY, _ALPHA_ZONE_HISTORY)
CHART_ZONE_FORECAST_FILL = rgba_from_hsl(*_HSL_ZONE_FORECAST, _ALPHA_ZONE_FORECAST)


# --- Chart 1 — Energiebilanz-Balken (Rauf/Runter) -----------------------------


_HSL_PV = (60.0, 90.0, 50.0)
_HSL_GRID = (240.0, 90.0, 50.0)
_HSL_GRID_IMPORT = (240.0, 80.0, 60.0)
_HSL_BASELOAD = (300.0, 60.0, 50.0)
_HSL_BATTERY = (120.0, 100.0, 50.0)
_HSL_WHITE = (0.0, 0.0, 100.0)

COLOR_PV = hsl(*_HSL_PV)
COLOR_GRID = hsl(*_HSL_GRID)
COLOR_BASELOAD = hsl(*_HSL_BASELOAD)
COLOR_BATTERY = hsl(*_HSL_BATTERY)
COLOR_GRID_IMPORT = hsl(*_HSL_GRID_IMPORT)

# Gedämpfte Bilanz-Segmente (Opacity in ``chart_flow_balance._MUTED_BAR_OPACITY``).
MUTED_BATTERY_LOAD = blend_hsl(_HSL_BATTERY, _HSL_WHITE, 0.1, 25.0)
MUTED_BATTERY_CHARGE_PV = blend_hsl(_HSL_PV, _HSL_BATTERY, 0.5, 25.0)
MUTED_BATTERY_CHARGE_GRID = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.6, 35.0)
MUTED_BATTERY_EXPORT = blend_hsl(_HSL_BATTERY, _HSL_GRID, 0.5, 0.8)
MUTED_EXPORT_PV = blend_hsl(_HSL_PV, _HSL_WHITE, 0.1, 25.0)


# --- Chart 1 — Linien & Overlays ----------------------------------------------


_HSL_SOC = (120.0, 90.0, 40.0)
COLOR_SOC = hsl(*_HSL_SOC)

_ALPHA_PV_LINE_FILL = 0.15
CHART_PV_LINE_COLOR = COLOR_PV
CHART_PV_FILL_COLOR = rgba_from_hsl(*_HSL_PV, _ALPHA_PV_LINE_FILL)

_HSL_MARKER_NOW = (204.0, 62.0, 58.0)
_HSL_MARKER_SUNRISE = (37.0, 90.0, 52.0)
CHART_MARKER_NOW_COLOR = hsl(*_HSL_MARKER_NOW)
CHART_MARKER_SUNRISE_COLOR = hsl(*_HSL_MARKER_SUNRISE)

_HSL_MISSING_SLOT = (33.0, 100.0, 85.0)
_ALPHA_MISSING_SLOT = 0.55
CHART_MISSING_SLOT_FILL = rgba_from_hsl(*_HSL_MISSING_SLOT, _ALPHA_MISSING_SLOT)

CHART_ENTLADESPERRE_BAND_FILL = COLOR_PV
_HSL_ENTLADESPERRE_STRIPE = (0.0, 0.0, 10.0)
CHART_ENTLADESPERRE_BAND_STRIPE = hsl(*_HSL_ENTLADESPERRE_STRIPE)


# --- Chart 1 — Legacy-Batterie-Balken (Steuerbefehl) --------------------------


COLOR_STEER_FORCE_CHARGE = COLOR_BATTERY
_HSL_STEER_FORCE_DISCHARGE = (348.0, 83.0, 47.0)
COLOR_STEER_FORCE_DISCHARGE = hsl(*_HSL_STEER_FORCE_DISCHARGE)
_HSL_STEER_ENTLADESPERRE = (33.0, 100.0, 50.0)
COLOR_STEER_ENTLADESPERRE = hsl(*_HSL_STEER_ENTLADESPERRE)
COLOR_STEER_BASELINE = "#d3d3d3"
COLOR_STEER_DEFAULT = COLOR_GRID_IMPORT


# --- Chart 1 — Flex-Verbraucher (ohne ``chart_color`` in config) ---------------


CONSUMER_PALETTE_RGB_START = (194, 24, 91)
CONSUMER_PALETTE_RGB_END = (0, 188, 212)


# --- Chart 2 — Kostenlinien & Summary -----------------------------------------


_HSL_COST_BASELINE = (210.0, 6.0, 52.5)
_HSL_COST_OPTIMIZED = (28.0, 78.0, 52.0)
_HSL_COST_ACTUAL = _HSL_MARKER_NOW
_HSL_COST_SAVINGS = (145.0, 63.0, 42.0)
_HSL_COST_SAVINGS_NEGATIVE = (6.0, 78.0, 57.0)

COLOR_COST_BASELINE = hsl(*_HSL_COST_BASELINE)
COLOR_COST_OPTIMIZED = hsl(*_HSL_COST_OPTIMIZED)
COLOR_COST_ACTUAL = hsl(*_HSL_COST_ACTUAL)
COLOR_COST_SAVINGS = hsl(*_HSL_COST_SAVINGS)
COLOR_COST_SAVINGS_NEGATIVE = hsl(*_HSL_COST_SAVINGS_NEGATIVE)
COLOR_GRID_POWER = COLOR_COST_BASELINE
COLOR_CONSUMER_FALLBACK = COLOR_COST_BASELINE


# --- Sankey Live --------------------------------------------------------------


SANKEY_NODE_PV = COLOR_PV
SANKEY_NODE_SYSTEM = COLOR_COST_BASELINE
SANKEY_NODE_BASELOAD = COLOR_COST_ACTUAL
SANKEY_NODE_HOUSE = COLOR_COST_ACTUAL

_HSL_SANKEY_GRID_IMPORT = (348.0, 83.0, 47.0)
_HSL_SANKEY_GRID_EXPORT = (0.0, 0.0, 61.6)
SANKEY_GRID_IMPORT_COLOR = hsl(*_HSL_SANKEY_GRID_IMPORT)
SANKEY_GRID_EXPORT_COLOR = hsl(*_HSL_SANKEY_GRID_EXPORT)

SANKEY_BATTERY_DISCHARGE_COLOR = COLOR_BATTERY
SANKEY_BATTERY_CHARGE_COLOR = SANKEY_GRID_IMPORT_COLOR
SANKEY_BATTERY_IDLE_COLOR = SANKEY_GRID_EXPORT_COLOR

_HSL_SANKEY_FLEX_PURPLE = (282.0, 39.0, 57.0)
_HSL_SANKEY_FLEX_TEAL = (168.0, 76.0, 42.0)
_HSL_SANKEY_FLEX_DARK = (210.0, 29.0, 24.0)
SANKEY_FLEX_PALETTE: tuple[str, ...] = (
    COLOR_COST_OPTIMIZED,
    hsl(*_HSL_SANKEY_FLEX_PURPLE),
    hsl(*_HSL_SANKEY_FLEX_TEAL),
    COLOR_COST_SAVINGS_NEGATIVE,
    hsl(*_HSL_SANKEY_FLEX_DARK),
)

_HSL_SANKEY_FLEX_MISMATCH = (24.0, 70.0, 45.0)
SANKEY_FLEX_MISMATCH_COLOR = hsl(*_HSL_SANKEY_FLEX_MISMATCH)
_ALPHA_SANKEY_SOLL_LINK = 0.45
SANKEY_SOLL_PLACEHOLDER_LINK_COLOR = rgba_from_hsl(
    *_HSL_SANKEY_FLEX_MISMATCH,
    _ALPHA_SANKEY_SOLL_LINK,
)
_ALPHA_SANKEY_DEFAULT_LINK = 0.25
SANKEY_DEFAULT_LINK_COLOR = rgba_from_hsl(0.0, 0.0, 70.0, _ALPHA_SANKEY_DEFAULT_LINK)


# --- Paletten-Hilfsfunktion (nutzt Chart-1-Flex-Konstanten) -------------------


def consumer_bar_palette(count: int) -> list[str]:
    """Farben für Flex-Verbraucher ohne ``chart_color``: Start→Ende interpoliert."""
    if count <= 0:
        return []
    if count == 1:
        return [rgb_to_hex(lerp_rgb(CONSUMER_PALETTE_RGB_START, CONSUMER_PALETTE_RGB_END, 0.5))]
    return [
        rgb_to_hex(
            lerp_rgb(
                CONSUMER_PALETTE_RGB_START,
                CONSUMER_PALETTE_RGB_END,
                index / (count - 1),
            )
        )
        for index in range(count)
    ]
