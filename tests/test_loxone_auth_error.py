"""Tests for runtime/loxone_auth_error.json persistence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime_store import loxone_auth_error as lae


@pytest.fixture
def runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    return tmp_path


def test_persist_load_and_clear(runtime_dir):
    lae.persist_loxone_auth_error(
        message="Loxone auth failed (HTTP 403)",
        http_status=403,
        source="test",
    )
    loaded = lae.load_loxone_auth_error()
    assert loaded is not None
    assert loaded["message"] == "Loxone auth failed (HTTP 403)"
    assert loaded["http_status"] == 403
    assert loaded["source"] == "test"
    assert loaded["detected_at"]

    lae.clear_loxone_auth_error()
    assert lae.load_loxone_auth_error() is None


def test_needs_loxone_auth_recovery_requires_file_and_backend(runtime_dir):
    with (
        patch("integrations.ehal_live.is_loxone_backend", return_value=True),
        patch("runtime_store.dotenv_io.loxone_credentials_configured", return_value=True),
    ):
        assert lae.needs_loxone_auth_recovery() is False

        lae.persist_loxone_auth_error(
            message="Loxone auth failed (HTTP 401)",
            http_status=401,
            source="test",
        )
        assert lae.needs_loxone_auth_recovery() is True


def test_needs_loxone_auth_recovery_false_for_network_backend(runtime_dir):
    lae.persist_loxone_auth_error(
        message="Loxone auth failed (HTTP 403)",
        http_status=403,
        source="test",
    )
    with (
        patch("integrations.ehal_live.is_loxone_backend", return_value=False),
        patch("runtime_store.dotenv_io.loxone_credentials_configured", return_value=True),
    ):
        assert lae.needs_loxone_auth_recovery() is False


def test_auth_banner_suppressed_in_shadow(runtime_dir, monkeypatch):
    """Shadow UI must not show a leftover Loxone auth-gate banner."""
    from ui.loxone_auth_banner import render_loxone_auth_error_banner

    lae.persist_loxone_auth_error(
        message="Loxone auth failed (HTTP 401)",
        http_status=401,
        source="startup_checks",
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    with (
        patch("ui.loxone_auth_banner.loxone_dotenv_conflict", return_value=None),
        patch("ui.loxone_auth_banner.st") as st_mock,
    ):
        render_loxone_auth_error_banner()
    st_mock.error.assert_not_called()
    st_mock.warning.assert_not_called()


def test_auth_banner_shows_when_not_shadow(runtime_dir, monkeypatch):
    from ui.loxone_auth_banner import render_loxone_auth_error_banner

    lae.persist_loxone_auth_error(
        message="Loxone auth failed (HTTP 401)",
        http_status=401,
        source="startup_checks",
    )
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    with (
        patch("ui.loxone_auth_banner.loxone_dotenv_conflict", return_value=None),
        patch("ui.loxone_auth_banner.st") as st_mock,
    ):
        render_loxone_auth_error_banner()
    st_mock.error.assert_called_once()
    assert "Loxone-Zugang verweigert" in st_mock.error.call_args.args[0]
