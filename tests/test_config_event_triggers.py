"""Tests für system.event_triggers in config.py."""
from __future__ import annotations

import json

import pytest

import config
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree


def _write_config(tmp_path, system_block: dict) -> tuple[str, str]:
    payload = minimal_config_payload(extra={"system": {"global_timeout": 10, "loop_timeout": 900, **system_block}})
    return write_minimal_config_tree(tmp_path, config_payload=payload)


def test_event_triggers_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "eauto_plugged_in",
                    "loxone_name": "Ernie_EAuto_Da",
                    "signal_type": "binary",
                    "on_change": "rising",
                    "label": "E-Auto angeschlossen",
                }
            ]
        },
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    triggers = cfg.get_event_triggers()
    assert len(triggers) == 1
    assert triggers[0]["id"] == "eauto_plugged_in"
    assert triggers[0]["on_change"] == "rising"


def test_duplicate_trigger_id_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "dup",
                    "loxone_name": "A",
                    "signal_type": "binary",
                    "on_change": "any",
                },
                {
                    "id": "dup",
                    "loxone_name": "B",
                    "signal_type": "binary",
                    "on_change": "any",
                },
            ]
        },
    )
    with pytest.raises(ValueError, match="doppelte id"):
        config.Config(
            config_path=config_path,
            backtesting_scenarios_path=scenarios_path,
            require_loxone_credentials=False,
        )


def test_text_trigger_invalid_on_change_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = _write_config(
        tmp_path,
        {
            "event_triggers": [
                {
                    "id": "ready",
                    "loxone_name": "FertigUm",
                    "signal_type": "text",
                    "on_change": "rising",
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="on_change"):
        config.Config(
            config_path=config_path,
            backtesting_scenarios_path=scenarios_path,
            require_loxone_credentials=False,
        )
