"""Tests for Loxone auth gate in startup_checks and main loop helpers."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts import startup_checks as sc


def test_startup_skips_marker_verify_on_auth_failure(monkeypatch):
    monkeypatch.delenv("EARNIE_SKIP_LOXONE_VERIFY", raising=False)
    with (
        patch.object(sc, "loxone_env_configured", return_value=True),
        patch(
            "integrations.loxone_connectivity.probe_current_loxone_credentials",
            return_value=(False, "Loxone auth failed (HTTP 403)"),
        ),
        patch.object(sc, "verify_loxone_setup") as mock_verify,
        patch(
            "runtime_store.loxone_auth_error.persist_loxone_auth_error",
        ) as mock_persist,
    ):
        sc.run_loxone_verify_on_startup()

    mock_persist.assert_called_once_with(
        message="Loxone auth failed (HTTP 403)",
        http_status=403,
        source="startup_checks",
    )
    mock_verify.assert_not_called()


def test_startup_strict_exits_on_auth_failure(monkeypatch):
    monkeypatch.setenv("EARNIE_STRICT_LOXONE_VERIFY", "1")
    with (
        patch.object(sc, "loxone_env_configured", return_value=True),
        patch(
            "integrations.loxone_connectivity.probe_current_loxone_credentials",
            return_value=(False, "Loxone auth failed (HTTP 401)"),
        ),
        patch.object(sc, "verify_loxone_setup") as mock_verify,
    ):
        with pytest.raises(SystemExit) as exc:
            sc.run_loxone_verify_on_startup()
    assert exc.value.code == 1
    mock_verify.assert_not_called()
