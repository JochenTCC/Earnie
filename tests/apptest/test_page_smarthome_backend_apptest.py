"""AppTest-Smoketest für Smarthome-Backend (SB) — echtes Rendering, headless.

Der Discovery-Scan macht echte Netzwerk-I/O (mDNS/SSDP) — für Tests immer
gemockt, sonst wäre jeder Render-Aufruf langsam/nicht-deterministisch (siehe
integrations/integration_scanner.py, gegen echte Hardware verifiziert, aber
in CI ohne Netzwerkzugriff).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from integrations.integration_scanner import DiscoveredBackend

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_smarthome_backend.py"


@pytest.fixture(autouse=True)
def _no_loxone_credentials(monkeypatch):
    monkeypatch.delenv("LOXONE_IP", raising=False)
    monkeypatch.delenv("LOXONE_USER", raising=False)
    monkeypatch.delenv("LOXONE_PASS", raising=False)
    monkeypatch.delenv("EARNIE_INSTALL_CONTEXT", raising=False)


@pytest.fixture(autouse=True)
def _mock_scan_no_network(monkeypatch):
    mock = MagicMock(return_value=[])
    monkeypatch.setattr("ui.pages.page_smarthome_backend.scan_for_backends", mock)
    return mock


def test_renders_without_exception():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception


def test_shows_zero_results_hint_when_scan_finds_nothing():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert any("Kein Smarthome-Backend gefunden" in w.value for w in at.warning)


def test_offers_manual_selection_fallback():
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert any("Manuelle Auswahl" in md.value for md in at.markdown)


def test_shows_single_hit_confirmation(monkeypatch):
    hit = DiscoveredBackend(
        kind="loxone",
        host="192.168.178.20",
        method="ssdp",
        port=80,
        name="Loxone Miniserver Miniserver-Gen2",
    )
    monkeypatch.setattr(
        "ui.pages.page_smarthome_backend.scan_for_backends",
        MagicMock(return_value=[hit]),
    )
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert any("Gefunden" in info.value and "Loxone" in info.value for info in at.info)
    assert any(b.label == "Dieses Backend verwenden" for b in at.button)


def test_shows_configured_summary_when_hub_credentials_present(monkeypatch):
    # LOXONE_IP is a real address on the dev LAN this was verified against — the
    # import section would otherwise make a real HTTP probe; not what this test
    # is about (see test_ehal_greenfield_import_ui.py for that), so stub it out.
    monkeypatch.setattr(
        "ui.pages.page_smarthome_backend._render_backend_import_section",
        lambda backend: None,
    )
    monkeypatch.setenv("LOXONE_IP", "192.168.178.20")
    monkeypatch.setenv("LOXONE_USER", "earnie")
    monkeypatch.setenv("LOXONE_PASS", "secret")
    at = AppTest.from_file(str(_SCRIPT)).run()
    assert not at.exception
    assert any("Smarthome-Backend verbunden" in s.value for s in at.success)
    assert any(sh.value == "Anbindung" for sh in at.subheader)
