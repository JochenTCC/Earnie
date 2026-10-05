"""ENTSO-E A44 client: fixture XML parse, QH expand, token redaction."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from integrations.entsoe_client import (
    ZONE_TO_EIC,
    fetch_entsoe_day_ahead_prices,
    parse_entsoe_a44_xml,
    read_entsoe_api_token,
    redact_entsoe_url,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "entsoe"
TZ = ZoneInfo("Europe/Vienna")


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


def test_fetch_returns_none_without_token(monkeypatch):
    monkeypatch.delenv("ENTSOE_API_TOKEN", raising=False)
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
