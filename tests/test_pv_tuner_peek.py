"""Tests für PV-Delta ohne State-Update (Event-Läufe)."""
from __future__ import annotations

import json
from unittest.mock import patch

from data import pv_tuner


def test_get_pv_delta_peek_does_not_write_state(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    state_file.write_text(
        json.dumps({"schema_version": 1, "last_total_pv": 100.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))

    with patch.object(
        pv_tuner.loxone_client,
        "fetch_loxone_generic_value",
        return_value=103.5,
    ):
        delta = pv_tuner.get_pv_delta_peek()

    assert delta == 3.5
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["last_total_pv"] == 100.0


def test_get_pv_delta_and_update_writes_state(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    state_file.write_text(
        json.dumps({"schema_version": 1, "last_total_pv": 100.0}),
        encoding="utf-8",
    )
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))

    with patch.object(
        pv_tuner.loxone_client,
        "fetch_loxone_generic_value",
        return_value=104.0,
    ):
        delta = pv_tuner.get_pv_delta_and_update()

    assert delta == 4.0
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert saved["last_total_pv"] == 104.0


def test_get_pv_delta_peek_without_state_returns_none(tmp_path, monkeypatch):
    state_file = tmp_path / "pv_counter_state.json"
    monkeypatch.setattr(pv_tuner, "STATE_FILE", str(state_file))

    with patch.object(
        pv_tuner.loxone_client,
        "fetch_loxone_generic_value",
        return_value=50.0,
    ):
        assert pv_tuner.get_pv_delta_peek() is None
