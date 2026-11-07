"""Import limit per slot for the max-power tariff: the cap, the ratchet and the active months.

Pure except for ``import_caps_from_params``, which asks the grid area which months have a capacity
charge. Plan: ``docs/dev/max-power-tariff-plan.md`` (P3, decisions D3 and D4).
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from house_config.import_cap import ImportCap, parse_import_cap


@dataclass(frozen=True)
class ImportCaps:
    """Per slot: the import limit in kW and its calendar month; ``None`` where no limit applies."""

    limits_kw: tuple[float | None, ...]
    months: tuple[str | None, ...]

    def from_slot(self, start: int) -> ImportCaps | None:
        """The limits of a plan that starts at slot ``start``; ``None`` when none is left."""
        return _caps_or_none(self.limits_kw[start:], self.months[start:])

    def only_at(self, indices: Collection[int]) -> ImportCaps | None:
        """Keeps the limits of these slots, the others go free; ``None`` when none is left."""
        return _caps_or_none(
            tuple(limit if i in indices else None for i, limit in enumerate(self.limits_kw)),
            tuple(month if i in indices else None for i, month in enumerate(self.months)),
        )


def _caps_or_none(limits: tuple[float | None, ...], months: tuple[str | None, ...]) -> ImportCaps | None:
    """A plan without any limit gets no ``ImportCaps``, so the model has no extra variables."""
    return None if all(limit is None for limit in limits) else ImportCaps(limits, months)


def import_caps_for_slots(
    slots: Sequence[datetime],
    cap: ImportCap,
    month_is_active: Callable[[date], bool],
    peak_by_month: Mapping[str, float],
) -> ImportCaps | None:
    """Limit = larger of cap and the month's peak so far (the ratchet), less the margin.

    ``peak_by_month`` holds the peak so far per ``YYYY-MM``; a month without an entry has no peak
    yet, as in a horizon that crosses the month boundary. ``None`` when no slot has a limit, so a
    plan outside the active months gets no extra variables.
    """
    limits: list[float | None] = []
    months: list[str | None] = []
    for slot in slots:
        month = f"{slot:%Y-%m}"
        if not month_is_active(slot.date().replace(day=1)):
            limits.append(None)
            months.append(None)
            continue
        peak = max(0.0, float(peak_by_month.get(month, 0.0)))
        limits.append(max(cap.cap_kw, peak) - cap.margin_kw)
        months.append(month)
    return _caps_or_none(tuple(limits), tuple(months))


def import_caps_from_params(
    params: dict | None,
    slots: Sequence[datetime],
    peak_by_month: Mapping[str, float],
) -> ImportCaps | None:
    """Limits of a resolved scenario; ``None`` without a cap or outside the active months."""
    from data.edibert_slot_prices import EDIBERT_PRICING_KEY, grid_fee
    from house_config.edibert_tariffs import capacity_charge_for_month

    cap = parse_import_cap(params)
    if cap is None:
        return None
    ref = params.get(EDIBERT_PRICING_KEY) if isinstance(params, dict) else None
    fee = grid_fee(ref) if isinstance(ref, dict) else None
    if fee is None:
        raise ValueError("Szenario: import_cap_kw braucht ein Hausprofil mit Netzbereich (netznutzung).")
    return import_caps_for_slots(
        slots,
        cap,
        lambda month: capacity_charge_for_month(fee, month) is not None,
        peak_by_month,
    )
