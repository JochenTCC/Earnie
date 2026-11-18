"""``loxone_sent`` ledger follows ``batteries[].control`` exactly like the send path.

``build_sent_loxone_snapshot`` (stored as ``loxone_sent`` in run_state, read by the
watchdog and status.json) must contain the ESS values ``send_huawei_modbus_states``
really publishes: ``read_only`` sends nothing, ``limits_only`` reduces forced
charge/discharge to Automatik without an active power setpoint.
"""
from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import pytest

import integrations.loxone_writes as lw
from integrations import loxone_watchdog

ESS_NAMES = {
    "set_ess_active_power": "Earnie_Batterie_Sollleistung",
    "set_ess_charge_power_limit": "Earnie_LadeLeistungs-Limit",
    "set_ess_discharge_power_limit": "Earnie_EntladeLeistungs-Limit",
    "set_ess_mode": "Earnie_Steuerbefehl",
    "set_ess_target_soc": "Earnie_Ziel_SOC",
}
EXPORT_MARKER = "Earnie_Einspeiselimit"
EXPORT_VALUE = 4.0


def _battery(control: str) -> dict:
    return {
        "max_charge_power_kw": 5.0,
        "max_discharge_power_kw": 5.0,
        "battery_capacity_kwh": 15.0,
        "min_soc": 5.0,
        "max_soc": 100.0,
        "control": control,
    }


def _patches(stack: ExitStack, control: str) -> None:
    stack.enter_context(
        patch(
            "house_config.ess_bindings.resolve_primary_ess_binding",
            side_effect=lambda kind, **kw: ESS_NAMES.get(kind, ""),
        )
    )
    stack.enter_context(
        patch.object(lw.config, "get_battery_params", return_value=_battery(control))
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
    # Ledger key = Merker name on both paths, so they compare 1:1.
    stack.enter_context(
        patch.object(lw, "_ess_c1_exchange_field", side_effect=lambda kind, wired, *a, **kw: wired)
    )
    stack.enter_context(
        patch.object(
            lw, "_export_cap_marker_and_value", return_value=(EXPORT_MARKER, EXPORT_VALUE)
        )
    )


def _snapshot(control: str, *, mode: int, target_power_kw: float, target_soc: float) -> dict:
    with ExitStack() as stack:
        _patches(stack, control)
        return lw.build_sent_loxone_snapshot(
            mode=mode,
            target_power_kw=target_power_kw,
            target_soc=target_soc,
            consumer_powers={},
            charging_contexts={},
            export_cap_kw=3.0,
        )


def _sent(control: str, *, mode: int, target_power_kw: float, target_soc: float) -> dict:
    published: dict[str, float] = {}

    def _publish(field: str, value: float, *, io_name: str = ""):
        published[io_name or field] = float(value)
        return lw.LoxoneWriteRecord(io_name=io_name, value=value, success=True, written_at="t")

    with ExitStack() as stack:
        _patches(stack, control)
        stack.enter_context(patch.object(lw, "_publish_setpoint_traced", side_effect=_publish))
        lw.send_huawei_modbus_states(
            mode, target_power_kw, target_soc, export_cap_kw=3.0
        )
    return published


def test_limits_only_forced_charge_is_recorded_as_automatik() -> None:
    snap = _snapshot("limits_only", mode=1, target_power_kw=3.0, target_soc=70.0)
    assert snap["Earnie_Steuerbefehl"] == 0.0
    assert snap["Earnie_Batterie_Sollleistung"] == 0.0
    assert snap["Earnie_LadeLeistungs-Limit"] == 5.0
    assert snap["Earnie_EntladeLeistungs-Limit"] == 5.0
    # Reduced mode: no forced-charge buffer on the target SoC.
    assert snap["Earnie_Ziel_SOC"] == 70.0


def test_limits_only_forced_discharge_is_recorded_as_automatik() -> None:
    snap = _snapshot("limits_only", mode=3, target_power_kw=2.0, target_soc=40.0)
    assert snap["Earnie_Steuerbefehl"] == 0.0
    assert snap["Earnie_Batterie_Sollleistung"] == 0.0
    assert snap["Earnie_Ziel_SOC"] == 40.0


def test_read_only_records_no_ess_values_and_no_export_cap() -> None:
    snap = _snapshot("read_only", mode=1, target_power_kw=3.0, target_soc=70.0)
    assert not set(ESS_NAMES.values()) & set(snap)
    assert EXPORT_MARKER not in snap


def test_full_control_still_records_forced_charge() -> None:
    snap = _snapshot("full", mode=1, target_power_kw=3.0, target_soc=70.0)
    assert snap["Earnie_Steuerbefehl"] == 1.0
    assert snap["Earnie_Batterie_Sollleistung"] == -3.0
    assert snap["Earnie_Ziel_SOC"] > 70.0


@pytest.mark.parametrize("control", ["full", "limits_only", "read_only"])
@pytest.mark.parametrize(
    ("mode", "power", "soc"),
    [(0, 0.0, 99.0), (1, 3.0, 70.0), (2, 0.0, 63.4), (3, 2.5, 30.0)],
)
def test_snapshot_matches_published_values(
    control: str, mode: int, power: float, soc: float
) -> None:
    assert _snapshot(control, mode=mode, target_power_kw=power, target_soc=soc) == _sent(
        control, mode=mode, target_power_kw=power, target_soc=soc
    )


def test_watchdog_fallback_without_loxone_sent_follows_limits_only() -> None:
    state = {
        "success": True,
        "mode": 1,
        "target_power_kw": 3.0,
        "target_soc_percent": 70.0,
    }
    with ExitStack() as stack:
        _patches(stack, "limits_only")
        expected = loxone_watchdog.expected_loxone_snapshot_from_run_state(state)
    assert expected is not None
    assert expected["Earnie_Steuerbefehl"] == 0.0
    assert expected["Earnie_Batterie_Sollleistung"] == 0.0
