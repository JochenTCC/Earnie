"""Loxone ESS C1 path publishes the effective (live) power limits the plan used.

``main.py`` plans with ``apply_effective_ess_limits`` (live ``get_ess_max_*``) and
hands the same params to ``send_huawei_modbus_states`` / ``build_sent_loxone_snapshot``.
Without them (startup safe push, watchdog rebuild) the house config limits apply.
An explicit 0 kW limit is respected; a battery without any max power fails loud.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import pytest

import integrations.loxone_writes as lw
from integrations import ehal_live_ops
from settings.ess_limits_resolve import apply_effective_ess_limits

ESS_NAMES = {
    "set_ess_active_power": "Earnie_Batterie_Sollleistung",
    "set_ess_charge_power_limit": "Earnie_LadeLeistungs-Limit",
    "set_ess_discharge_power_limit": "Earnie_EntladeLeistungs-Limit",
    "set_ess_mode": "Earnie_Steuerbefehl",
    "set_ess_target_soc": "Earnie_Ziel_SOC",
}


def _hk_battery(**overrides) -> dict:
    bat = {
        "id": "speicher",
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "max_power_kw": 5.0,
        "battery_capacity_kwh": 15.0,
        "min_soc": 5.0,
        "max_soc": 100.0,
        "control": "full",
        "limits_from_live": True,
    }
    bat.update(overrides)
    return bat


def _patches(stack: ExitStack, hk_battery: dict) -> None:
    stack.enter_context(
        patch(
            "house_config.ess_bindings.resolve_primary_ess_binding",
            side_effect=lambda kind, **kw: ESS_NAMES.get(kind, ""),
        )
    )
    stack.enter_context(
        patch.object(lw.config, "get_battery_params", return_value=hk_battery)
    )
    stack.enter_context(patch.object(lw.config, "get_flexible_consumers", return_value=[]))
    stack.enter_context(
        patch(
            "integrations.ehal_debug_mapping.has_mappable_live_batteries",
            return_value=False,
        )
    )
    stack.enter_context(
        patch("integrations.ehal_debug_mapping.build_loxone_setpoint_io_index", return_value={})
    )
    stack.enter_context(
        patch.object(lw, "_ess_c1_exchange_field", side_effect=lambda kind, wired, *a, **kw: wired)
    )


def _snapshot(hk_battery: dict, battery_params: dict | None, *, mode: int = 0) -> dict:
    with ExitStack() as stack:
        _patches(stack, hk_battery)
        return ehal_live_ops.build_sent_loxone_snapshot(
            mode, 0.0, 99.0, {}, {}, battery_params=battery_params
        )


def _sent(hk_battery: dict, battery_params: dict | None, *, mode: int = 0) -> dict:
    published: dict[str, float] = {}

    def _publish(field: str, value: float, *, io_name: str = ""):
        published[io_name or field] = float(value)
        return lw.LoxoneWriteRecord(io_name=io_name, value=value, success=True, written_at="t")

    with ExitStack() as stack:
        _patches(stack, hk_battery)
        stack.enter_context(patch.object(lw, "_publish_setpoint_traced", side_effect=_publish))
        ehal_live_ops.write_huawei_modbus_states(
            mode, 0.0, 99.0, battery_params=battery_params
        )
    return published


def test_live_discharge_zero_is_published_in_automatik() -> None:
    """Production case: inverter reports max discharge 0 W, plan used 0 kW."""
    hk = _hk_battery()
    telemetry = {"ess.speicher.get_ess_max_discharge_power": 0.0}
    effective = apply_effective_ess_limits(hk, telemetry=telemetry)
    assert effective["max_discharge_power_kw"] == 0.0

    sent = _sent(hk, effective)
    assert sent["Earnie_EntladeLeistungs-Limit"] == 0.0
    assert sent["Earnie_LadeLeistungs-Limit"] == 5.0
    assert sent["Earnie_Steuerbefehl"] == 0.0
    assert _snapshot(hk, effective) == sent


def test_live_derated_charge_limit_reaches_loxone() -> None:
    hk = _hk_battery()
    effective = apply_effective_ess_limits(
        hk, telemetry={"ess.speicher.get_ess_max_charge_power": 2500.0}
    )
    sent = _sent(hk, effective)
    assert sent["Earnie_LadeLeistungs-Limit"] == 2.5
    assert sent["Earnie_EntladeLeistungs-Limit"] == 5.0
    assert _snapshot(hk, effective) == sent


def test_without_battery_params_house_config_limits_apply() -> None:
    """Startup safe push / watchdog rebuild: no telemetry, house config limits."""
    hk = _hk_battery(max_discharge_power_kw=4.0)
    sent = _sent(hk, None)
    assert sent["Earnie_LadeLeistungs-Limit"] == 5.0
    assert sent["Earnie_EntladeLeistungs-Limit"] == 4.0
    assert _snapshot(hk, None) == sent


def test_explicit_zero_discharge_is_not_replaced_by_max_power() -> None:
    hk = _hk_battery(max_discharge_power_kw=0.0, max_power_kw=5.0)
    sent = _sent(hk, None)
    assert sent["Earnie_EntladeLeistungs-Limit"] == 0.0
    assert sent["Earnie_LadeLeistungs-Limit"] == 5.0


def test_missing_direction_uses_shared_max_power() -> None:
    assert lw._battery_max_powers_kw({"max_power_kw": 3.0, "max_charge_power_kw": 1.0}) == (
        1.0,
        3.0,
    )


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"max_charge_power_kw": 5.0},
        {"max_charge_power_kw": None, "max_discharge_power_kw": 5.0, "max_power_kw": None},
    ],
)
def test_missing_max_power_fails_loud(params: dict) -> None:
    with pytest.raises(ValueError, match="no max_"):
        lw._battery_max_powers_kw(params)


def test_send_path_raises_instead_of_publishing_zero_limits() -> None:
    hk = _hk_battery()
    for key in ("max_charge_power_kw", "max_discharge_power_kw", "max_power_kw"):
        hk.pop(key)
    with pytest.raises(ValueError):
        _sent(hk, None)
