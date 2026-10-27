# data_loader.py
import logging

import pandas as pd

logger = logging.getLogger(__name__)


def _monday_of_week(ts: pd.Timestamp) -> pd.Timestamp:
    """Montag der Kalenderwoche, die ts enthält (ISO: Montag = Wochenstart)."""
    return ts.normalize() - pd.Timedelta(days=int(ts.dayofweek))


_SIMULATION_MONTHS = 12


def last_complete_month_end(data_max: pd.Timestamp) -> pd.Timestamp:
    """Last day of the most recent complete calendar month on or before data_max."""
    data_max = pd.Timestamp(data_max).normalize()
    month_end = data_max + pd.offsets.MonthEnd(0)
    if data_max == month_end.normalize():
        return data_max
    return (data_max - pd.offsets.MonthBegin(1) - pd.Timedelta(days=1)).normalize()


def resolve_simulation_window(
    range_mode: str = "last_12_months",
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Overall SE/backtesting span from cons_data bounds (month-aligned).

    End = last day of the most recent complete calendar month in cons_data.
    Start = first day of the month 11 months earlier (12 inclusive months),
    clipped to cons_data min. Day iteration stays chronological (oldest→newest).

    When ``season_mirror_to_last_month`` is enabled, the window ends at the
    wall-clock last complete month (consumption is remapped separately).

    ``range_mode`` is kept for call-site compatibility; bounds always use cons_data
    (``loxone_logs`` is no longer a separate path-pair mode).
    """
    del range_mode  # API compat; bounds are always month-aligned
    from data.cons_data_season_mirror import (
        is_season_mirror_enabled,
        wall_clock_simulation_window,
    )

    if is_season_mirror_enabled():
        return wall_clock_simulation_window()

    from data.profile_manager import get_cons_data_date_bounds

    data_min, data_max = get_cons_data_date_bounds()
    if data_min is None or data_max is None:
        raise ValueError(
            "Kein Zeitraum für die Simulation: cons_data.csv fehlt oder ist leer."
        )

    end = last_complete_month_end(pd.Timestamp(data_max))
    start = (end.to_period("M") - (_SIMULATION_MONTHS - 1)).to_timestamp().normalize()
    start = max(start, pd.Timestamp(data_min).normalize())
    if start > end:
        raise ValueError(
            "Kein gültiger Simulationszeitraum: cons_data deckt keinen "
            "vollständigen Kalendermonat ab."
        )
    return start, end
