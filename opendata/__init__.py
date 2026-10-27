"""Caching access to public weather and power data (Open-Meteo, Energy-Charts).

Standalone: no imports from the host application. The host builds a :class:`Session` (timeout,
transport, pauses) and passes explicit dates; clocks, time zones and feature logic stay with it.
"""
from opendata.http import ApiUnreachableError, FetchBudgetExceeded, Session, fetch_budget

__all__ = ["ApiUnreachableError", "FetchBudgetExceeded", "Session", "fetch_budget"]
