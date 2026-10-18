"""Plausibility guard for the per-slot PV input of an L2 run (fail loud)."""
from __future__ import annotations

import pandas as pd

# Local hours in which tilted irradiance is zero all year at Earnie latitudes.
NIGHT_HOURS = frozenset({23, 0, 1, 2})
NIGHT_PV_TOLERANCE_KW = 1e-6


class ImplausiblePvInputError(ValueError):
    """PV input of an L2 run cannot be real irradiance (e.g. poisoned Open-Meteo cache)."""


def assert_pv_day_shape(result_df: pd.DataFrame, *, case_id: str) -> None:
    """Raise if ``pv_kw`` is non-zero at night or constant and positive over the window."""
    if "pv_kw" not in result_df.columns:
        raise ImplausiblePvInputError(f"{case_id}: result frame has no pv_kw column")
    pv = result_df["pv_kw"].astype(float)
    hours = pd.DatetimeIndex(result_df.index).hour
    night = pv[[hour in NIGHT_HOURS for hour in hours]]
    hint = (
        "PV input is not a day curve — check data/cache/open_meteo for mock data "
        "(tests/fixtures/open_meteo_mock.py writes constant irradiance)."
    )
    if (night > NIGHT_PV_TOLERANCE_KW).any():
        raise ImplausiblePvInputError(
            f"{case_id}: PV > 0 at night (max {night.max():.3f} kW). {hint}"
        )
    if len(pv) > 1 and pv.nunique() == 1 and float(pv.iloc[0]) > 0.0:
        raise ImplausiblePvInputError(
            f"{case_id}: PV constant {float(pv.iloc[0]):.3f} kW in every slot. {hint}"
        )
