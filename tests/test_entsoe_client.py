"""ENTSO-E A44 client: fixture XML parse, QH expand, token redaction, Shadow R4."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import config
from integrations.entsoe_client import (
    FEED_KEY,
    ZONE_TO_EIC,
    fetch_entsoe_day_ahead_prices,
    parse_entsoe_a44_xml,
    read_entsoe_api_token,
    redact_entsoe_url,
)
from runtime_store.shadow import feed as shadow_feed
from runtime_store.shadow import reader as shadow_reader
from runtime_store.shadow import replay as shadow_replay
from tests.config_fixtures import minimal_config_payload, write_minimal_config_tree

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "entsoe"
TZ = ZoneInfo("Europe/Vienna")


def _pt15m_xml() -> str:
    return (FIXTURES / "a44_pt15m.xml").read_text(encoding="utf-8")


def _utc(offset_sec: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=offset_sec)
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _enable_feed(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("EARNIE_SHADOW", raising=False)
    config_path, scenarios_path = write_minimal_config_tree(
        tmp_path,
        config_payload=minimal_config_payload(),
    )
    local_path = tmp_path / "local_settings.json"
    local_path.write_text(
        json.dumps(
            {
                "silent_mode": True,
                "shadow_feed_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    feed_path = tmp_path / "shadow_feed"
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed_path))
    monkeypatch.setenv("EARNIE_CONFIG_PATH", str(Path(config_path).parent))
    cfg = config.Config(
        config_path=config_path,
        backtesting_scenarios_path=scenarios_path,
        local_settings_path=str(local_path),
        require_loxone_credentials=False,
    )
    monkeypatch.setattr(config, "CONFIG", cfg)
    shadow_feed.reset_for_tests()
    return feed_path


def _write_feed(feed: Path, records: dict) -> None:
    feed.mkdir(parents=True, exist_ok=True)
    hb = _utc()
    (feed / "meta.json").write_text(
        json.dumps(
            {
                "feed_schema": 1,
                "earnie_version": "2.7.0",
                "earnie_data_model": 4,
                "ehal_backend": "ha",
                "prod_runtime_dir": "/prod",
                "heartbeat_ts": hb,
                "cycle_seq": 1,
            }
        ),
        encoding="utf-8",
    )
    (feed / "latest.json").write_text(
        json.dumps({"cycle_seq": 1, "cycle_ts": hb, "records": records}),
        encoding="utf-8",
    )


def test_zone_eic_map_covers_supported_markets():
    assert ZONE_TO_EIC["AT"] == "10YAT-APG------L"
    assert ZONE_TO_EIC["DE-LU"] == "10Y1001A1001A82H"
    assert ZONE_TO_EIC["CH"] == "10YCH-SWISSGRIDZ"


def test_parse_pt15m_fixture():
    xml = (FIXTURES / "a44_pt15m.xml").read_text(encoding="utf-8")
    df = parse_entsoe_a44_xml(xml)
    assert len(df) == 8
    assert float(df.iloc[0]["price_cent_kwh"]) == pytest.approx(19.246)
    assert df.index[0] == datetime(2026, 10, 5, 0, 0)


def test_parse_pt60m_expands_to_quarter_hours():
    xml = (FIXTURES / "a44_pt60m.xml").read_text(encoding="utf-8")
    df = parse_entsoe_a44_xml(xml)
    assert len(df) == 16
    first_hour = df.iloc[:4]["price_cent_kwh"].tolist()
    assert first_hour == pytest.approx([19.211, 19.211, 19.211, 19.211])
    assert df.index[1] == datetime(2026, 10, 5, 0, 15)


def test_redact_security_token_from_url():
    url = (
        "https://web-api.tp.entsoe.eu/api?documentType=A44"
        "&securityToken=super-secret&in_Domain=10YAT-APG------L"
    )
    redacted = redact_entsoe_url(url)
    assert "super-secret" not in redacted
    assert "securityToken=REDACTED" in redacted


def test_fetch_returns_none_without_token(monkeypatch, tmp_path):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    # Isolate from a developer .env that may still hold ENTSOE_API_TOKEN.
    empty_dotenv = tmp_path / ".env"
    empty_dotenv.write_text("", encoding="utf-8")
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(empty_dotenv))
    start = datetime(2026, 10, 5, 0, 0, tzinfo=TZ)
    end = datetime(2026, 10, 6, 0, 0, tzinfo=TZ)
    assert fetch_entsoe_day_ahead_prices(start, end, "AT") is None


def test_read_entsoe_api_token_strips_quotes(monkeypatch):
    monkeypatch.setenv("ENTSOE_API_TOKEN", '"abc-token"')
    assert read_entsoe_api_token() == "abc-token"


def test_read_entsoe_api_token_falls_back_to_dotenv_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text('ENTSOE_API_TOKEN="from-file-token"\n', encoding="utf-8")
    monkeypatch.setenv("EARNIE_DOTENV_PATH", str(dotenv))
    assert read_entsoe_api_token() == "from-file-token"
    assert os.environ.get("ENTSOE_API_TOKEN") == "from-file-token"


def test_prod_fetch_records_ext_prices_entsoe(tmp_path, monkeypatch):
    feed_path = _enable_feed(tmp_path, monkeypatch)
    monkeypatch.setenv("ENTSOE_API_TOKEN", "prod-secret-token")
    xml = _pt15m_xml()
    response = MagicMock()
    response.status_code = 200
    response.text = xml
    response.url = (
        "https://web-api.tp.entsoe.eu/api?securityToken=prod-secret-token"
    )
    response.raise_for_status = MagicMock()
    monkeypatch.setattr(
        "integrations.entsoe_client.requests.get",
        MagicMock(return_value=response),
    )

    start = datetime(2026, 10, 5, 0, 0, tzinfo=TZ)
    end = datetime(2026, 10, 6, 0, 0, tzinfo=TZ)
    df = fetch_entsoe_day_ahead_prices(start, end, "AT")
    assert len(df) == 8

    shadow_feed.flush_after_cycle()
    latest = json.loads((feed_path / "latest.json").read_text(encoding="utf-8"))
    record = latest["records"][FEED_KEY]
    assert record["ok"] is True
    assert record["payload"] == xml
    assert "prod-secret-token" not in json.dumps(record)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jsonl = (feed_path / f"feed-{day}.jsonl").read_text(encoding="utf-8")
    assert FEED_KEY in jsonl
    assert "prod-secret-token" not in jsonl


def test_shadow_replay_skips_requests(tmp_path, monkeypatch):
    shadow_feed.reset_for_tests()
    shadow_reader.reset_reader_for_tests()
    shadow_replay.reset_replay_for_tests()
    feed = tmp_path / "feed"
    xml = _pt15m_xml()
    _write_feed(
        feed,
        {
            FEED_KEY: {
                "key": FEED_KEY,
                "ts": _utc(),
                "ok": True,
                "status": 200,
                "payload": xml,
                "error": None,
            }
        },
    )
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("ENTSOE_API_TOKEN", "shadow-token")
    get_mock = MagicMock(side_effect=AssertionError("must not call ENTSO-E"))
    monkeypatch.setattr("integrations.entsoe_client.requests.get", get_mock)

    start = datetime(2026, 10, 5, 0, 0, tzinfo=TZ)
    end = datetime(2026, 10, 6, 0, 0, tzinfo=TZ)
    df = fetch_entsoe_day_ahead_prices(start, end, "AT")
    assert len(df) == 8
    assert float(df.iloc[0]["price_cent_kwh"]) == pytest.approx(19.246)
    get_mock.assert_not_called()


def test_shadow_miss_live_fallback_unrecorded(tmp_path, monkeypatch):
    shadow_feed.reset_for_tests()
    shadow_reader.reset_reader_for_tests()
    shadow_replay.reset_replay_for_tests()
    feed = tmp_path / "feed"
    _write_feed(feed, {})
    monkeypatch.setenv("EARNIE_SHADOW", "1")
    monkeypatch.setenv("EARNIE_SHADOW_FEED_PATH", str(feed))
    monkeypatch.setenv("ENTSOE_API_TOKEN", "fallback-token")

    xml = _pt15m_xml()
    response = MagicMock()
    response.status_code = 200
    response.text = xml
    response.url = "https://web-api.tp.entsoe.eu/api?securityToken=fallback-token"
    response.raise_for_status = MagicMock()
    get_mock = MagicMock(return_value=response)
    monkeypatch.setattr("integrations.entsoe_client.requests.get", get_mock)
    record_mock = MagicMock()
    monkeypatch.setattr(
        "runtime_store.shadow.transport.record_transport", record_mock
    )

    start = datetime(2026, 10, 5, 0, 0, tzinfo=TZ)
    end = datetime(2026, 10, 6, 0, 0, tzinfo=TZ)
    df = fetch_entsoe_day_ahead_prices(start, end, "AT")
    assert len(df) == 8
    get_mock.assert_called_once()
    record_mock.assert_not_called()
