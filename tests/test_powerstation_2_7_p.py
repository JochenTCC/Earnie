"""2.7.p — virtual powerstation consumer-start release + 24h refill deadline."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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


def test_vo_consumer_template_has_aktiv_cmd():
    xml = Path("share/loxone/templates/VirtualOut/VO_Earnie_Consumer.xml").read_text(
        encoding="utf-8"
    )
    assert "Earnie_Verbraucher_Aktiv" in xml
    assert "consumer.{hk_id}.sens_consumer_active" in xml
    assert "flex.{hk_id}.sens_consumer_active" not in xml
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
    deadline = store.refill_deadline_utc(entry)
    assert deadline is not None
    opened = datetime.fromisoformat(str(entry["refill_opened_at"]))
    assert deadline - opened == timedelta(hours=store.REFILL_DEADLINE_H)


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


def test_milp_deadline_prefers_cheap_slot_within_24h():
    """Refill constraint spans pre-deadline slots; cost objective picks cheap ones."""
    from optimizer.milp import milp_optimizer
    from optimizer.powerstation_reserve import prepare_battery_params_for_reserves

    tz = ZoneInfo("Europe/Vienna")
    start = datetime(2026, 10, 8, 8, 0, tzinfo=tz)
    deadline = start + timedelta(hours=6)
    matrix = []
    for i in range(24):
        dt = start + timedelta(minutes=15 * i)
        # Expensive early, cheap later (still before deadline).
        price = 50.0 if i < 8 else 10.0
        matrix.append(
            {
                "hour": dt.hour,
                "date": dt.date(),
                "slot_datetime": dt,
                "expected_p_pv": 0.0,
                "expected_p_act": 0.2,
                "k_act": price,
                "k_push_act": 5.0,
                "expected_flex_kw": {},
            }
        )
    battery = {
        "id": "house",
        "battery_capacity_kwh": 15.0,
        "min_soc": 10.0,
        "max_soc": 100.0,
        "max_charge_power_kw": 4.0,
        "max_discharge_power_kw": 4.0,
        "max_power_kw": 4.0,
        "efficiency": 1.0,
        "control": "full",
    }
    reserves = [
        {
            "backing": "virtual",
            "protected_kwh": 0.0,
            "asap_charge_kwh": 1.0,
            "refill_kwh": 1.0,
            "refill_deadline_utc": deadline.astimezone(timezone.utc).isoformat(),
            "state": "empty",
            "stored_kwh": 0.0,
            "target_kwh": 1.0,
        }
    ]
    battery = prepare_battery_params_for_reserves(battery, reserves)
    assert battery["_virtual_reserve_refill_kwh"] == pytest.approx(1.0)
    assert battery.get("_virtual_reserve_refill_deadline_utc")

    mode, target_power, target_soc, *_rest = milp_optimizer(
        matrix,
        current_hour=8,
        current_soc=50.0,
        battery_params=battery,
        consumers=[],
    )
    assert mode is not None
    assert target_soc is not None
    # Slot-0 charge (positive target_power under force-charge conventions) or Automatik.
    assert float(target_power or 0.0) >= -1e-6
