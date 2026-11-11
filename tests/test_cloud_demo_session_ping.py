"""Anonymous session counter of the cloud demo (earnie-server Dashboard P6)."""
from __future__ import annotations

import json

import pytest

from runtime_store import cloud_demo_session_ping as demo
from runtime_store.server_endpoints import PATH_DEMO_SESSION, url_for


class _FakeTransport:
    def __init__(self, status: int = 204) -> None:
        self.status = status
        self.calls: list[tuple[str, bytes, float]] = []

    def __call__(self, url: str, body: bytes, timeout: float) -> int:
        self.calls.append((url, body, timeout))
        return self.status


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EARNIE_CLOUD_DEMO", "1")
    monkeypatch.delenv("EARNIE_USAGE_PING", raising=False)


def test_sends_only_the_version_field() -> None:
    fake = _FakeTransport()
    assert demo.send_demo_session(transport=fake, endpoint_url="http://x/demo-session") is True
    assert len(fake.calls) == 1
    url, body, timeout = fake.calls[0]
    assert url == "http://x/demo-session"
    assert json.loads(body) == {"v": 1}
    assert timeout == demo.TIMEOUT_SEC


def test_default_endpoint() -> None:
    assert url_for(PATH_DEMO_SESSION) == "https://cloudserver.earnie-hems.com/demo-session"


def test_no_send_outside_the_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    fake = _FakeTransport()
    assert demo.send_demo_session(transport=fake, endpoint_url="http://x") is False
    assert demo.spawn_demo_session_ping() is None
    assert fake.calls == []


def test_kill_switch_stops_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EARNIE_USAGE_PING", "off")
    fake = _FakeTransport()
    assert demo.send_demo_session(transport=fake, endpoint_url="http://x") is False
    assert demo.spawn_demo_session_ping() is None
    assert fake.calls == []


def test_server_error_is_reported_not_raised() -> None:
    assert demo.send_demo_session(transport=_FakeTransport(500), endpoint_url="http://x") is False
    assert demo.send_demo_session(transport=_FakeTransport(0), endpoint_url="http://x") is False


def test_spawn_runs_in_a_daemon_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[int] = []
    monkeypatch.setattr(demo, "send_demo_session", lambda: sent.append(1) or True)
    thread = demo.spawn_demo_session_ping()
    assert thread is not None and thread.daemon
    thread.join(timeout=2)
    assert sent == [1]
