"""Shared test helper for the savings ledger v2 day close (Ledger P9d)."""
from __future__ import annotations

from runtime_store import savings_ledger as sl
from runtime_store import savings_ledger_flex as slf


def no_flex(_state: sl.LedgerState) -> slf.FlexDayInputs:
    """``day_flex`` without consumers: the v2 replay then equals the causal (v1) day."""
    return slf.FlexDayInputs(consumers=[], profiles_kw={}, windows={})
