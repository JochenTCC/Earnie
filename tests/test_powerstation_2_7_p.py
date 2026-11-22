"""2.7.p — virtual powerstation consumer-start release (refill: Reserve P2, price-aware floor)."""
from __future__ import annotations


import pytest


def test_flex_sens_consumer_active_field():
    from ehal.flex_fields import (
        flex_sens_consumer_active,
        is_flex_live_read_field,
        is_flex_sens_consumer_active_field,
    )

    assert flex_sens_consumer_active("waschmaschine") == (
        "flex.waschmaschine.sens_consumer_active"
    )
    assert is_flex_sens_consumer_active_field(
        "flex.waschmaschine.sens_consumer_active"
    )
    assert is_flex_live_read_field("flex.waschmaschine.sens_consumer_active")


def test_vo_consumer_export_has_aktiv_cmd():
    import io
    import zipfile

    from ehal.signal_export import build_export_zip

    house = {
        "plant": {"ehal_bindings": {}},
        "profiles": {"live": {"consumers": [
            {"id": "waschmaschine", "type": "generic", "ehal_bindings": {}},
        ]}},
    }
    payload = build_export_zip(house, {}, host="192.168.1.10", port=8541, mode="all")
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        xml = zf.read("VO_Earnie_Verbraucher.xml").decode("utf-8-sig")
    assert "Push_consumer_waschmaschine_sens_consumer_active" in xml
    assert "consumer.waschmaschine.sens_consumer_active" in xml
    assert "flex.waschmaschine.sens_consumer_active" not in xml
    assert 'Analog="false"' in xml


def test_qualified_exchange_id_for_consumer_active():
    from ehal.qualified_ids import qualified_consumer_id

    assert (
        qualified_consumer_id(
            "waschmaschine", "generic", "flex.waschmaschine.sens_consumer_active"
        )
        == "consumer.waschmaschine.sens_consumer_active"
    )


def test_digital_trigger_releases_protected_floor(tmp_path, monkeypatch):
    from optimizer.powerstation_live import sync_triggers_from_telemetry
    from optimizer.powerstation_reserve import (
        collect_active_reserves,
        protected_kwh_from_state,
    )
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    appliances = [
        {
            "id": "waschmaschine",
            "mode": "reserve",
            "powerstation_id": "vps",
            "default_power_kw": 2.0,
            "default_runtime_h": 1.0,
        }
    ]
    powerstations = [
        {
            "id": "vps",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "battery_capacity_kwh": 5.0,
        }
    ]
    # Seed standby reserve
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=2.0)
    entry["state"] = store.STATE_STANDBY
    entry["stored_kwh"] = 2.0
    entry["trigger_active"] = False
    store.clear_refill_opened(entry)
    store.save_reserve_states(states)

    sync_triggers_from_telemetry(
        {"consumer.waschmaschine.sens_consumer_active": 1.0},
        collect_active_reserves(appliances=appliances, powerstations=powerstations),
    )
    states = store.load_reserve_states()
    entry = states["vps"]
    assert entry["state"] == store.STATE_DISCHARGING
    assert entry["trigger_active"] is True
    assert protected_kwh_from_state(entry) == 0.0


def test_power_threshold_trigger_from_telemetry(tmp_path, monkeypatch):
    from optimizer.powerstation_live import sync_triggers_from_telemetry
    from optimizer.powerstation_reserve import collect_active_reserves
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    appliances = [
        {
            "id": "trockner",
            "mode": "reserve",
            "powerstation_id": "vps",
            "default_power_kw": 2.0,
            "default_runtime_h": 1.0,
        }
    ]
    powerstations = [
        {
            "id": "vps",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "battery_capacity_kwh": 5.0,
        }
    ]
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=2.0)
    entry["state"] = store.STATE_STANDBY
    entry["stored_kwh"] = 2.0
    store.clear_refill_opened(entry)
    store.save_reserve_states(states)

    sync_triggers_from_telemetry(
        {"flex.trockner.sens_power_act": 0.2},
        collect_active_reserves(appliances=appliances, powerstations=powerstations),
    )
    assert store.load_reserve_states()["vps"]["state"] == store.STATE_DISCHARGING


def test_inactive_keeps_draining_then_opens_refill(tmp_path, monkeypatch):
    from optimizer.powerstation_live import sync_triggers_from_telemetry
    from optimizer.powerstation_reserve import (
        advance_reserve_after_slot,
        collect_active_reserves,
    )
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    appliances = [
        {
            "id": "waschmaschine",
            "mode": "reserve",
            "powerstation_id": "vps",
            "default_power_kw": 2.0,
            "default_runtime_h": 1.0,
        }
    ]
    powerstations = [
        {
            "id": "vps",
            "type": "powerstation",
            "backing": "virtual",
            "role": "single_use",
            "battery_capacity_kwh": 5.0,
        }
    ]
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=2.0)
    entry["state"] = store.STATE_DISCHARGING
    entry["stored_kwh"] = 1.0
    entry["trigger_active"] = True
    store.clear_refill_opened(entry)
    store.save_reserve_states(states)

    # Inactive telemetry must not wipe leftover.
    sync_triggers_from_telemetry(
        {"consumer.waschmaschine.sens_consumer_active": 0.0},
        collect_active_reserves(appliances=appliances, powerstations=powerstations),
    )
    entry = store.load_reserve_states()["vps"]
    assert entry["state"] == store.STATE_DISCHARGING
    assert entry["stored_kwh"] == pytest.approx(1.0)

    advance_reserve_after_slot(powerstation_id="vps", discharged_kwh=1.0)
    entry = store.load_reserve_states()["vps"]
    assert entry["state"] == store.STATE_EMPTY
    assert entry["stored_kwh"] == pytest.approx(0.0)
    assert entry["target_kwh"] == pytest.approx(2.0)
    assert entry.get("refill_opened_at")
    # Reserve P2: no fixed refill deadline; an emptied reserve has no fill basis.
    assert entry.get("fill_basis_price") is None


def test_ui_reset_wipes_and_reopens_refill(tmp_path, monkeypatch):
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "vps", target_kwh=2.0)
    entry["state"] = store.STATE_DISCHARGING
    entry["stored_kwh"] = 1.5
    entry["trigger_active"] = True
    store.save_reserve_states(states)

    store.set_trigger("vps", active=False)
    entry = store.load_reserve_states()["vps"]
    assert entry["state"] == store.STATE_EMPTY
    assert entry["stored_kwh"] == pytest.approx(0.0)
    assert entry["target_kwh"] == pytest.approx(2.0)
    assert entry.get("refill_opened_at")


def test_advance_and_trigger_preserve_target_kwh(tmp_path, monkeypatch):
    """Regression: advance/set_trigger must not wipe target with placeholder 0.

    Prod (Nas, 2026-10-10): virtual_gs stayed empty after MILP charge because
    advance_reserve_after_slot called get_or_init_state(..., target_kwh=0.0).
    """
    from optimizer.powerstation_reserve import advance_reserve_after_slot
    from runtime_store import powerstation_reserves as store

    monkeypatch.setattr(store, "_path", lambda: str(tmp_path / "reserves.json"))
    states = store.load_reserve_states()
    entry = store.get_or_init_state(states, "virtual_gs", target_kwh=1.0)
    entry["state"] = store.STATE_EMPTY
    entry["stored_kwh"] = 0.0
    store.save_reserve_states(states)

    advance_reserve_after_slot(powerstation_id="virtual_gs", charged_kwh=0.5)
    entry = store.load_reserve_states()["virtual_gs"]
    assert entry["target_kwh"] == pytest.approx(1.0)
    assert entry["stored_kwh"] == pytest.approx(0.5)
    assert entry["state"] == store.STATE_CHARGING

    store.set_trigger("virtual_gs", active=True)
    entry = store.load_reserve_states()["virtual_gs"]
    assert entry["target_kwh"] == pytest.approx(1.0)
    assert entry["state"] == store.STATE_DISCHARGING

    advance_reserve_after_slot(powerstation_id="virtual_gs", discharged_kwh=0.2)
    entry = store.load_reserve_states()["virtual_gs"]
    assert entry["target_kwh"] == pytest.approx(1.0)
    assert entry["stored_kwh"] == pytest.approx(0.3)


def test_save_falls_back_to_direct_write_on_winerror_5(tmp_path, monkeypatch):
    """Regression: WinError 5 on os.replace must not abort the Durchlauf."""
    from runtime_store import powerstation_reserves as store

    path = tmp_path / "reserves.json"
    monkeypatch.setattr(store, "_path", lambda: str(path))

    def _fail_replace(src, dst):
        raise PermissionError(13, "Zugriff verweigert", dst, dst, 5)

    monkeypatch.setattr(store.os, "replace", _fail_replace)
    store.save_reserve_states(
        {
            "virtual_gs": store.default_state(1.0),
        }
    )
    assert path.is_file()
    loaded = store.load_reserve_states()
    assert "virtual_gs" in loaded
    assert loaded["virtual_gs"]["target_kwh"] == pytest.approx(1.0)
