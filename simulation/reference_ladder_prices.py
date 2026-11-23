"""SE reference ladder: L2's end-customer price series and its export curtailment.

Split from ``simulation.reference_ladder``, which re-exports every name here.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from optimizer.export_power_limit import clip_grid_kw_to_export_cap


def curtail_negative_export(chart_row: dict, matrix_row: dict) -> None:
    """L2 limits export to zero while feeding in costs money; L1 does not (spec § 4.6)."""
    chart_row["Netzbezug (kW)"] = round(
        clip_grid_kw_to_export_cap(chart_row["Netzbezug (kW)"], k_push_act=matrix_row["k_push_act"]), 2
    )


def _end_customer_price_series(
    first_slot: datetime,
    last_slot: datetime,
    prices_df: pd.DataFrame,
    scenario_params: dict,
) -> dict[datetime, float]:
    """End-customer price per slot, from the book's start to the last day published in it.

    ``epex_prices_for_slots`` fills holes of up to ``MAX_PRICE_GAP`` with the previous price;
    here any slot without a market price raises, since the lock must not rank prices that did
    not exist. Only the end of the market data cuts the series, and never inside the book
    (spec § 4.2).
    """
    from data.backtesting_prices import (
        last_day_ahead_calendar_date,
        matrix_prices_from_context,
        pricing_kwargs_from_resolved,
    )
    from optimizer.sim_baseline import _is_nonexistent_local_slot
    from optimizer.slot_duration import DEFAULT_DT_H

    stop = datetime.combine(
        last_day_ahead_calendar_date(last_slot) + timedelta(days=1), datetime.min.time()
    )
    step = timedelta(hours=float(DEFAULT_DT_H))
    slots: list[datetime] = []
    current = first_slot
    while current < stop:
        if not _is_nonexistent_local_slot(current):
            slots.append(current)
        current += step
    index = prices_df.index
    known = index.tz_localize(None) if index.tz is not None else index
    stamps = pd.DatetimeIndex(slots)
    # Quarter-hour slots of an hourly series take the hour's price.
    has_price = stamps.isin(known) | stamps.floor("h").isin(known)
    last_priced = int(has_price.nonzero()[0].max()) if has_price.any() else -1
    gaps = stamps[: last_priced + 1][~has_price[: last_priced + 1]]
    if len(gaps):
        raise ValueError(
            f"Referenz-Regeln: Kein Börsenpreis für {gaps[0]:%Y-%m-%d %H:%M} "
            f"(die Preissperre braucht Preise bis {stop:%Y-%m-%d %H:%M})."
        )
    if last_priced < 0 or slots[last_priced] < last_slot:
        raise ValueError(
            f"Referenz-Regeln: Die Börsenpreise enden vor dem letzten gebuchten Slot "
            f"{last_slot:%Y-%m-%d %H:%M}."
        )
    slots = slots[: last_priced + 1]
    _, end_customer, _ = matrix_prices_from_context(
        prices_df, slots, None, **pricing_kwargs_from_resolved(scenario_params)
    )
    return dict(zip(slots, end_customer))
