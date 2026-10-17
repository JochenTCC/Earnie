"""Tests for Earnie_Request_Optimize HTTP wake."""
from __future__ import annotations

import threading
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
    assert parse_binary_value("on") is True
    assert parse_binary_value("OFF") is False
    assert parse_binary_value("true") is True
    assert parse_binary_value("false") is False
    assert parse_binary_value("home") is False
    assert parse_binary_value("away") is True
    assert parse_binary_value(True) is True
    assert parse_binary_value("nope") is None
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


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, sec: float) -> None:
        self.now += sec


def test_wait_until_next_run_times_out() -> None:
    clock = _FakeClock()
    result = wait_until_next_run(
        total_wait_sec=0.4,
        poll_interval_sec=0.2,
        sleep_fn=clock.sleep,
        clock_fn=clock,
    )
    assert result is None
    assert clock.now == pytest.approx(1000.4)


def test_wait_on_poll_cost_does_not_extend_total_wait() -> None:
    """Regression: on_poll runtime must count towards the wait (daemon drift ~1 min/15 min)."""
    clock = _FakeClock()
    polls: list[float] = []

    def on_poll() -> None:
        polls.append(clock.now)
        clock.now += 0.1  # e.g. sampler tick loading state JSON

    fired = http_mod.wait_for_optimize_or_timeout(
        900.0,
        poll_interval_sec=1.0,
        sleep_fn=clock.sleep,
        event=threading.Event(),
        on_poll=on_poll,
        clock_fn=clock,
    )
    assert fired is False
    # Deadline is 1900.0; the final on_poll may overrun by at most one poll cost.
    assert clock.now == pytest.approx(1900.0, abs=0.11)
    assert len(polls) > 800  # still polls roughly every second


def test_wait_early_wake_with_fake_clock() -> None:
    clock = _FakeClock()
    ev = threading.Event()

    def on_poll() -> None:
        if clock.now >= 1005.0:
            ev.set()

    fired = http_mod.wait_for_optimize_or_timeout(
        900.0,
        poll_interval_sec=1.0,
        sleep_fn=clock.sleep,
        event=ev,
        on_poll=on_poll,
        clock_fn=clock,
    )
    assert fired is True
    assert not ev.is_set()
    assert clock.now == pytest.approx(1005.0)


def test_http_post_request_optimize_sets_event(tmp_path, monkeypatch) -> None:
    from runtime_store import loxone_push_inbox as inbox

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    inbox.reset_memory_for_tests()
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
    value, state, last_ts = inbox.read_control_receipt("request_optimize")
    assert value == 1.0
    assert state.startswith("OK")
    assert last_ts
    assert "request_optimize" in inbox.memory_snapshot()
    inbox.reset_memory_for_tests()


def test_http_alive_removed() -> None:
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/ehal/loxone/alive", timeout=2)
    assert exc_info.value.code == 404


def test_http_heartbeat_records_callback(tmp_path, monkeypatch) -> None:
    from runtime_store import loxone_callback_status as cbs
    from runtime_store import loxone_push_inbox as inbox

    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.setenv(http_mod.PUSH_TOKEN_ENV, "s3cret")
    inbox.reset_memory_for_tests()
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/ehal/telemetry/heartbeat/1?t=s3cret", timeout=2
    ) as resp:
        assert resp.status == 204
    status = cbs.load_loxone_callback_status()
    assert status is not None
    assert status["client_ip"] in ("127.0.0.1", "::1", "localhost")
    inbox.reset_memory_for_tests()


def test_http_get_status_json_canonical_matches_loxone_path(monkeypatch) -> None:
    import json

    from integrations import loxone_status_json as status_mod

    payload = {
        "heartbeat_ts": 42,
        "set_ess_active_power": -1.5,
        "set_ess_charge_power_limit": 0.0,
        "set_ess_discharge_power_limit": 0.0,
        "set_ess_mode": 0.0,
    }
    monkeypatch.setattr(
        status_mod,
        "build_loxone_status_payload",
        lambda: dict(payload),
    )
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    loxone_url = f"http://127.0.0.1:{port}/ehal/loxone/status.json"
    canonical_url = f"http://127.0.0.1:{port}/ehal/status.json"
    with urllib.request.urlopen(loxone_url, timeout=2) as resp:
        assert resp.status == 200
        loxone_data = json.loads(resp.read().decode("utf-8"))
    with urllib.request.urlopen(canonical_url, timeout=2) as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        canonical_data = json.loads(resp.read().decode("utf-8"))
    assert canonical_data == loxone_data == payload


def test_http_get_status_json(monkeypatch) -> None:
    import json

    from integrations import loxone_status_json as status_mod

    monkeypatch.setattr(
        status_mod,
        "build_loxone_status_payload",
        lambda: {
            "heartbeat_ts": 42,
            "set_ess_active_power": -1.5,
            "set_ess_charge_power_limit": 0.0,
            "set_ess_discharge_power_limit": 0.0,
            "set_ess_mode": 0.0,
        },
    )
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/ehal/loxone/status.json", timeout=2
    ) as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = json.loads(resp.read().decode("utf-8"))
    assert data["heartbeat_ts"] == 42
    assert data["set_ess_active_power"] == -1.5


def test_http_unknown_path_404() -> None:
    server = http_mod.start_loxone_request_http(0)
    port = server.server_address[1]
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=2)
    assert exc.value.code == 404
