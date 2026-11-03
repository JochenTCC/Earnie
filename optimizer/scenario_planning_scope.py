"""Scenario settings for planning inputs that read the house profile (SE runs).

The Szenarien-Explorer plans each window inside ``planning_scenario_scope()``
(``simulation.anchor_step._simulate_anchor_step``). Inside the scope,
``planning_runtime_settings`` returns that scenario's resolved settings
(``_house_profile`` with its heating-system variant, climate keys); outside —
Live, UI, tests — the Live scenario's resolved settings, as before.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import config

_scenario: ContextVar[dict | None] = ContextVar("earnie_planning_scenario", default=None)


@contextmanager
def planning_scenario_scope(scenario_params: dict) -> Iterator[None]:
    if not isinstance(scenario_params, dict):
        raise TypeError("Planungsszenario: scenario_params muss ein dict sein.")
    token = _scenario.set(scenario_params)
    try:
        yield
    finally:
        _scenario.reset(token)


def planning_runtime_settings() -> dict:
    """Settings the planner reads the house profile from: SE scenario, else Live."""
    scenario = _scenario.get()
    if scenario is not None:
        return scenario
    return config.get_resolved_runtime_settings()
