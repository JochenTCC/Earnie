"""Unit tests for Supervisor-proxied Home Assistant helpers."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("EARNIE_OFFLINE", "1")

from integrations import ha_supervisor as hs


class TestResolveHaCredentials:
    def test_configured_url_and_token_win(self, monkeypatch):
        monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
        monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)
        assert hs.resolve_ha_base_url("http://ha:8123") == "http://ha:8123"
        assert hs.resolve_ha_token("llat") == "llat"

    def test_addon_defaults_to_supervisor_core(self, monkeypatch):
        monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
        monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
        assert hs.resolve_ha_base_url("") == hs.SUPERVISOR_CORE_BASE_URL
        assert hs.resolve_ha_token("") == "sup-token"

    def test_manual_install_does_not_invent_url(self, monkeypatch):
        monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)
        monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
        assert hs.resolve_ha_base_url("") == ""
        assert hs.resolve_ha_token("") == "sup-token"


class TestDiscoverViaSupervisor:
    def test_returns_hit_when_probe_ok(self, monkeypatch):
        monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
        monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
        with patch.object(hs, "probe_supervisor_core", return_value=True):
            hits = hs.discover_home_assistant_via_supervisor()
        assert len(hits) == 1
        assert hits[0].method == "supervisor"
        assert hits[0].extra["base_url"] == hs.SUPERVISOR_CORE_BASE_URL

    def test_empty_without_token(self, monkeypatch):
        monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
        monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
        assert hs.discover_home_assistant_via_supervisor() == []

    def test_probe_uses_bearer_header(self, monkeypatch):
        monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
        response = MagicMock()
        response.status = 200
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            assert hs.probe_supervisor_core() is True
        request = urlopen.call_args[0][0]
        assert request.get_header("Authorization") == "Bearer sup-token"
        assert request.full_url.endswith("/api/")


class TestGetHaAdapterSupervisorResolve:
    def test_uses_supervisor_defaults(self, monkeypatch):
        import integrations.ehal_live as ehal_live

        monkeypatch.setenv("EARNIE_INSTALL_CONTEXT", "homeassistant_addon")
        monkeypatch.setenv("SUPERVISOR_TOKEN", "sup-token")
        monkeypatch.setattr(
            ehal_live.config,
            "get",
            lambda key, default=None: {
                "EHAL_HA_BASE_URL": "",
                "EHAL_HA_TOKEN": "",
                "EHAL_HA_ENTITIES": {},
                "EHAL_HA_SIGN": {},
                "EHAL_ADAPTER_ID": "ha-home",
                "GLOBAL_TIMEOUT": 5,
            }.get(key, default),
        )
        ehal_live.reset_adapter_cache()
        adapter = ehal_live.get_ha_adapter()
        assert adapter.cfg.base_url == hs.SUPERVISOR_CORE_BASE_URL
        assert adapter.cfg.token == "sup-token"
        ehal_live.reset_adapter_cache()
