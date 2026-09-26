"""Live export limit helpers (2.7.a): cap resolution, battery-only set_ess_mode."""
from __future__ import annotations

from optimizer import battery as bat
import pytest

from optimizer.live_export_limit import (
    live_unconstrained_export_kw,
    resolve_live_export_context,
)
from integrations.loxone_writes import map_ess_setpoints
from optimizer.export_power_limit import (
    EXPORT_LIMIT_UNCONSTRAINED_W,
    export_limit_setpoint_w,
)


def test_ess_mode_stays_battery_only_under_zero_export_cap() -> None:
    """Pay-to-export (cap 0) must not override the MILP battery decision."""
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": -1.0}, telemetry=None, house_doc={"plant": {}}
    )
    assert ctx["effective_export_cap_kw"] == 0.0
    active, charge, discharge, cmd = map_ess_setpoints(bat.MODE_ZWANGS_LADEN, 3.0, 5.0)
    assert (active, charge, discharge, cmd) == (-3.0, 5.0, 0.0, 1)
    assert not hasattr(bat, "MODE_EINSPEISESPERRE")


def test_resolve_live_export_context_min() -> None:
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": 10.0},
        telemetry={"get_grid_export_power_limit": 2000.0},
        house_doc={"plant": {"max_export_power_kw": 5.0}},
    )
    assert ctx["hk_max_export_kw"] == 5.0
    assert ctx["inbound_export_limit_kw"] == 2.0
    assert ctx["effective_export_cap_kw"] == 2.0


def test_resolve_inbound_unconstrained_is_no_cap() -> None:
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": 10.0},
        telemetry={"get_grid_export_power_limit": EXPORT_LIMIT_UNCONSTRAINED_W},
        house_doc={"plant": {}},
    )
    assert ctx["inbound_export_limit_kw"] is None
    assert ctx["effective_export_cap_kw"] is None


def test_resolve_pay_to_export_zero() -> None:
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": -1.0},
        telemetry=None,
        house_doc={"plant": {"max_export_power_kw": 5.0}},
    )
    assert ctx["effective_export_cap_kw"] == 0.0
    assert export_limit_setpoint_w(ctx["effective_export_cap_kw"]) == 0.0
    assert export_limit_setpoint_w(None) == EXPORT_LIMIT_UNCONSTRAINED_W


@pytest.mark.parametrize(
    ("control", "expected_kw"),
    [("full", 14.8), ("limits_only", 9.8), ("read_only", 9.8)],
)
def test_live_unconstrained_counts_only_force_discharge_battery(
    monkeypatch, control, expected_kw
) -> None:
    import config

    monkeypatch.setattr(
        config, "get_battery_params", lambda: {"max_power_kw": 5.0, "control": control}
    )
    monkeypatch.setattr(
        config, "get", lambda name, default=None, cast=None: 9.8 if name == "PV_KWP" else default
    )
    assert live_unconstrained_export_kw() == pytest.approx(expected_kw)
