"""Tests for 2.7.a export power limit helper."""
from __future__ import annotations

from optimizer.export_power_limit import (
    EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W,
    effective_export_cap_kw,
    export_caps_for_horizon,
    export_limit_setpoint_kw,
    export_limit_setpoint_w,
    inbound_limit_w_to_kw,
    plant_max_export_power_kw,
)


def test_effective_cap_min_of_active_sources() -> None:
    assert effective_export_cap_kw(hk_max_export_kw=5.0, inbound_limit_kw=3.0) == 3.0
    assert effective_export_cap_kw(hk_max_export_kw=5.0) == 5.0
    assert effective_export_cap_kw(inbound_limit_kw=2.5) == 2.5


def test_effective_cap_missing_sources_unconstrained() -> None:
    assert effective_export_cap_kw() is None
    assert effective_export_cap_kw(hk_max_export_kw=None, inbound_limit_kw=None) is None


def test_pay_to_export_forces_hard_zero() -> None:
    assert effective_export_cap_kw(hk_max_export_kw=10.0, k_push_act=-1.5) == 0.0
    assert effective_export_cap_kw(k_push_act=-0.01) == 0.0
    assert effective_export_cap_kw(hk_max_export_kw=10.0, k_push_act=0.0) == 10.0
    assert effective_export_cap_kw(k_push_act=5.0) is None


def test_inbound_w_to_kw() -> None:
    assert inbound_limit_w_to_kw(3500.0) == 3.5
    assert inbound_limit_w_to_kw(-1) is None
    assert inbound_limit_w_to_kw(None) is None


def test_setpoint_sentinel() -> None:
    assert export_limit_setpoint_w(None) == EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W
    assert export_limit_setpoint_w(2.0) == 2000.0
    assert export_limit_setpoint_kw(None) == EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W
    assert export_limit_setpoint_kw(2.0) == 2.0


def test_export_caps_for_horizon_pay_to_export() -> None:
    matrix = [
        {"k_push_act": 10.0},
        {"k_push_act": -2.0},
        {"k_push_act": 5.0},
    ]
    caps = export_caps_for_horizon(
        matrix, hk_max_export_kw=4.0, inbound_limit_kw=None, fallback_k_push=0.0
    )
    assert caps == [4.0, 0.0, 4.0]


def test_plant_max_export_power_kw() -> None:
    assert plant_max_export_power_kw({"plant": {"max_export_power_kw": 7.0}}) == 7.0
    assert plant_max_export_power_kw({"plant": {}}) is None
    assert plant_max_export_power_kw(None) is None
