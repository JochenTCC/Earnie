"""Backtesting: umschaltbare Planungshorizont-Modi."""
from __future__ import annotations

FIXED_24H = "fixed_24h"
SUNRISE_WINDOW = "sunrise_window"
VALID_HORIZON_MODES = (FIXED_24H, SUNRISE_WINDOW)
# SE default: sunset2sunset / Live-aligned sunrise window (not fixed_24h).
DEFAULT_HORIZON_MODE = SUNRISE_WINDOW
BACKTESTING_STEP_HOURS = 24


def parse_horizon_mode(value: str) -> str:
    """Parst und validiert --horizon-mode (explizit, kein stiller Default außer CLI)."""
    if value is None:
        raise ValueError("horizon_mode fehlt.")
    mode = str(value).strip().lower()
    if mode not in VALID_HORIZON_MODES:
        raise ValueError(
            f"Ungültiger horizon_mode '{value}'. "
            f"Erlaubt: {', '.join(VALID_HORIZON_MODES)}."
        )
    return mode
