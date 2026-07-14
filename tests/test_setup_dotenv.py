# tests/test_setup_dotenv.py
"""Tests für Loxone-Setup-Helfer in der Streamlit-UI."""
from __future__ import annotations

import pytest

from integrations.loxone_connectivity import LoxoneCheck
from ui import setup_dotenv


def test_run_loxone_setup_verify_requires_credentials(monkeypatch):
    monkeypatch.setattr(setup_dotenv, "loxone_env_configured", lambda: False)

    with pytest.raises(ValueError, match="Zugangsdaten fehlen"):
        setup_dotenv.run_loxone_setup_verify()


def test_run_loxone_setup_verify_delegates_to_verify_loxone_setup(monkeypatch):
    expected = (
        True,
        [
            LoxoneCheck(
                label="SOC",
                io_name="Battery_SOC",
                passed=True,
                detail="42.0",
            )
        ],
    )
    monkeypatch.setattr(setup_dotenv, "loxone_env_configured", lambda: True)
    monkeypatch.setattr(setup_dotenv, "verify_loxone_setup", lambda: expected)

    assert setup_dotenv.run_loxone_setup_verify() == expected
