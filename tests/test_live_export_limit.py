"""Live export limit / Einspeisesperre helpers (2.7.a)."""
from __future__ import annotations

from optimizer import battery as bat
from optimizer.live_export_limit import (
    apply_einspeisesperre_mode,
    resolve_live_export_context,
)
from integrations.loxone_writes import map_ess_setpoints
from optimizer.export_power_limit import (
    EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W,
    export_limit_setpoint_w,
)


def test_apply_einspeisesperre_when_cap_zero() -> None:
    assert (
        apply_einspeisesperre_mode(bat.MODE_AUTOMATIK, 0.0)
        == bat.MODE_EINSPEISESPERRE
    )
    assert apply_einspeisesperre_mode(bat.MODE_ZWANGS_LADEN, 2.0) == bat.MODE_ZWANGS_LADEN
    assert apply_einspeisesperre_mode(bat.MODE_AUTOMATIK, None) == bat.MODE_AUTOMATIK


def test_map_ess_einspeisesperre_steuerbefehl_3() -> None:
    active, charge, discharge, cmd = map_ess_setpoints(bat.MODE_EINSPEISESPERRE, 0.0, 5.0)
    assert active is None
    assert charge == 5.0
    assert discharge == 5.0
    assert cmd == 3


def test_resolve_live_export_context_min() -> None:
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": 10.0},
        telemetry={"get_grid_export_power_limit": 2000.0},
        house_doc={"plant": {"max_export_power_kw": 5.0}},
    )
    assert ctx["hk_max_export_kw"] == 5.0
    assert ctx["inbound_export_limit_kw"] == 2.0
    assert ctx["effective_export_cap_kw"] == 2.0


def test_resolve_pay_to_export_zero() -> None:
    ctx = resolve_live_export_context(
        matrix_row={"k_push_act": -1.0},
        telemetry=None,
        house_doc={"plant": {"max_export_power_kw": 5.0}},
    )
    assert ctx["effective_export_cap_kw"] == 0.0
    assert export_limit_setpoint_w(ctx["effective_export_cap_kw"]) == 0.0
    assert export_limit_setpoint_w(None) == EXPORT_LIMIT_UNCONSTRAINED_SENTINEL_W
