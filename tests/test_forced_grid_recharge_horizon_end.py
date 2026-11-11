"""Zwangsladen aus dem Netz am Horizontende bei SOC_min."""
from __future__ import annotations

import pytest

from optimizer import battery as bat
from optimizer.simulation import (
    _apply_forced_grid_recharge_at_horizon_end,
    horizon_end_soc_percent,
    sync_chart_row_netzbezug,
)


def _battery_params() -> dict:
    return {
        "battery_capacity_kwh": 5.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_power_kw": 2.5,
        "efficiency": 0.95,
    }


def _chart_row(soc: float, batt_kw: float = 0.0) -> dict:
    row = {
        "Simulierter SoC (%)": soc,
        "Geplante Batterie-Aktion (kW)": batt_kw,
        "PV-Prognose (kW)": 0.0,
        "Verbrauch-Prognose (kW)": 0.0,
        "Steuerbefehl": "Automatikbetrieb",
    }
    sync_chart_row_netzbezug(row)
    return row


def test_forced_recharge_when_end_soc_at_min():
    params = _battery_params()
    rows = [_chart_row(12.0, -0.07), _chart_row(10.0, 0.0)]
    end_soc = horizon_end_soc_percent(rows, 12.0, params)
    assert end_soc == 10.0

    recharged = _apply_forced_grid_recharge_at_horizon_end(
        rows,
        end_soc,
        battery_params=params,
        horizon_anchor_soc=50.0,
    )
    assert recharged > 10.0 + bat.SOC_DELTA_THRESHOLD
    assert rows[-1]["Steuerbefehl"].startswith("Zwangsladen")
    assert float(rows[-1]["Geplante Batterie-Aktion (kW)"]) > 0.0
    assert horizon_end_soc_percent(rows, 12.0, params) == pytest.approx(recharged, abs=0.2)


def test_no_recharge_when_end_soc_above_min():
    params = _battery_params()
    rows = [_chart_row(50.0, -0.07)]
    end_soc = horizon_end_soc_percent(rows, 50.0, params)
    assert end_soc > params["min_soc"] + bat.SOC_DELTA_THRESHOLD

    recharged = _apply_forced_grid_recharge_at_horizon_end(
        rows,
        end_soc,
        battery_params=params,
        horizon_anchor_soc=50.0,
    )
    assert recharged == end_soc
    assert rows[-1]["Steuerbefehl"] == "Automatikbetrieb"


def test_no_recharge_when_anchor_is_min_soc():
    params = _battery_params()
    rows = [_chart_row(12.0, -0.07), _chart_row(10.0, 0.0)]
    end_soc = 10.0
    recharged = _apply_forced_grid_recharge_at_horizon_end(
        rows,
        end_soc,
        battery_params=params,
        horizon_anchor_soc=10.0,
    )
    assert recharged == 10.0


def test_end_soc_is_the_last_rows_start_soc_plus_its_action():
    params = _battery_params()
    last = _chart_row(40.0, 1.0)
    # 1 kW for a quarter hour at 95 % into 5 kWh: +4.75 %
    expected = 40.0 + 1.0 * 0.95 * 0.25 / 5.0 * 100.0

    assert horizon_end_soc_percent([last], 12.0, params) == pytest.approx(expected, abs=0.05)
    # earlier rows and the start SoC of the run do not change the end
    earlier = [_chart_row(80.0, -2.5), _chart_row(15.0, 2.5)]
    assert horizon_end_soc_percent([*earlier, last], 99.0, params) == pytest.approx(
        expected, abs=0.05
    )


def test_end_soc_without_rows_is_the_start_soc():
    assert horizon_end_soc_percent([], 42.04, _battery_params()) == 42.0
