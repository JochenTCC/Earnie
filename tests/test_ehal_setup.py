# tests/test_ehal_setup.py
from __future__ import annotations

import json

from runtime_store import ehal_setup


def test_normalize_backend_defaults_to_loxone():
    assert ehal_setup.normalize_backend("") == "loxone"
    assert ehal_setup.normalize_backend("none") == "loxone"
    assert ehal_setup.normalize_backend("HA") == "ha"
    assert ehal_setup.normalize_backend("openems") == "openems"


def test_hub_credentials_ha_and_openems(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(
        ehal_setup, "resolve_config_json_path", lambda: str(config_path)
    )
    config_path.write_text(
        json.dumps(
            {
                "ehal": {
                    "backend": "ha",
                    "ha": {
                        "base_url": "http://homeassistant:8123",
                        "token": "secret-token",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    assert ehal_setup.active_ehal_backend() == "ha"
    assert ehal_setup.hub_credentials_configured() is True
    assert ehal_setup.is_network_backend() is True

    config_path.write_text(
        json.dumps(
            {
                "ehal": {
                    "backend": "openems",
                    "openems": {"base_url": "http://openems-edge:8084"},
                }
            }
        ),
        encoding="utf-8",
    )
    assert ehal_setup.hub_credentials_configured("openems") is True


def test_hub_credentials_loxone_uses_env(monkeypatch):
    monkeypatch.setattr(ehal_setup, "loxone_credentials_configured", lambda: True)
    monkeypatch.setattr(ehal_setup, "_read_config_json", lambda: {})
    assert ehal_setup.hub_credentials_configured("loxone") is True


def test_require_loxone_credentials_false_for_ha(tmp_path, monkeypatch):
    from runtime_store import dotenv_io

    config_path = tmp_path / "config.json"
    monkeypatch.setenv("ENERGY_OPTIMIZER_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("ENERGY_OPTIMIZER_OFFLINE", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)
    config_path.write_text(
        json.dumps(
            {
                "ehal": {
                    "backend": "ha",
                    "ha": {
                        "base_url": "http://homeassistant:8123",
                        "token": "tok",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dotenv_io, "loxone_setup_deferred", lambda: False)
    monkeypatch.setattr(
        "runtime_store.ehal_setup.resolve_config_json_path",
        lambda: str(config_path),
    )
    assert dotenv_io.require_loxone_credentials_for_config() is False
    assert dotenv_io.needs_loxone_setup() is False


def test_build_ehal_write_records_marks_failed_fields():
    from integrations.ehal_live import build_ehal_write_records

    error = {
        "schema_version": 1,
        "ts": "2026-07-28T12:00:00Z",
        "adapter_id": "ha-home",
        "failed_fields": ["set_ess_charge_power_limit"],
        "message": "HTTP 403",
        "retryable": True,
        "hub_status": "403",
    }
    rows = build_ehal_write_records(
        {
            "set_ess_charge_power_limit": 1500.0,
            "set_ess_discharge_power_limit": 0.0,
        },
        written_at="2026-07-28T12:00:00Z",
        error=error,
    )
    assert rows[0]["success"] is False
    assert rows[1]["success"] is True
    assert rows[0]["message"] == "HTTP 403"


def test_build_telemetry_rows():
    from ui.loxone_debug import build_telemetry_rows

    rows = build_telemetry_rows({"ess_soc": 55.0, "grid_power_active": 100}, "t0")
    assert len(rows) == 2
    assert rows[0]["EHAL-Feld"] == "ess_soc"
