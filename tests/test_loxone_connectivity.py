"""Unit-Tests für Loxone-Verbindungsprüfung (ohne echten Miniserver)."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from integrations import loxone_connectivity as lc


class TestLoxoneEnvHelpers:
    def test_loxone_env_configured_false_when_incomplete(self, monkeypatch):
        monkeypatch.delenv("LOXONE_IP", raising=False)
        monkeypatch.setenv("LOXONE_USER", "u")
        monkeypatch.setenv("LOXONE_PASS", "p")
        assert lc.loxone_env_configured() is False

    def test_loxone_env_configured_true_when_complete(self, monkeypatch):
        monkeypatch.setenv("LOXONE_IP", "10.0.0.1")
        monkeypatch.setenv("LOXONE_USER", "u")
        monkeypatch.setenv("LOXONE_PASS", "p")
        assert lc.loxone_env_configured() is True


class TestReadCheckValidation:
    def test_soc_validation_rejects_out_of_range(self):
        assert lc._soc_valid(105.0) is not None

    def test_power_validation_accepts_typical_value(self):
        assert lc._power_valid(2.5) is None

    def test_binary_validation(self):
        assert lc._binary_valid(1.0) is None
        assert lc._binary_valid(0.5) is not None


class TestCollectReadChecks:
    def test_collects_flexible_consumer_ios(self):
        consumers = [
            {
                "id": "swimspa",
                "loxone_inputs": {"power_name": "P_Spa"},
                "loxone_outputs": {"enable_name": "En_Spa"},
                "charging_schedule": None,
            }
        ]
        with patch.object(lc.config, "get", side_effect=lambda name, **kw: {
            "LOXONE_SOC_NAME": "SOC",
            "LOXONE_PV_POWER_NAME": "PV",
            "LOXONE_BATTERY_POWER_NAME": "BAT",
            "LOXONE_GRID_POWER_NAME": "GRID",
            "LOXONE_PV_COUNTER_NAME": "CNT",
        }.get(name)), patch.object(lc.config, "get_flexible_consumers", return_value=consumers):
            checks = lc.collect_read_checks()

        labels = [label for label, _, _ in checks]
        assert "Verbraucher swimspa Leistung" in labels
        assert "Verbraucher swimspa Freigabe" in labels


class TestVerifySetupAggregation:
    def test_verify_reports_failure_from_read_checks(self):
        with patch.object(lc, "ensure_live_config"), patch.object(
            lc, "run_read_checks",
            return_value=[lc.LoxoneCheck("Test", "IO", False, "fehlgeschlagen")],
        ):
            ok, results = lc.verify_loxone_setup()
        assert ok is False
        assert len(results) == 1

    def test_roundtrip_fails_when_send_fails(self):
        with patch.object(lc.config, "get", return_value="SoC_IO"), patch.object(
            lc.loxone_client, "fetch_loxone_generic_value", return_value=50.0
        ), patch.object(lc.loxone_client, "send_loxone_value", return_value=False):
            result = lc.check_roundtrip_soc()
        assert result.passed is False
        assert "Senden" in result.detail
