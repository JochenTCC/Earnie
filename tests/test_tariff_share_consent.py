"""Edibert share consent: stored answer and the exchange handed to the embedded editor."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from runtime_store.persist_paths import tariff_share_state_file
from runtime_store.tariff_share_consent import (
    OFF_EARNIE_OFFLINE,
    OFF_EDIBERT_SWITCH,
    OFF_NO_CONSENT,
    exchange_for_editor,
    load_consent,
    set_consent,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv("EDIBERT_EXCHANGE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("EDIBERT_EXCHANGE_OFF", raising=False)
    monkeypatch.delenv("EARNIE_OFFLINE", raising=False)


def test_missing_file_is_unset_and_gives_no_exchange():
    assert load_consent() == "unset"
    exchange = exchange_for_editor()
    assert (exchange.client, exchange.transport, exchange.off_reason) == (None, None, OFF_NO_CONSENT)


def test_consent_on_builds_client_and_transport_for_the_configured_server():
    from edibert.exchange import ServerTransport

    set_consent("on", today=date(2026, 10, 31))
    state = json.loads(Path(tariff_share_state_file()).read_text(encoding="utf-8"))
    assert state == {"consent": "on", "answered_at": "2026-10-31"}
    exchange = exchange_for_editor()
    assert exchange.off_reason is None
    assert isinstance(exchange.transport, ServerTransport)
    assert exchange.client.config.base_url == "http://127.0.0.1:9"


def test_revoked_consent_gives_no_exchange():
    set_consent("on")
    set_consent("off")
    assert load_consent() == "off"
    assert exchange_for_editor().transport is None


@pytest.mark.parametrize(
    "env, reason",
    [("EARNIE_OFFLINE", OFF_EARNIE_OFFLINE), ("EDIBERT_EXCHANGE_OFF", OFF_EDIBERT_SWITCH)],
)
def test_off_switches_win_over_consent(monkeypatch, env, reason):
    set_consent("on")
    monkeypatch.setenv(env, "1")
    exchange = exchange_for_editor()
    assert (exchange.client, exchange.transport, exchange.off_reason) == (None, None, reason)


def test_unknown_state_fails_loud():
    Path(tariff_share_state_file()).write_text(json.dumps({"consent": "maybe"}), encoding="utf-8")
    with pytest.raises(ValueError, match="consent='maybe'"):
        load_consent()


def test_only_on_and_off_can_be_stored():
    with pytest.raises(ValueError):
        set_consent("unset")  # type: ignore[arg-type]
