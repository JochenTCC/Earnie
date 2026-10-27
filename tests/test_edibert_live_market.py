"""Live Day-Ahead prices through Edibert (Edibert P4a): zone, shadow transport, chain."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests
from edibert import api

from data import edibert_live_market as elm
from house_config.edibert_tariffs import EdibertLoadError

TZ = ZoneInfo("Europe/Vienna")
DAY_START = datetime(2026, 12, 14, 23, 0, tzinfo=UTC)  # 2026-12-15 00:00 Vienna
MORNING = datetime(2026, 12, 15, 10, 0, tzinfo=TZ)  # tomorrow not published yet
EC_URL = "https://api.energy-charts.info/price"
ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"


def _energy_charts(start: datetime, hours: int) -> dict:
    stamps = [int((start + timedelta(minutes=15 * i)).timestamp()) for i in range(hours * 4)]
    return {"unix_seconds": stamps, "price": [100.0 + i % 4 for i in range(hours * 4)]}


class _Response:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code


class _Web:
    """Fake ``requests.get`` per host; a value that is an exception is raised."""

    def __init__(self, **answers) -> None:
        self.answers = answers
        self.hosts: list[str] = []

    def __call__(self, url, params=None, **_kwargs):
        host = url.split("/")[2]
        self.hosts.append(host)
        answer = self.answers.get(host, requests.ConnectionError(f"no fake for {host}"))
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Runtime dir, house profile land, frozen planning clock, no shadow, no token."""
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    monkeypatch.setattr(elm, "read_entsoe_api_token", lambda: "")
    monkeypatch.setattr(elm.config, "get_planning_timezone", lambda: "Europe/Vienna")
    land = {"value": "AT"}
    monkeypatch.setattr(
        elm.config,
        "get_resolved_runtime_settings",
        lambda: {"_house_profile": {"land": land["value"]}},
    )
    clock = {"now": MORNING}
    monkeypatch.setattr(elm, "planning_now", lambda tz=None: clock["now"])
    events: list[str] = []
    monkeypatch.setattr(elm, "record_cycle_event", events.append)
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "runtime_store.shadow.transport.safe_record",
        lambda key, **kw: recorded.append((key, kw)),
    )
    return {"land": land, "clock": clock, "events": events, "recorded": recorded}


def _install_web(monkeypatch, **answers) -> _Web:
    web = _Web(**answers)
    monkeypatch.setattr(elm.requests, "get", web)
    return web


def test_feed_keys_follow_the_source_host():
    assert elm.feed_key_for_url(ENTSOE_URL) == "ext:prices:entsoe"
    assert elm.feed_key_for_url(EC_URL) == "ext:prices:energy_charts"
    assert elm.feed_key_for_url("https://api.awattar.de/v1/marketdata") == "ext:prices:awattar"
    with pytest.raises(ValueError, match="example.org"):
        elm.feed_key_for_url("https://example.org/price")


def test_fetch_returns_local_rows_with_seven_lead_days_and_records_the_answer(live, monkeypatch):
    payload = json.dumps(_energy_charts(DAY_START - timedelta(days=7), 8 * 24))
    web = _install_web(monkeypatch, **{"api.energy-charts.info": _Response(payload)})
    rows = elm.fetch_live_day_ahead_prices(planning_end=MORNING + timedelta(hours=30))
    assert web.hosts == ["api.energy-charts.info"]
    assert len(rows) == 8 * 96
    first = rows[0]
    assert first["timestamp"] == datetime(2026, 12, 8, 0, 0, tzinfo=TZ)
    assert (first["hour"], first["price_buy"]) == (0, 10.0)
    assert live["events"] == [elm.EVENT_DAY_AHEAD_FETCH]
    assert live["recorded"] == [
        ("ext:prices:energy_charts", {"ok": True, "payload": payload, "status": 200})
    ]


def test_a_cache_that_covers_the_window_makes_no_request(live, monkeypatch):
    payload = json.dumps(_energy_charts(DAY_START - timedelta(days=7), 8 * 24))
    _install_web(monkeypatch, **{"api.energy-charts.info": _Response(payload)})
    first = elm.fetch_live_day_ahead_prices()
    web = _install_web(monkeypatch)
    live["clock"]["now"] = MORNING + timedelta(minutes=30)
    again = elm.fetch_live_day_ahead_prices()
    assert (web.hosts, again) == ([], first)
    assert len(live["events"]) == 1


def test_entsoe_failure_is_recorded_redacted_and_falls_through(live, monkeypatch):
    monkeypatch.setattr(elm, "read_entsoe_api_token", lambda: "hush")
    payload = json.dumps(_energy_charts(DAY_START - timedelta(days=7), 8 * 24))
    _install_web(
        monkeypatch,
        **{
            "web-api.tp.entsoe.eu": requests.ConnectionError(f"{ENTSOE_URL}?securityToken=hush failed"),
            "api.energy-charts.info": _Response(payload),
        },
    )
    rows = elm.fetch_live_day_ahead_prices()
    assert len(rows) == 8 * 96
    key, entry = live["recorded"][0]
    assert key == "ext:prices:entsoe" and entry["ok"] is False
    assert "hush" not in entry["error"] and "REDACTED" in entry["error"]


def test_http_error_is_recorded_and_raised_as_market_source_error(live, monkeypatch):
    _install_web(monkeypatch, **{"api.energy-charts.info": _Response("busy", 503)})
    with pytest.raises(api.MarketSourceError, match="HTTP 503"):
        elm._shadow_get(EC_URL, {"bzn": "AT"}, 5)
    assert live["recorded"] == [
        (
            "ext:prices:energy_charts",
            {"ok": False, "status": 503, "payload": "busy", "error": "HTTP 503"},
        )
    ]


def test_shadow_replays_old_dict_records_as_text_without_network(live, monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    old_record = _energy_charts(DAY_START, 2)
    monkeypatch.setattr(
        "runtime_store.shadow.replay.replay_ext_payload",
        lambda key: old_record if key == "ext:prices:energy_charts" else None,
    )
    web = _install_web(monkeypatch)
    assert json.loads(elm._shadow_get(EC_URL, {}, 5)) == old_record
    assert web.hosts == []
    assert live["recorded"] == []


def test_shadow_miss_falls_back_to_an_unrecorded_live_request(live, monkeypatch):
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setattr("runtime_store.shadow.replay.replay_ext_payload", lambda key: None)
    web = _install_web(monkeypatch, **{"api.awattar.at": _Response("{}")})
    assert elm._shadow_get("https://api.awattar.at/v1/marketdata", {}, 5) == "{}"
    assert web.hosts == ["api.awattar.at"]
    assert live["recorded"] == []


def test_switzerland_has_no_awattar_substitute_and_no_price_is_none(live, monkeypatch):
    live["land"]["value"] = "CH"
    web = _install_web(monkeypatch)
    assert elm.fetch_live_day_ahead_prices() is None
    assert web.hosts == ["api.energy-charts.info"]


def test_a_house_profile_without_land_fails_loud(live, monkeypatch):
    monkeypatch.setattr(elm.config, "get_resolved_runtime_settings", lambda: {})
    with pytest.raises(ValueError, match="Kein Land"):
        elm.fetch_live_day_ahead_prices()


def test_an_unknown_land_fails_loud(live):
    live["land"]["value"] = "FR"
    with pytest.raises(EdibertLoadError):
        elm.fetch_live_day_ahead_prices()
