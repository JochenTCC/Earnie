"""Clock-skew diagnostics from HTTP Date headers (spec early-start-scheduling §7)."""
from __future__ import annotations

import logging
from email.utils import format_datetime
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from runtime_store import clock_skew as cs

T0 = 1_792_000_000.0  # fixed local epoch for samples


@pytest.fixture(autouse=True)
def _reset():
    cs.reset()
    yield
    cs.reset()


def _date(epoch: float) -> str:
    return format_datetime(datetime.fromtimestamp(epoch, tz=timezone.utc), usegmt=True)


def test_sample_uses_midpoint_and_half_second():
    # Server stamped 1000.0 (truncated); request took 0.4 s, received at local 1000.2.
    sample = cs.sample_from_response(
        _date(T0), received_epoch=T0 + 0.2, elapsed_sec=0.4, host="api.example.org"
    )
    assert sample is not None
    assert sample.offset_sec == pytest.approx(0.5 - 0.0)  # (T0+0.5) - (T0+0.2-0.2)
    assert sample.uncertainty_sec == pytest.approx(0.7)


def test_slow_or_broken_responses_are_ignored():
    assert cs.sample_from_response(_date(T0), received_epoch=T0, elapsed_sec=3.0, host="h.org") is None
    assert cs.sample_from_response("not a date", received_epoch=T0, elapsed_sec=0.1, host="h.org") is None


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.org/x",  # not HTTPS
        "https://192.168.1.10/data",  # LAN device
        "https://127.0.0.1/x",
        "https://miniserver/x",  # no dot
        "https://homeassistant.local/api",
    ],
)
def test_lan_and_plain_http_hosts_are_ignored(url):
    cs.observe_response(url, {"Date": _date(T0)}, 0.1, received_epoch=T0)
    for _ in range(4):
        cs.observe_response(url, {"Date": _date(T0)}, 0.1, received_epoch=T0)
    assert cs.current_estimate(now_epoch=T0) is None


def test_estimate_is_median_and_needs_three_samples():
    for skew in (3.0, 3.2):
        cs.observe_response(
            "https://api.open-meteo.com/v1/forecast", {"Date": _date(T0 + skew)}, 0.0, received_epoch=T0
        )
    assert cs.current_estimate(now_epoch=T0) is None
    cs.observe_response("https://web-api.tp.entsoe.eu/api", {"Date": _date(T0 + 30)}, 0.0, received_epoch=T0)
    estimate = cs.current_estimate(now_epoch=T0)
    assert estimate is not None
    assert estimate.samples == 3
    assert estimate.offset_sec == pytest.approx(3.5)  # median 3.0 → +0.5 (outlier 30 ignored)
    assert estimate.hosts == ("api.open-meteo.com", "web-api.tp.entsoe.eu")


def test_old_samples_expire():
    for _ in range(3):
        cs.observe_response("https://a.org/", {"Date": _date(T0)}, 0.0, received_epoch=T0)
    assert cs.current_estimate(now_epoch=T0 + cs.SAMPLE_MAX_AGE_SEC + 1) is None


def test_warning_above_two_seconds_with_ntp_hint_at_most_hourly(caplog):
    big = cs.SkewEstimate(offset_sec=-4.2, samples=5, hosts=("a.org",))
    small = cs.SkewEstimate(offset_sec=1.5, samples=5, hosts=("a.org",))
    with caplog.at_level(logging.WARNING, logger="clock_skew"):
        assert not cs.maybe_warn(small, now_epoch=T0)
        assert cs.maybe_warn(big, now_epoch=T0)
        assert not cs.maybe_warn(big, now_epoch=T0 + 600)
        assert cs.maybe_warn(big, now_epoch=T0 + cs.WARN_REPEAT_SEC + 1)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 2
    assert "4.2 s vor" in messages[0] and "NTP" in messages[0]


def test_requests_hook_observes_date_header_without_touching_response(monkeypatch):
    sent = []

    def fake_send(self, request, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response.url = request.url
        response.headers["Date"] = _date(T0)
        response.elapsed = __import__("datetime").timedelta(seconds=0.1)
        sent.append(request.url)
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    monkeypatch.setattr(cs, "_hook_installed", False)
    cs.install_requests_hook()
    cs.install_requests_hook()  # idempotent
    with patch.object(cs, "observe_response", wraps=cs.observe_response) as observed:
        response = requests.get("https://api.example.org/ping")
    assert response.status_code == 200
    assert observed.call_count == 1
    assert observed.call_args.args[0] == "https://api.example.org/ping"


def test_requests_hook_survives_observer_errors(monkeypatch):
    def fake_send(self, request, **kwargs):
        response = requests.Response()
        response.status_code = 204
        response.url = request.url
        return response

    monkeypatch.setattr(requests.Session, "send", fake_send)
    monkeypatch.setattr(cs, "_hook_installed", False)
    cs.install_requests_hook()
    with patch.object(cs, "observe_response", side_effect=RuntimeError("bug")):
        assert requests.get("https://api.example.org/x").status_code == 204


def test_cycle_record_carries_clock_skew(monkeypatch):
    from runtime_store.cycle_duration_stats import CycleStats

    for _ in range(3):
        cs.observe_response("https://a.org/", {"Date": _date(T0 + 1)}, 0.0, received_epoch=T0)
    monkeypatch.setattr(cs.time, "time", lambda: T0)
    stats = CycleStats(trigger="quarter_hour", started_at=datetime(2026, 10, 15, 13, 0))
    row = stats.to_record(outcome="ok", finished_at=datetime(2026, 10, 15, 13, 0, 5), version="t")
    assert row["clock_skew_sec"] == pytest.approx(1.5)
