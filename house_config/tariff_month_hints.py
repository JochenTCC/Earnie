"""Hints for ``monthly_table`` tariffs whose next month has no rate yet (UI only).

Pricing itself (including the prior-year / prior-month fallback) is Edibert's; these helpers
only tell the user, near the month end, that the catalog copy needs the next month's rate.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any

MONTHLY_TABLE = "monthly_table"


def next_calendar_month(year: int, month: int) -> tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def is_within_days_of_next_month(
    when: date | datetime,
    *,
    days: int = 2,
) -> bool:
    """True in the last ``days`` calendar days of ``when``'s month.

    Used to surface missing next-month ``monthly_table`` rates only when the
    ~48h planning horizon can reach into the next month (default: last 2 days).
    """
    if days < 1:
        raise ValueError("days must be >= 1.")
    day = when.day
    last_day = monthrange(when.year, when.month)[1]
    return day > last_day - days


def _monthly_months(tariff: dict[str, Any]) -> set[tuple[int, int]]:
    """``(year, month)`` keys of catalog rows or ``(year, month, cent)`` triples."""
    months: set[tuple[int, int]] = set()
    for index, row in enumerate(tariff.get("monthly_rates") or ()):
        if isinstance(row, dict):
            months.add((int(row["year"]), int(row["month"])))
        elif isinstance(row, (tuple, list)) and len(row) >= 3:
            months.add((int(row[0]), int(row[1])))
        else:
            raise ValueError(f"monthly_rates[{index}] muss Objekt oder (year, month, cent) sein.")
    return months


def monthly_rates_cover_month(tariff: dict[str, Any], year: int, month: int) -> bool:
    """True if a ``monthly_table`` tariff has an exact (year, month) row; other types always."""
    if str(tariff.get("type", "")).strip().lower() != MONTHLY_TABLE:
        return True
    try:
        return (int(year), int(month)) in _monthly_months(tariff)
    except (KeyError, TypeError, ValueError):
        return False


def missing_next_month_tariff_hints(
    *,
    import_tariff: dict[str, Any] | None,
    export_tariff: dict[str, Any] | None,
    year: int,
    month: int,
) -> list[str]:
    """German captions for monthly_table tariffs missing exact (year, month)."""
    hints: list[str] = []
    for side_label, tariff in (
        ("Bezug", import_tariff),
        ("Einspeise", export_tariff),
    ):
        if not isinstance(tariff, dict):
            continue
        if monthly_rates_cover_month(tariff, year, month):
            continue
        name = str(tariff.get("label") or tariff.get("id") or side_label)
        hints.append(f"{side_label}: {name}")
    return hints
