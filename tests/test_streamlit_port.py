"""Tests für konfigurierbaren Streamlit-Port."""
from __future__ import annotations

import pytest

import config
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree
from ui import streamlit_server


def test_streamlit_port_default_without_ui_block(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_STREAMLIT_PORT", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(tmp_path)
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_streamlit_port() == 8501


def test_streamlit_port_from_config_json(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    monkeypatch.delenv("ENERGY_OPTIMIZER_UI_STREAMLIT_PORT", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(extra={"ui": {"streamlit_port": 8510}}),
    )
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        require_loxone_credentials=False,
    )
    assert cfg.get_ui_streamlit_port() == 8510


def test_streamlit_port_env_overrides_config(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_STREAMLIT_PORT", "8520")
    assert streamlit_server.streamlit_port() == 8520


def test_invalid_streamlit_port_in_config_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_OFFLINE", "1")
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(extra={"ui": {"streamlit_port": 80}}),
    )
    with pytest.raises(ValueError, match="1024 und 65535"):
        config.Config(
            config_path=config_path,
            backtesting_scenarios_path=scenarios_path,
            require_loxone_credentials=False,
        )


def test_invalid_streamlit_port_env_raises(monkeypatch):
    monkeypatch.setenv("ENERGY_OPTIMIZER_UI_STREAMLIT_PORT", "0")
    with pytest.raises(ValueError, match="1024 und 65535"):
        streamlit_server.streamlit_port()
