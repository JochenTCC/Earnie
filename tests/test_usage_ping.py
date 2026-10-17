"""UsagePing P1/P2 — consent, payload, daemon spawn, milestones, mock server."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from runtime_store import usage_ping as up
from version import __version__


@pytest.fixture
def runtime_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path / "runtime"))
    monkeypatch.delenv("EARNIE_USAGE_PING", raising=False)
    monkeypatch.delenv("EARNIE_USAGE_PING_URL", raising=False)
    monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    up.reset_send_in_flight_for_tests()
    return tmp_path / "runtime"


def _now(day: str = "2026-10-16", hour: int = 12) -> datetime:
    y, m, d = (int(x) for x in day.split("-"))
    return datetime(y, m, d, hour, 0, 0, tzinfo=timezone.utc)


class _FakeTransport:
    def __init__(self, status: int = 204) -> None:
        self.status = status
        self.calls: list[tuple[str, bytes, float]] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> int:
        self.calls.append((url, body, timeout))
        return self.status


def test_missing_file_is_unset(runtime_dir: Path) -> None:
    state = up.load_state()
    assert state["consent"] == "unset"
    fake = _FakeTransport()
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://x/ping") is False
    assert fake.calls == []


def test_opt_in_mints_id_opt_out_wipes(runtime_dir: Path) -> None:
    on = up.set_consent("on", now=_now())
    assert on["consent"] == "on"
    assert on["consent_at"] == "2026-10-16"
    assert on["stage"] == "explorer"
    install_id = on["install_id"]
    assert len(install_id) == 36

    off = up.set_consent("off", now=_now())
    assert off["consent"] == "off"
    assert "install_id" not in off
    assert off["consent_at"] == "2026-10-16"


def test_kill_switch_blocks_send(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    up.set_consent("on", now=_now())
    monkeypatch.setenv("EARNIE_USAGE_PING", "off")
    fake = _FakeTransport()
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://x/ping") is False
    assert fake.calls == []


def test_consent_off_blocks_send(runtime_dir: Path) -> None:
    up.set_consent("on", now=_now())
    up.set_consent("off", now=_now())
    fake = _FakeTransport()
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://x/ping") is False
    assert fake.calls == []


def test_once_per_day_and_next_day(runtime_dir: Path) -> None:
    up.set_consent("on", now=_now())
    fake = _FakeTransport(204)
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://x/ping") is True
    assert len(fake.calls) == 1
    state = up.load_state()
    assert state["last_sent_date"] == "2026-10-16"

    assert up.maybe_send_ping(_now(hour=18), transport=fake, endpoint_url="http://x/ping") is False
    assert len(fake.calls) == 1

    next_day = _now("2026-10-17")
    assert up.maybe_send_ping(next_day, transport=fake, endpoint_url="http://x/ping") is True
    assert len(fake.calls) == 2
    assert up.load_state()["last_sent_date"] == "2026-10-17"


def test_failure_retry_after_one_hour(runtime_dir: Path) -> None:
    up.set_consent("on", now=_now())
    fake = _FakeTransport(500)
    t0 = _now(hour=10)
    assert up.maybe_send_ping(t0, transport=fake, endpoint_url="http://x/ping") is False
    assert len(fake.calls) == 1
    state = up.load_state()
    assert "last_sent_date" not in state or state.get("last_sent_date") != "2026-10-16"
    assert state["last_attempt_at"]

    assert up.maybe_send_ping(t0 + timedelta(minutes=30), transport=fake, endpoint_url="http://x/ping") is False
    assert len(fake.calls) == 1

    fake.status = 200
    assert up.maybe_send_ping(t0 + timedelta(hours=1), transport=fake, endpoint_url="http://x/ping") is True
    assert len(fake.calls) == 2
    assert up.load_state()["last_sent_date"] == "2026-10-16"


def test_payload_whitelist_and_context(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "loxberry")
    state = up.set_consent("on", now=_now())
    payload = up.build_payload(state)
    assert set(payload.keys()) == up.PAYLOAD_KEYS_V1
    assert payload == {
        "v": 1,
        "id": state["install_id"],
        "app_version": __version__,
        "context": "loxberry",
        "stage": "explorer",
    }


def test_set_highest_stage_monotonic(runtime_dir: Path) -> None:
    up.set_consent("on", now=_now())
    up.set_highest_stage("live")
    assert up.load_state()["stage"] == "live"
    up.set_highest_stage("explorer")
    assert up.load_state()["stage"] == "live"
    payload = up.build_payload()
    assert payload["stage"] == "live"


def test_missing_url_without_transport_warns(
    runtime_dir: Path, caplog: pytest.LogCaptureFixture
) -> None:
    up.set_consent("on", now=_now())
    with caplog.at_level("WARNING", logger="runtime_store.usage_ping"):
        assert up.maybe_send_ping(_now()) is False
    assert any("USAGE_PING_URL" in r.message for r in caplog.records)


def test_fake_transport_records_json_body(runtime_dir: Path) -> None:
    state = up.set_consent("on", now=_now())
    fake = _FakeTransport(201)
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://mock/ping") is True
    url, body, timeout = fake.calls[0]
    assert url == "http://mock/ping"
    assert timeout == up.TIMEOUT_SEC
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["id"] == state["install_id"]
    assert set(parsed.keys()) == up.PAYLOAD_KEYS_V1


class _PingHandler(BaseHTTPRequestHandler):
    received: list[dict[str, Any]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        _PingHandler.received.append(
            {
                "path": self.path,
                "content_type": self.headers.get("Content-Type"),
                "body": json.loads(raw.decode("utf-8")),
            }
        )
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


def test_mock_http_server_receives_ping(runtime_dir: Path) -> None:
    _PingHandler.received = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PingHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        up.set_consent("on", now=_now())
        url = f"http://127.0.0.1:{port}/ping"
        assert up.maybe_send_ping(_now(), endpoint_url=url) is True
        assert len(_PingHandler.received) == 1
        hit = _PingHandler.received[0]
        assert hit["path"] == "/ping"
        assert hit["content_type"] == "application/json"
        assert set(hit["body"].keys()) == up.PAYLOAD_KEYS_V1
        assert up.load_state()["last_sent_date"] == "2026-10-16"
    finally:
        server.shutdown()
        server.server_close()


def test_preview_payload_placeholder_when_unset(runtime_dir: Path) -> None:
    preview = up.preview_payload()
    assert set(preview.keys()) == up.PAYLOAD_KEYS_V1
    assert preview["id"] == up.PREVIEW_ID_PLACEHOLDER
    assert preview["stage"] == "explorer"

    state = up.set_consent("on", now=_now())
    preview_on = up.preview_payload(state)
    assert preview_on["id"] == state["install_id"]
    assert set(preview_on.keys()) == up.PAYLOAD_KEYS_V1


def _live_state_with_points(points: object = 5, points_v: object = 1) -> dict[str, Any]:
    state = up.set_consent("on", now=_now())
    state.update({"stage": "live", "points": points, "points_v": points_v})
    return state


def test_payload_v2_when_live_with_points(runtime_dir: Path) -> None:
    state = _live_state_with_points()
    payload = up.build_payload(state)
    assert set(payload.keys()) == up.PAYLOAD_KEYS_V2
    assert payload["v"] == 2
    assert payload["points"] == 5
    assert payload["points_v"] == 1
    assert up.preview_payload(state) == payload


def test_payload_v1_without_points_or_before_live(runtime_dir: Path) -> None:
    live = up.set_consent("on", now=_now())
    # Strip any points from consent-time refresh (local plant may be resolvable).
    live["stage"] = "live"
    live.pop("points", None)
    live.pop("points_v", None)
    live.pop("points_stamp", None)
    assert set(up.build_payload(live).keys()) == up.PAYLOAD_KEYS_V1
    explorer = {**live, "stage": "explorer", "points": 5, "points_v": 1}
    payload = up.build_payload(explorer)
    assert set(payload.keys()) == up.PAYLOAD_KEYS_V1
    assert payload["v"] == 1


def test_payload_zero_points_is_sent(runtime_dir: Path) -> None:
    payload = up.build_payload(_live_state_with_points(points=0))
    assert payload["v"] == 2
    assert payload["points"] == 0


@pytest.mark.parametrize(
    ("points", "points_v"),
    [(-1, 1), (True, 1), ("5", 1), (5, 0), (5, None), (5, 1.0)],
)
def test_invalid_points_state_raises(runtime_dir: Path, points: object, points_v: object) -> None:
    with pytest.raises(ValueError, match="invalid points state"):
        up.build_payload(_live_state_with_points(points, points_v))


def test_points_without_points_v_raises(runtime_dir: Path) -> None:
    state = _live_state_with_points()
    del state["points_v"]
    with pytest.raises(ValueError, match="invalid points state"):
        up.build_payload(state)


def test_v2_ping_is_sent_with_points(runtime_dir: Path) -> None:
    state = _live_state_with_points(points=7)
    up.save_state(state)
    fake = _FakeTransport(204)
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://mock/ping") is True
    parsed = json.loads(fake.calls[0][1].decode("utf-8"))
    assert set(parsed.keys()) == up.PAYLOAD_KEYS_V2
    assert parsed["points"] == 7


def test_note_explorer_activated(runtime_dir: Path) -> None:
    up.note_explorer_activated()
    assert up.load_state()["stage"] == "explorer"


def test_note_scenarios_calculated_forces_same_day_send(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up.set_consent("on", now=_now())
    fake = _FakeTransport(204)
    assert up.maybe_send_ping(_now(), transport=fake, endpoint_url="http://x/ping") is True
    assert len(fake.calls) == 1
    assert up.load_state()["last_sent_date"] == "2026-10-16"

    sent: list[bool] = []

    def _capture_send(*_a: Any, **_k: Any) -> bool:
        ok = up.maybe_send_ping(
            _now(hour=18), transport=fake, endpoint_url="http://x/ping"
        )
        sent.append(ok)
        return ok

    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: _capture_send() or True)
    up.note_scenarios_calculated(2)
    state = up.load_state()
    assert state["scenarios_calc_count"] == 2
    assert sent == [True]
    assert len(fake.calls) == 2
    assert state["last_sent_date"] == "2026-10-16"


def test_note_scenarios_calculated_bypasses_retry_gate(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    up.set_consent("on", now=_now())
    fake = _FakeTransport(500)
    t0 = _now(hour=10)
    assert up.maybe_send_ping(t0, transport=fake, endpoint_url="http://x/ping") is False
    assert up.load_state().get("last_attempt_at")

    fake.status = 200
    sent: list[bool] = []

    def _capture_send(*_a: Any, **_k: Any) -> bool:
        ok = up.maybe_send_ping(
            t0 + timedelta(minutes=15), transport=fake, endpoint_url="http://x/ping"
        )
        sent.append(ok)
        return ok

    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: _capture_send() or True)
    up.note_scenarios_calculated(1)
    assert sent == [True]
    assert up.load_state()["scenarios_calc_count"] == 1
    assert up.load_state()["last_sent_date"] == "2026-10-16"


def test_note_scenarios_calculated_rejects_non_positive(runtime_dir: Path) -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        up.note_scenarios_calculated(0)


def test_note_scenarios_calculated_no_send_without_consent(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawns: list[int] = []
    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: spawns.append(1) or True)
    up.note_scenarios_calculated(3)
    assert up.load_state()["scenarios_calc_count"] == 3
    assert spawns == []


def test_note_live_cycle_success_skips_shadow(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    up.note_live_cycle_success()
    assert up.load_state().get("stage") != "live"

    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    up.note_live_cycle_success()
    assert up.load_state()["stage"] == "live"


def test_spawn_maybe_send_ping_single_flight(
    runtime_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Avoid consent-time points refresh spawning a real send before this test.
    monkeypatch.setattr("runtime_store.usage_points.refresh_points", lambda: False)
    up.set_consent("on", now=_now())
    up.reset_send_in_flight_for_tests()
    started = threading.Event()
    release = threading.Event()
    calls: list[int] = []

    def _slow_send(*_args: Any, **_kwargs: Any) -> bool:
        calls.append(1)
        started.set()
        release.wait(timeout=2.0)
        return True

    monkeypatch.setattr(up, "maybe_send_ping", _slow_send)
    assert up.spawn_maybe_send_ping() is True
    assert started.wait(timeout=1.0)
    assert up.spawn_maybe_send_ping() is False
    release.set()
    deadline = time.monotonic() + 2.0
    while up._send_in_flight and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)
    assert len(calls) == 1
    assert up.spawn_maybe_send_ping() is True
    deadline = time.monotonic() + 2.0
    while up._send_in_flight and time.monotonic() < deadline:  # noqa: SLF001
        time.sleep(0.01)
    assert len(calls) == 2
