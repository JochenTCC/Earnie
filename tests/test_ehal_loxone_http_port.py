"""Tests für Daemon-HTTP-Port system.ehal_loxone_http_port inkl. Env-Override."""
from __future__ import annotations

import pytest

import config
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree


def test_ehal_loxone_http_port_default(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_EHAL_LOXONE_HTTP_PORT", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ehal_loxone_http_port() == 8541


def test_ehal_loxone_http_port_from_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.delenv("EARNIE_EHAL_LOXONE_HTTP_PORT", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={
                "system": {
                    "global_timeout": 10,
                    "loop_timeout": 900,
                    "ehal_loxone_http_port": 8551,
                }
            }
        ),
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ehal_loxone_http_port() == 8551


def test_ehal_loxone_http_port_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_EHAL_LOXONE_HTTP_PORT", "8560")
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(
            extra={
                "system": {
                    "global_timeout": 10,
                    "loop_timeout": 900,
                    "ehal_loxone_http_port": 8551,
                }
            }
        ),
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ehal_loxone_http_port() == 8560


def test_invalid_ehal_loxone_http_port_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_EHAL_LOXONE_HTTP_PORT", "0")
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    with pytest.raises(ValueError, match="1024 und 65535"):
        cfg.get_ehal_loxone_http_port()


def test_non_integer_ehal_loxone_http_port_env_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_OFFLINE", "1")
    monkeypatch.setenv("EARNIE_EHAL_LOXONE_HTTP_PORT", "abc")
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    with pytest.raises(ValueError, match="ganze Zahl"):
        cfg.get_ehal_loxone_http_port()
