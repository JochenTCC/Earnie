"""Integrationstests gegen einen echten Loxone-Miniserver (nur lesend).

Laufen automatisch bei `pytest`, wenn `.env` mit LOXONE_IP/USER/PASS und
`config/config.json` vorhanden sind. Überspringen: ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION=1

Nur diese Datei:
    pytest tests/test_loxone_integration.py -v
"""
from __future__ import annotations

import pytest

from integrations.loxone_connectivity import (
    _check_counts_as_ok,
    run_read_checks,
    verify_loxone_setup,
)
from tests.conftest import requires_loxone


@requires_loxone
class TestLoxoneIntegration:
    def test_all_configured_ios_readable(self):
        _, results = verify_loxone_setup()
        failed = [item for item in results if not _check_counts_as_ok(item)]
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

    def test_individual_read_checks_return_details(self):
        from integrations.loxone_connectivity import ensure_live_config

        ensure_live_config()
        results = run_read_checks()
        assert results, "Keine IO-Prüfungen aus config.json abgeleitet"
        for item in results:
            assert item.label
            assert item.detail
