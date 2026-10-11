"""Inverter P5: curtail-only AC limit math, gating, adapter writes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ehal.field_registry import clear_loxone_spec_cache, require_loxone_write, require_openems_write
from ehal.inverter_fields import inv_field
from house_config.control_capability import inverter_control_capability_warnings
from optimizer.export_power_limit import EXPORT_LIMIT_UNCONSTRAINED_W
from optimizer.inv_ac_power_limit import (
    allocate_inv_ac_limits_kw,
    eligible_inv_limit_ids,
    inv_ac_limit_setpoint_w,
    inverter_unconstrained_kw,
    planned_discharge_kw_by_inverter,
)
from optimizer.milp_result import _extract_milp_plan_at


@pytest.fixture(autouse=True)
def _clear_registry_cache() -> None:
    clear_loxone_spec_cache()
    yield
    clear_loxone_spec_cache()


def _inv(
    inv_id: str,
    *,
    max_ac: float | None = 10.0,
    control: str = "full",
    ac: str = "grid_tied",
    inv_type: str = "hybrid",
) -> dict:
    doc: dict = {
        "id": inv_id,
        "type": inv_type,
        "control": control,
        "ac_connection": ac,
    }
    if max_ac is not None:
        doc["max_ac_power_kw"] = max_ac
    return doc


def test_unconstrained_uses_max_ac() -> None:
    assert inverter_unconstrained_kw(_inv("wr"), pv_kwp=20.0) == 10.0


def test_setpoint_w_sticky_and_cap() -> None:
    assert inv_ac_limit_setpoint_w(None, unconstrained_kw=5.0) == 5000.0
    assert inv_ac_limit_setpoint_w(None) == EXPORT_LIMIT_UNCONSTRAINED_W
    assert inv_ac_limit_setpoint_w(2.5) == 2500.0


def test_no_curtail_writes_rating() -> None:
    inverters = [_inv("wr_a"), _inv("wr_b", max_ac=8.0)]
    limits = allocate_inv_ac_limits_kw(
        inverters=inverters,
        writable_ids={"wr_a", "wr_b"},
        plant_curtail_kw=0.0,
        matrix_row={"expected_p_pv_by_system": {"pv1": 6.0, "pv2": 4.0}},
        pv_systems=[
            {"id": "pv1", "inverter_id": "wr_a"},
            {"id": "pv2", "inverter_id": "wr_b"},
        ],
        pv_kwp_by_inverter={"wr_a": 6.0, "wr_b": 4.0},
        force_discharge_kw_by_inverter={},
        planned_discharge_by_inverter={},
    )
    assert limits["wr_a"] == 10.0
    assert limits["wr_b"] == 8.0


def test_curtail_proportional_to_pv() -> None:
    inverters = [_inv("wr_a"), _inv("wr_b")]
    limits = allocate_inv_ac_limits_kw(
        inverters=inverters,
        writable_ids={"wr_a", "wr_b"},
        plant_curtail_kw=3.0,
        matrix_row={"expected_p_pv_by_system": {"pv1": 6.0, "pv2": 3.0}},
        pv_systems=[
            {"id": "pv1", "inverter_id": "wr_a"},
            {"id": "pv2", "inverter_id": "wr_b"},
        ],
        pv_kwp_by_inverter={"wr_a": 6.0, "wr_b": 3.0},
        force_discharge_kw_by_inverter={},
        planned_discharge_by_inverter={},
    )
    # weights 6:3 → allocate 2 + 1; usable 4 and 2
    assert limits["wr_a"] == pytest.approx(4.0)
    assert limits["wr_b"] == pytest.approx(2.0)


def test_hybrid_keeps_discharge_headroom() -> None:
    inverters = [_inv("wr_a")]
    limits = allocate_inv_ac_limits_kw(
        inverters=inverters,
        writable_ids={"wr_a"},
        plant_curtail_kw=2.0,
        matrix_row={"expected_p_pv_by_system": {"pv1": 5.0}},
        pv_systems=[{"id": "pv1", "inverter_id": "wr_a"}],
        pv_kwp_by_inverter={"wr_a": 5.0},
        force_discharge_kw_by_inverter={},
        planned_discharge_by_inverter={"wr_a": 1.5},
    )
    # usable PV 3 + discharge 1.5
    assert limits["wr_a"] == pytest.approx(4.5)


def test_eligible_skips_island_read_only_unmapped() -> None:
    inverters = [
        _inv("wr_ok"),
        _inv("wr_island", ac="island"),
        _inv("wr_ro", control="read_only"),
        _inv("wr_unmap"),
    ]
    ids = eligible_inv_limit_ids(
        inverters, mapped_ids={"wr_ok", "wr_island", "wr_ro"}
    )
    assert ids == {"wr_ok"}


def test_planned_discharge_by_inverter() -> None:
    out = planned_discharge_kw_by_inverter(
        {"ess": {"bat1": {"p_discharge": 2.0}, "bat2": {"p_discharge": 1.0}}},
        battery_params=[
            {"id": "bat1", "inverter_id": "wr_a"},
            {"id": "bat2", "inverter_id": "wr_a"},
        ],
    )
    assert out["wr_a"] == pytest.approx(3.0)


def test_milp_plan_includes_p_pv_curtail() -> None:
    class _Var:
        def __init__(self, value: float) -> None:
            self.varValue = value

    class _Model:
        p_grid_buy = [_Var(0.0)]
        p_grid_sell = [_Var(0.0)]
        p_charge = [_Var(0.0)]
        p_discharge = [_Var(0.0)]
        p_pv_curtail = [_Var(1.25)]
        ess_ids: list[str] = []
        p_charge_by_ess: dict = {}
        p_discharge_by_ess: dict = {}

    plan = _extract_milp_plan_at(_Model(), 0)  # type: ignore[arg-type]
    assert plan["p_pv_curtail"] == pytest.approx(1.25)


def test_inverter_control_capability_warning() -> None:
    msgs = inverter_control_capability_warnings(control="full", ehal_map={})
    assert msgs and "set_inv_ac_power_limit" in msgs[0]
    assert (
        inverter_control_capability_warnings(
            control="full",
            ehal_map={inv_field("wr", "set_inv_ac_power_limit"): "number.wr_limit"},
        )
        == []
    )
    assert inverter_control_capability_warnings(control="read_only", ehal_map={}) == []


def test_loxone_and_openems_registry_conversion() -> None:
    assert require_loxone_write("set_inv_ac_power_limit", 5000.0) == pytest.approx(5.0)
    assert require_openems_write("set_inv_ac_power_limit", 5000.0) == pytest.approx(
        5000.0
    )


def test_loxone_write_inv_ac_power_limits() -> None:
    from integrations.loxone_writes import write_inv_ac_power_limits

    with patch(
        "integrations.loxone_writes._publish_setpoint_traced"
    ) as publish:
        publish.return_value = MagicMock(success=True, value=5.0, written_at="t")
        rows = write_inv_ac_power_limits(
            {inv_field("wr_main", "set_inv_ac_power_limit"): 5000.0}
        )
    assert len(rows) == 1
    publish.assert_called_once()
    args, kwargs = publish.call_args
    assert args[0] == "inv.wr_main.set_inv_ac_power_limit"
    assert args[1] == pytest.approx(5.0)


def test_openems_write_mapped_inv_limit() -> None:
    from integrations.openems_adapter import OpenemsAdapter, OpenemsConfig

    cfg = OpenemsConfig(
        base_url="http://example.invalid",
        username="u",
        password="p",
        adapter_id="oem",
    )
    field = inv_field("wr_main", "set_inv_ac_power_limit")
    channels = {field: ("pvInverter0", "ActivePowerLimit")}
    with patch(
        "integrations.openems_adapter._openems_inv_limit_channels",
        return_value=channels,
    ):
        adapter = OpenemsAdapter(cfg)
        with patch.object(adapter, "write_channel") as write_ch:
            err = adapter.write_mapped_fields({field: 3000.0})
    assert err is None
    write_ch.assert_called_once_with("pvInverter0", "ActivePowerLimit", 3000.0)


def test_ha_write_mapped_fields_keys() -> None:
    from integrations.ha_adapter import HaAdapter, HaConfig

    cfg = HaConfig(
        base_url="http://example.invalid",
        token="t",
        adapter_id="ha",
        entities={inv_field("wr_main", "set_inv_ac_power_limit"): "number.wr_limit"},
    )
    adapter = HaAdapter(cfg)
    field = inv_field("wr_main", "set_inv_ac_power_limit")
    with patch.object(
        adapter, "_try_setpoint_write", return_value=(True, None, "")
    ) as try_write:
        err = adapter.write_mapped_fields({field: 4000.0})
    assert err is None
    try_write.assert_called_once_with(field, 4000.0)
