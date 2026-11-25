"""Test-suite guard for the sparse exclusivity binaries (decided 2026-11-24).

``optimizer.milp_horizon._exclusivity_slots`` keeps the buy/sell and charge/discharge
binaries only where prices need them; ``optimizer.milp_model`` logs a warning when a solved
plan still runs opposite flows in one slot. In the test suite such a plan fails the test
(autouse fixture in ``tests/conftest.py``), so a case the exclusivity rule missed shows up.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

MARKER = "allow_simultaneous_flows"


def install() -> tuple[list[dict[str, list[int]]], Callable[[], None]]:
    """Record every solved plan with opposite flows.

    Returns the (growing) list of hits and the function that restores the original check.
    Plain attribute swap, no ``monkeypatch``: an autouse fixture that requests
    ``monkeypatch`` changes the teardown order the config restore in ``tests/conftest.py``
    relies on.
    """
    from optimizer import milp_model

    original = milp_model.simultaneous_flow_slots
    found: list[dict[str, list[int]]] = []

    def _recording(model: Any) -> dict[str, list[int]]:
        result = original(model)
        if result.get("grid") or result.get("battery"):
            found.append(result)
        return result

    def _restore() -> None:
        milp_model.simultaneous_flow_slots = original

    milp_model.simultaneous_flow_slots = _recording
    return found, _restore


def check(found: list[dict[str, list[int]]]) -> None:
    """Fail the test when a plan ran opposite flows at once."""
    if found:
        pytest.fail(
            "MILP plan runs opposite flows at once (sparse exclusivity guard): "
            f"{found[:3]} — fix the exclusivity slots or mark the test "
            f"'{MARKER}' with a reason.",
            pytrace=False,
        )
