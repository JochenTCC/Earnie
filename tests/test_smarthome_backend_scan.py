"""Unit tests for SB scan helpers (no Streamlit render)."""
from __future__ import annotations

from unittest.mock import MagicMock

from integrations.integration_scanner import DiscoveredBackend
from ui.pages import page_smarthome_backend as sb


def test_describe_hit_includes_port_and_name():
    hit = DiscoveredBackend(
        kind="loxone", host="192.0.2.10", method="ssdp", port=80, name="MS"
    )
    text = sb._describe_hit(hit)
    assert "`192.0.2.10`" in text
    assert ":80" in text
    assert "MS" in text


def test_run_scan_active_uses_full_active(monkeypatch):
    mock = MagicMock(return_value=[])
    monkeypatch.setattr(sb, "scan_for_backends", mock)
    sb._run_scan(active=True)
    mock.assert_called_once_with("full_active")


def test_run_scan_widens_empty_targeted(monkeypatch):
    mock = MagicMock(side_effect=[[], ["ha"]])
    monkeypatch.setattr(sb, "scan_for_backends", mock)
    monkeypatch.setattr(sb, "install_context_target_kinds", lambda: ("loxone",))
    assert sb._run_scan(active=False) == ["ha"]
    assert mock.call_args_list[0].args[0] == "targeted"
    assert mock.call_args_list[1].args == ("full_passive",)


def test_run_scan_full_passive_when_no_install_kinds(monkeypatch):
    mock = MagicMock(return_value=["loxone"])
    monkeypatch.setattr(sb, "scan_for_backends", mock)
    monkeypatch.setattr(sb, "install_context_target_kinds", lambda: ())
    assert sb._run_scan(active=False) == ["loxone"]
    mock.assert_called_once()
    assert mock.call_args.args[0] == "full_passive"
