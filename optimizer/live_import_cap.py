"""Live import caps for the max-power tariff (P5b): the Live scenario's cap and the month peak.

The peak comes from Earnie's own quarter-hour log (``capacity_peak_store``). A month without an
entry is unknown: the plan then holds the cap itself, and the result names that month in
``unknown_months`` so the cycle record and the UI can say so. The quarter hour that is running
when the cycle plans is not in the store yet (known limit, plan L4b).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from optimizer.import_power_limit import ImportCaps, import_caps_from_params


def _slot_datetimes(matrix: Sequence[dict[str, Any]]) -> list[datetime]:
    slots = []
    for row in matrix:
        slot = row["slot_datetime"]
        slots.append(slot.replace(tzinfo=None) if slot.tzinfo else slot)
    return slots


def resolve_live_import_caps(
    matrix: Sequence[dict[str, Any]],
    *,
    params: dict | None = None,
    read_peak: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """``import_caps`` for the MILP plus what the cycle record keeps.

    ``params``: the resolved Live scenario (default from ``config``). ``read_peak``: month
    (``YYYY-MM``) to a stored month peak or ``None`` (default ``capacity_peak_store.month_peak``).
    """
    if params is None:
        import config

        params = config.get_resolved_runtime_settings()
    if read_peak is None:
        from runtime_store.capacity_peak_store import month_peak

        read_peak = month_peak
    slots = _slot_datetimes(matrix)
    peak_by_month: dict[str, float] = {}
    unknown_months: list[str] = []
    caps: ImportCaps | None = None
    if params.get("import_cap_kw") is not None:
        for month in sorted({f"{slot:%Y-%m}" for slot in slots}):
            peak = read_peak(month)
            if peak is None:
                unknown_months.append(month)
            else:
                peak_by_month[month] = float(peak.peak_kw)
        caps = import_caps_from_params(params, slots, peak_by_month)
    return {
        "import_caps": caps,
        "peak_by_month": peak_by_month,
        "unknown_months": unknown_months,
    }
