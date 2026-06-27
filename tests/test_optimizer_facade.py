# tests/test_optimizer_facade.py
"""Prüft, dass optimizer.py als Facade alle von main/app/Tests benötigten Symbole exportiert."""
from __future__ import annotations

import optimizer


def test_optimizer_facade_exports_public_api() -> None:
    for name in optimizer.__all__:
        assert hasattr(optimizer, name), f"optimizer.{name} fehlt in der Facade"


def test_heuristic_optimizer_was_renamed() -> None:
    assert hasattr(optimizer, "milp_optimizer")
    assert not hasattr(optimizer, "heuristic_optimizer")


def test_main_and_app_entry_points_are_callable() -> None:
    for name in (
        "resolve_charging_contexts",
        "prepare_optimization_matrix",
        "get_consumer_remaining_kwh",
        "milp_optimizer",
        "battery_plan_kw_from_control",
        "register_consumer_hours",
        "overlay_main_run_on_rows",
        "calculate_optimization_savings",
    ):
        assert callable(getattr(optimizer, name)), f"optimizer.{name} ist nicht aufrufbar"
