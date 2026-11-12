"""Loxone auth errors: startup check records/clears them, the daemon never waits on them."""
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


def test_startup_clears_stale_auth_error_when_probe_succeeds(monkeypatch):
    """Credentials fixed in .env outside the UI: the banner must not stay forever."""
    monkeypatch.delenv("EARNIE_SKIP_LOXONE_VERIFY", raising=False)
    monkeypatch.delenv("EARNIE_STRICT_LOXONE_VERIFY", raising=False)
    with (
        patch.object(sc, "loxone_env_configured", return_value=True),
        patch(
            "integrations.loxone_connectivity.probe_current_loxone_credentials",
            return_value=(True, "ok"),
        ),
        patch.object(sc, "verify_loxone_setup", return_value=(True, [])),
        patch(
            "runtime_store.loxone_auth_error.clear_loxone_auth_error",
        ) as mock_clear,
    ):
        sc.run_loxone_verify_on_startup()

    mock_clear.assert_called_once_with()


def test_main_loop_has_no_loxone_credential_gates():
    """Loxone is push-only (VO inbox, VI status.json): the daemon must not wait on
    missing or rejected LOXONE_* credentials (both blocked every cycle in 2.7.0).
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert "needs_loxone_auth_recovery" not in source
    assert "probe_current_loxone_credentials" not in source
    assert "deferred_loxone_blocks_live" not in source
