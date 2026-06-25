"""Tests für variable Verbraucher-Leistung (kW-Sollwert)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from optimizer.consumer_power import (
    clamp_setpoint_kw,
    loxone_control_outputs,
    power_limits_kw,
    uses_power_setpoint,
    uses_pv_follow,
)


def _eauto_consumer() -> dict:
    return {
        "id": "eauto",
        "name": "E-Auto",
        "nominal_power_kw": 3.5,
        "min_power_kw": 1.4,
        "loxone_outputs": {
            "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
            "pv_follow_name": "Ernie_EAuto_pv_follow",
        },
    }


class TestConsumerPowerHelpers:
    def test_uses_power_setpoint(self):
        assert uses_power_setpoint(_eauto_consumer()) is True
        assert uses_power_setpoint({"id": "x", "loxone_outputs": {"enable_name": "A"}}) is False

    def test_uses_pv_follow(self):
        assert uses_pv_follow(_eauto_consumer()) is True
        assert uses_pv_follow({"id": "x", "loxone_outputs": {"power_setpoint_name": "A"}}) is False

    def test_loxone_control_outputs(self):
        consumer = _eauto_consumer()
        assert loxone_control_outputs(consumer, 0.0, 1) == (0.0, 0)
        assert loxone_control_outputs(consumer, 2.0, 0) == (2.0, 0)
        assert loxone_control_outputs(consumer, 2.0, 1) == (3.5, 1)

    def test_power_limits_kw_setpoint(self):
        assert power_limits_kw(_eauto_consumer()) == (1.4, 3.5)

    def test_power_limits_kw_binary(self):
        consumer = {"id": "spa", "nominal_power_kw": 2.8, "loxone_outputs": {"enable_name": "X"}}
        assert power_limits_kw(consumer) == (0.0, 2.8)

    def test_clamp_setpoint_zero(self):
        assert clamp_setpoint_kw(_eauto_consumer(), 0.0) == 0.0

    def test_clamp_setpoint_in_range(self):
        assert clamp_setpoint_kw(_eauto_consumer(), 2.0) == 2.0

    def test_clamp_setpoint_below_min_becomes_min(self):
        assert clamp_setpoint_kw(_eauto_consumer(), 0.5) == 1.4

    def test_clamp_setpoint_above_max(self):
        assert clamp_setpoint_kw(_eauto_consumer(), 5.0) == 3.5

    def test_missing_min_power_raises(self):
        consumer = {
            "id": "eauto",
            "nominal_power_kw": 3.5,
            "loxone_outputs": {"power_setpoint_name": "X"},
        }
        with pytest.raises(ValueError, match="min_power_kw"):
            power_limits_kw(consumer)
