"""HTTP tests for house_sim mock REST (auth, state shape, services)."""
from __future__ import annotations

import pytest
import requests

from house_sim.archetype import load_archetype
from house_sim.mock_rest import DEFAULT_BENCH_TOKEN, start_mock_rest, stop_mock_rest


@pytest.fixture
def mock_ha():
    package = load_archetype("evcc_en")
    store = package.build_store()
    _server, base_url = start_mock_rest(store, host="127.0.0.1", port=0)
    yield package, store, base_url
    stop_mock_rest()


def _headers(token: str = DEFAULT_BENCH_TOKEN) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def test_mock_requires_bearer(mock_ha):
    _package, _store, base_url = mock_ha
    response = requests.get(f"{base_url}/api/states", timeout=5)
    assert response.status_code == 401


def test_mock_lists_states_with_ha_shape(mock_ha):
    _package, _store, base_url = mock_ha
    response = requests.get(
        f"{base_url}/api/states", headers=_headers(), timeout=5
    )
    assert response.status_code == 200
    states = response.json()
    assert isinstance(states, list)
    assert len(states) >= 5
    sample = next(s for s in states if s["entity_id"] == "sensor.evcc_pv_power")
    assert "state" in sample
    assert "attributes" in sample
    assert sample["attributes"].get("unit_of_measurement") == "kW"
    assert "friendly_name" in sample["attributes"]


def test_mock_get_single_state(mock_ha):
    _package, _store, base_url = mock_ha
    response = requests.get(
        f"{base_url}/api/states/sensor.evcc_battery_soc",
        headers=_headers(),
        timeout=5,
    )
    assert response.status_code == 200
    assert response.json()["entity_id"] == "sensor.evcc_battery_soc"


def test_mock_input_number_set_value(mock_ha):
    _package, _store, base_url = mock_ha
    response = requests.post(
        f"{base_url}/api/services/input_number/set_value",
        headers=_headers(),
        json={"entity_id": "input_number.ess_active_power_w", "value": -2000},
        timeout=5,
    )
    assert response.status_code == 200
    assert _store.numeric_state("input_number.ess_active_power_w") == pytest.approx(
        -2000.0
    )


def test_mock_rejects_switch_domain(mock_ha):
    _package, _store, base_url = mock_ha
    response = requests.post(
        f"{base_url}/api/services/switch/turn_on",
        headers=_headers(),
        json={"entity_id": "switch.evcc_loadpoint_1_enable"},
        timeout=5,
    )
    assert response.status_code == 400
