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

    def test_read_check_missing_text_io_is_warning(self):
        with patch.object(lc.loxone_client, "fetch_loxone_raw_value", return_value=None):
            result = lc._read_check(
                "Event-Trigger Test",
                "Ernie_EAuto_FertigUm",
                read_raw=True,
                warn_if_missing=True,
            )
        assert result.passed is False
        assert result.severity == "warning"
        assert lc._check_counts_as_ok(result) is True


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

    def test_collects_swimspa_filter_ios(self):
        consumers = [
            {
                "id": "swimspa_filter",
                "signal_type": "binary",
                "daily_target_source": "loxone_remaining_hours",
                "loxone_target_hours_name": "Ernie_Swimspa_Filter_Sollstunden",
                "loxone_inputs": {
                    "power_name": "homie_bwa_spa_filter2",
                    "signal_type": "binary",
                },
                "loxone_outputs": {"enable_name": "Ernie_Swimspa_Filter_Freigabe"},
                "filter_schedule": {
                    "enabled": True,
                    "loxone": {
                        "native_start_hour_name": "homie_bwa_spa_filter1hour",
                        "native_duration_hours_name": "homie_bwa_spa_filter1durationhours",
                    },
                },
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
        assert "Verbraucher swimspa_filter Sollstunden" in labels
        assert "Verbraucher swimspa_filter Filter Start-Stunde" in labels
        assert "Verbraucher swimspa_filter Filter Dauer (h)" in labels
        assert "Verbraucher swimspa_filter Freigabe" in labels

    def test_binary_consumer_uses_binary_validation(self):
        consumer = {
            "id": "swimspa_filter",
            "signal_type": "binary",
            "loxone_inputs": {"power_name": "F", "signal_type": "binary"},
        }
        assert lc._consumer_power_validate(consumer) is lc._binary_valid


class TestLoxoneIntegrationGate:
    def test_integration_skips_without_credentials(self, monkeypatch):
        from tests import conftest as ct

        monkeypatch.setattr(ct, "_load_dotenv_for_tests", lambda: None)
        monkeypatch.delenv("ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION", raising=False)
        monkeypatch.delenv("LOXONE_IP", raising=False)
        monkeypatch.delenv("LOXONE_USER", raising=False)
        monkeypatch.delenv("LOXONE_PASS", raising=False)
        assert ct._loxone_integration_enabled() is False

    def test_integration_honours_skip_flag(self, monkeypatch):
        from tests import conftest as ct

        monkeypatch.setenv("ENERGY_OPTIMIZER_SKIP_LOXONE_INTEGRATION", "1")
        monkeypatch.setenv("LOXONE_IP", "10.0.0.1")
        monkeypatch.setenv("LOXONE_USER", "u")
        monkeypatch.setenv("LOXONE_PASS", "p")
        assert ct._loxone_integration_enabled() is False


class TestVerifySetupAggregation:
    def test_verify_reports_failure_from_read_checks(self):
        with patch.object(lc, "ensure_live_config"), patch.object(
            lc, "run_read_checks",
            return_value=[lc.LoxoneCheck("Test", "IO", False, "fehlgeschlagen")],
        ):
            ok, results = lc.verify_loxone_setup()
        assert ok is False
        assert len(results) == 1
