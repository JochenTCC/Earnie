"""Tests for Earnie_Request_Optimize HTTP wake."""
from __future__ import annotations

import urllib.error
import urllib.request

import pytest

from integrations import loxone_request_http as http_mod
from integrations.loxone_value_parse import parse_analog_value, parse_binary_value, parse_text_value
from optimizer.run_trigger import TRIGGER_REQUEST_OPTIMIZE, wait_until_next_run


@pytest.fixture(autouse=True)
def _reset_http():
    http_mod.stop_loxone_request_http()
    http_mod.clear_optimize_request()
    yield
    http_mod.stop_loxone_request_http()
    http_mod.clear_optimize_request()


def test_parse_binary_and_text() -> None:
    assert parse_binary_value(1) is True
    assert parse_binary_value("0") is False
    assert parse_binary_value(None) is None
    assert parse_text_value("  hi ") == "hi"
    assert parse_analog_value("12.34") == 12.34
    assert parse_analog_value(None) is None


def test_wait_until_next_run_returns_request_optimize() -> None:
    sleeps: list[float] = []

    def sleep_fn(sec: float) -> None:
        sleeps.append(sec)
        http_mod.signal_optimize_request()

    result = wait_until_next_run(
        total_wait_sec=10.0,
        poll_interval_sec=1.0,
        sleep_fn=sleep_fn,
    )
    assert result == TRIGGER_REQUEST_OPTIMIZE
    assert sleeps


def test_wait_until_next_run_times_out() -> None:
    result = wait_until_next_run(
        total_wait_sec=0.4,
        poll_interval_sec=0.2,
        sleep_fn=lambda _s: None,
    )
    assert result is None


def test_http_post_request_optimize_sets_event() -> None:
    server = http_mod.start_loxone_request_http(0)  # OS-assigned port
    port = server.server_address[1]
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/ehal/loxone/request_optimize",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=2) as resp:
        assert resp.status == 204
    assert http_mod.optimize_request_event().is_set()
    assert http_mod.consume_optimize_request() is True
    assert http_mod.consume_optimize_request() is False


def test_http_get_alive() -> None:
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/ehal/loxone/alive", timeout=2
    ) as resp:
        assert resp.status == 204


def test_http_unknown_path_404() -> None:
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=2)
    assert exc.value.code == 404
