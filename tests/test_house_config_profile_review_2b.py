"""Hausprofil form fixes from the ui slice 2 review, package 2b."""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_entity_id_lock import profiles_env  # noqa: F401 — fixture


def _quarter_hour_on_off_csv(hours: int = 48) -> bytes:
    """15-minute 0/1 log: on in the first quarter of every hour (hourly mean 0.25)."""
    lines = ["timestamp;power_kw"]
    for hour in range(hours):
        day, h = divmod(hour, 24)
        for quarter in range(4):
            stamp = f"2025-01-{day + 1:02d}T{h:02d}:{quarter * 15:02d}:00"
            lines.append(f"{stamp};{1 if quarter == 0 else 0}")
    return ("\n".join(lines) + "\n").encode()


def test_sub_hourly_digital_upload_is_detected_and_scaled(tmp_path: Path, monkeypatch):
    """2b-1: hourly averaging hid the 0/1 signal; detection and scaling use the upload."""
    from house_config.consumption_csv import load_hourly_profile_csv, profile_csv_looks_digital
    from runtime_store.persist_paths import resolve_config_prefixed_path
    from ui.house_config_csv_io import raw_upload_sidecar, save_profile_consumption_csv
    from ui.house_config_profile_csv import _ensure_consumer_csv_normalized, _raw_upload_of

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir))
    saved = save_profile_consumption_csv(
        "haus", _quarter_hour_on_off_csv(), "wm.csv", consumer_id="wm", keep_raw=True
    )
    # The stored file is normalized (usable without a decision) ...
    unscaled = load_hourly_profile_csv(saved)
    assert 0.25 in {kw for _, kw in unscaled}
    assert profile_csv_looks_digital(saved) is False
    # ... the upload as sent still shows the on/off signal.
    assert _raw_upload_of(saved) == raw_upload_sidecar(saved)
    assert profile_csv_looks_digital(_raw_upload_of(saved)) is True

    _ensure_consumer_csv_normalized(saved, digital_scale_kw=2.0)
    scaled = load_hourly_profile_csv(saved)
    assert [ts for ts, _ in scaled] == [ts for ts, _ in unscaled]
    assert [kw for _, kw in scaled] == pytest.approx([2.0 * kw for _, kw in unscaled])
    # Answered once: the kept upload is gone, so the question does not come back.
    assert _raw_upload_of(saved) == ""
    assert not Path(resolve_config_prefixed_path(raw_upload_sidecar(saved))).exists()


def test_upload_without_keep_raw_drops_a_stale_raw_copy(tmp_path: Path, monkeypatch):
    from runtime_store.persist_paths import resolve_config_prefixed_path
    from ui.house_config_csv_io import raw_upload_sidecar, save_profile_consumption_csv

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(config_dir))
    content = _quarter_hour_on_off_csv()
    saved = save_profile_consumption_csv("haus", content, "wm.csv", keep_raw=True)
    raw = Path(resolve_config_prefixed_path(raw_upload_sidecar(saved)))
    assert raw.read_bytes() == content
    save_profile_consumption_csv("haus", content, "wm.csv")
    assert not raw.exists()


def _manual_consumer(**extra) -> dict:
    return {
        "id": "wm",
        "label": "WM",
        "type": "generic",
        "earnie_role": "manual",
        "nominal_power_kw": 1.0,
        "schedule": {
            "runs_per_week": 1,
            "duration_h": 1.0,
            "start_hour": 8,
            "start_shift_h": 0.0,
        },
        **extra,
    }


def _profile(consumer: dict) -> dict:
    return {
        "id": "home",
        "label": "Home",
        "annual_kwh": 5000.0,
        "latitude": 47.4,
        "longitude": 9.7,
        "netznutzung": {"area_id": "user_no_grid_fee"},
        "consumers": [consumer],
    }


def test_power_source_binding_saves(profiles_env):
    """2b-2: a sens_power_act binding serves power_source=loxone (no Loxone marker)."""
    from house_config.profiles_store import load_house_profiles_document
    from ui.house_config_io import upsert_house_profile

    consumer = _manual_consumer(
        appliance_recommendation={"power_source": "loxone", "default_power_kw": 1.0},
        ehal_bindings={"consumer.wm.sens_power_act": "sensor.wm_power"},
    )
    upsert_house_profile(_profile(consumer))
    stored = load_house_profiles_document(str(profiles_env["profiles"]))
    rec = stored["profiles"]["home"]["consumers"][0]["appliance_recommendation"]
    assert rec["power_source"] == "loxone"


def test_power_source_loxone_without_marker_or_binding_still_fails(profiles_env):
    from ui.house_config_io import upsert_house_profile

    consumer = _manual_consumer(
        appliance_recommendation={"power_source": "loxone", "default_power_kw": 1.0},
    )
    with pytest.raises(ValueError, match="sens_power_act-Binding"):
        upsert_house_profile(_profile(consumer))


def test_pool_filter_signal_type_survives_the_form():
    """2b-4: the form has no signal_type widget; the stored value passes through."""
    from ui.house_config_profile_save import _merge_passthrough_consumer_fields

    original = {"id": "pool_filter", "type": "generic", "signal_type": "analog"}
    edited = {"id": "pool_filter", "type": "generic", "label": "Pool"}
    assert _merge_passthrough_consumer_fields(original, edited)["signal_type"] == "analog"


def test_dynamic_ev_without_wallbox_is_rejected_not_fixed():
    """2b-3: an empty dynamic choice fails the save instead of a silent fixed wallbox."""
    from house_config.wallboxes import ASSIGNMENT_DYNAMIC, normalize_wallbox_assignment

    with pytest.raises(ValueError, match="mindestens eine Wallbox"):
        normalize_wallbox_assignment(
            {"mode": ASSIGNMENT_DYNAMIC, "wallbox_ids": []}, label="E-Auto"
        )
