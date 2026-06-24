"""Optionale Integrationstests gegen einen echten Loxone-Miniserver.

Aktivierung:
    set ENERGY_OPTIMIZER_RUN_LOXONE_INTEGRATION=1
    pytest tests/test_loxone_integration.py -m requires_loxone -v

Optional:
    set LOXONE_INTEGRATION_FTP=1          # FTP-Logdatei prüfen
    set LOXONE_INTEGRATION_ROUNDTRIP=1    # SoC-Sollwert Roundtrip (Schreibtest)
"""
from __future__ import annotations

import os

import pytest

from integrations.loxone_connectivity import (
    check_ftp_log_available,
    check_roundtrip_soc,
    run_read_checks,
    verify_loxone_setup,
)
from tests.conftest import requires_loxone


@requires_loxone
class TestLoxoneIntegration:
    def test_all_configured_ios_readable(self):
        _, results = verify_loxone_setup()
        failed = [item for item in results if not item.passed]
        assert not failed, "\n".join(
            f"{item.label} ({item.io_name}): {item.detail}" for item in failed
        )

    def test_live_power_aggregate(self):
        from integrations import loxone_client
        from integrations.loxone_connectivity import ensure_live_config

        ensure_live_config()
        live = loxone_client.fetch_loxone_live_power()
        assert live is not None, "fetch_loxone_live_power lieferte None"
        assert live["house"] == pytest.approx(
            live["pv"] + live["battery"] + live["grid"], abs=0.05
        )

    @pytest.mark.skipif(
        os.getenv("LOXONE_INTEGRATION_FTP") != "1",
        reason="LOXONE_INTEGRATION_FTP=1 für FTP-Prüfung setzen",
    )
    def test_ftp_log_available(self):
        from integrations.loxone_connectivity import ensure_live_config

        ensure_live_config()
        result = check_ftp_log_available()
        assert result.passed, result.detail

    @pytest.mark.skipif(
        os.getenv("LOXONE_INTEGRATION_ROUNDTRIP") != "1",
        reason="LOXONE_INTEGRATION_ROUNDTRIP=1 für Schreib-Roundtrip setzen",
    )
    def test_soc_roundtrip_without_change(self):
        from integrations.loxone_connectivity import ensure_live_config

        ensure_live_config()
        result = check_roundtrip_soc()
        assert result.passed, result.detail

    def test_individual_read_checks_return_details(self):
        from integrations.loxone_connectivity import ensure_live_config

        ensure_live_config()
        results = run_read_checks()
        assert results, "Keine IO-Prüfungen aus config.json abgeleitet"
        for item in results:
            assert item.label
            assert item.detail
