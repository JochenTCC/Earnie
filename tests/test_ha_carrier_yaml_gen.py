"""Golden checks for HA Weg B carrier YAML generator (2.7.r-T4)."""
from __future__ import annotations

from integrations.ha_carrier_yaml import build_carrier_yaml


def _minimal_house() -> dict:
    return {
        "plant": {
            "ehal_bindings": {
                "sens_grid_power_active": "",
                "sens_pv_production_active": "",
                "sens_ess_soc": "",
            }
        },
        "profiles": {},
    }


def test_carrier_yaml_contains_push_and_status():
    text = build_carrier_yaml(
        _minimal_house(),
        {"batteries": []},
        earnie_host="earnie-ha-lab",
        earnie_port=8541,
        token="TEST_TOKEN_12345678",
    )
    assert "rest_command:" in text
    assert "grid.meter.sens_grid_power_active" in text
    assert "earnie_push_heartbeat" in text
    assert "/ehal/status.json?t=TEST_TOKEN_12345678" in text
    assert "sensor:" in text
    assert "platform: rest" in text
