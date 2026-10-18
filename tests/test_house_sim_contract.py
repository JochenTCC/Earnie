"""HouseSim contract mode + push harness (Binding P5d)."""
from __future__ import annotations

import pytest

from house_sim.contract import (
    build_contract,
    contract_entity_id,
    fill_carrier_yaml_for_contract,
    fill_yaml_placeholders,
    minimal_contract_docs,
    placeholder_fill_map,
)
from house_sim.push_harness import PushClient, push_cycle
from integrations import ehal_write as ew
from integrations import loxone_request_http as http_mod
from integrations.ha_carrier_yaml import build_carrier_yaml, entity_placeholder
from runtime_store import loxone_push_inbox as inbox


@pytest.fixture(autouse=True)
def _reset_push(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "contract-test-token")
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()
    http_mod.stop_loxone_request_http()
    yield
    http_mod.stop_loxone_request_http()
    inbox.reset_memory_for_tests()
    ew.clear_published_for_tests()


def test_contract_entities_from_activated_keys_without_stored_ids():
    house, components = minimal_contract_docs()
    for value in house["plant"]["ehal_bindings"].values():
        assert value == ""
    for value in components["batteries"][0]["ehal_bindings"].values():
        assert value == ""

    bundle = build_contract(house, components)
    assert "grid.meter.sens_grid_power_active" in bundle.entity_by_ehal
    assert "ess.house.sens_ess_soc" in bundle.entity_by_ehal
    assert "ess.house.set_ess_active_power" in bundle.entity_by_ehal

    grid_eid = bundle.entity_by_ehal["grid.meter.sens_grid_power_active"]
    assert grid_eid == "sensor.earnie_grid_meter_sens_grid_power_active"
    assert bundle.store.get(grid_eid) is not None
    assert float(bundle.store.get(grid_eid)["state"]) == pytest.approx(500.0)

    write_eid = bundle.entity_by_ehal["ess.house.set_ess_active_power"]
    assert write_eid == contract_entity_id(
        "ess.house.set_ess_active_power", write=True
    )
    assert write_eid.startswith("number.earnie_")


def test_contract_rejects_stored_entity_ids():
    house, components = minimal_contract_docs()
    house["plant"]["ehal_bindings"]["sens_grid_power_active"] = (
        "sensor.should_not_be_here"
    )
    with pytest.raises(ValueError, match="must not store entity_id"):
        build_contract(house, components)


def test_fill_yaml_placeholders_uses_contract_ids():
    bundle = build_contract()
    yaml_text = build_carrier_yaml(
        bundle.house,
        bundle.components,
        earnie_host="127.0.0.1",
        earnie_port=8541,
        token="contract-test-token",
        repeat_s=10.0,
    )
    assert "ENTITY_grid_meter_sens_grid_power_active" in yaml_text
    filled = fill_yaml_placeholders(yaml_text, bundle.entity_by_ehal)
    assert "ENTITY_" not in filled or "ENTITY_unknown" not in filled
    # All mapped placeholders replaced.
    for placeholder in placeholder_fill_map(bundle.entity_by_ehal):
        assert placeholder not in filled
    assert "sensor.earnie_grid_meter_sens_grid_power_active" in filled
    assert "number.earnie_ess_house_set_ess_active_power" in filled

    via_helper = fill_carrier_yaml_for_contract(
        bundle,
        earnie_host="127.0.0.1",
        earnie_port=8541,
        token="contract-test-token",
    )
    assert "sensor.earnie_grid_meter_sens_grid_power_active" in via_helper
    assert entity_placeholder("grid.meter.sens_grid_power_active") not in via_helper


def test_push_path_inbox_and_status_setpoints():
    bundle = build_contract()
    server = http_mod.start_loxone_request_http(0, host="127.0.0.1")
    port = server.server_address[1]
    client = PushClient(f"http://127.0.0.1:{port}", token="contract-test-token")

    ew.write_field("ess.house.set_ess_active_power", -1500.0)
    report = push_cycle(bundle, client)

    assert "grid.meter.sens_grid_power_active" in report["pushed"]
    assert "heartbeat_smarthome" in report["pushed"]
    assert "ess.house.set_ess_active_power" in report["setpoints_applied"]

    value, state = inbox.read_push_value("grid.meter.sens_grid_power_active")
    assert state == inbox.STATE_OK
    assert value == pytest.approx(500.0)

    soc, soc_state = inbox.read_push_value("ess.house.sens_ess_soc")
    assert soc_state == inbox.STATE_OK
    assert soc == pytest.approx(55.0)

    write_eid = bundle.entity_by_ehal["ess.house.set_ess_active_power"]
    assert float(bundle.store.get(write_eid)["state"]) == pytest.approx(-1500.0)

    # Earnie bindings still empty — no entity_id stored.
    assert all(v == "" for v in bundle.house["plant"]["ehal_bindings"].values())


def test_push_client_rejects_bad_token():
    bundle = build_contract()
    server = http_mod.start_loxone_request_http(0, host="127.0.0.1")
    port = server.server_address[1]
    bad = PushClient(f"http://127.0.0.1:{port}", token="wrong-token")
    with pytest.raises(RuntimeError, match="telemetry push failed"):
        push_cycle(bundle, bad)
