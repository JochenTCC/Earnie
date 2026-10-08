"""2.7.n-4 gate: pin today's Loxone → EHAL read conversions before push intercept / n-5.

Thin characterization around ``LoxoneAdapter.read_telemetry`` and unit helpers so
push-source interception at ``fetch_loxone_generic_value`` cannot silently change
kW→W, clamps, required-field errors, or export-limit semantics.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from integrations.loxone_adapter import (
    LoxoneAdapter,
    LoxoneAdapterError,
    LoxoneConfig,
    ehal_active_power_w_to_loxone_kw,
    ehal_limit_w_to_loxone_kw,
    loxone_battery_kw_to_ehal_w,
)


def _cfg(**kwargs) -> LoxoneConfig:
    base = dict(
        adapter_id="loxone-home",
        soc_name="SoC",
        pv_power_name="PV",
        battery_power_name="Bat",
        grid_power_name="Grid",
        charge_power_name="Charge",
        discharge_power_name="Discharge",
        active_power_name="Active",
        control_cmd_name="Cmd",
    )
    base.update(kwargs)
    return LoxoneConfig(**base)


@pytest.mark.parametrize(
    ("kw", "w"),
    [(1.5, 1500.0), (-0.5, -500.0), (0.0, 0.0)],
)
def test_char_battery_kw_to_ehal_w(kw: float, w: float) -> None:
    assert loxone_battery_kw_to_ehal_w(kw) == pytest.approx(w)


@pytest.mark.parametrize(
    ("w", "kw"),
    [(2000.0, 2.0), (0.0, 0.0), (-100.0, 0.0)],
)
def test_char_ehal_limit_w_to_loxone_kw_clamps_negative(w: float, kw: float) -> None:
    assert ehal_limit_w_to_loxone_kw(w) == pytest.approx(kw)


def test_char_active_power_sign_preserved() -> None:
    assert ehal_active_power_w_to_loxone_kw(-1500) == pytest.approx(-1.5)


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_read_telemetry_kw_to_w_and_pv_clamp(fetch_mock) -> None:
    fetch_mock.side_effect = {
        "SoC": 55.0,
        "PV": -0.1,  # clamped to 0 before ×1000
        "Bat": 0.5,
        "Grid": -1.2,
    }.get
    telemetry = LoxoneAdapter(_cfg()).read_telemetry()
    assert telemetry["sens_ess_soc"] == 55.0
    assert telemetry["sens_pv_production_active"] == 0.0
    assert telemetry["sens_grid_power_active"] == pytest.approx(-1200.0)
    assert telemetry["sens_ess_power"] == pytest.approx(500.0)


@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_required_marker_missing_raises(fetch_mock) -> None:
    fetch_mock.return_value = None
    with pytest.raises(LoxoneAdapterError):
        LoxoneAdapter(_cfg()).read_telemetry()


@pytest.mark.parametrize(
    ("raw", "expected_w"),
    [(3.5, 3500.0), (0.0, 0.0), (-1.0, None), (None, None)],
)
@patch("integrations.loxone_adapter.loxone_client.fetch_loxone_generic_value")
def test_char_export_limit_inbound(fetch_mock, raw, expected_w) -> None:
    values = {"SoC": 55.0, "PV": 0.0, "Bat": 0.0, "Grid": 0.0, "ExpIn": raw}
    fetch_mock.side_effect = values.get
    telemetry = LoxoneAdapter(_cfg(grid_export_limit_in_name="ExpIn")).read_telemetry()
    assert telemetry.get("get_grid_export_power_limit") == expected_w
