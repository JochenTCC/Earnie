"""Unit-Tests für Loxone-Verbindungsprüfung (ohne echten Miniserver)."""
from __future__ import annotations

import os
from unittest.mock import patch

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
                "ev1:get_evcs_ready_by_time",
                "Ernie_EAuto_FertigUm",
                read_raw=True,
                warn_if_missing=True,
            )
        assert result.passed is False
        assert result.severity == "warning"
        assert lc._check_counts_as_ok(result) is True


class TestCollectReadChecks:
    def _plant_get(self, name, **kw):
        return {
            "LOXONE_SOC_NAME": "SOC",
            "LOXONE_PV_POWER_NAME": "PV",
            "LOXONE_BATTERY_POWER_NAME": "BAT",
            "LOXONE_GRID_POWER_NAME": "GRID",
            "LOXONE_CONSUMERS_POWER_NAME": "",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "CHG",
            "LOXONE_CONTROL_CMD_NAME": "CMD",
        }.get(name)

    def test_plant_labels_are_ehal_sens_fields(self):
        with patch.object(lc.config, "get", side_effect=self._plant_get), patch.object(
            lc.config, "get_flexible_consumers", return_value=[]
        ), patch.object(
            lc.config.CONFIG, "get_resolved_runtime_settings", return_value={}
        ):
            checks = lc.collect_read_checks()

        labels = [label for label, _, _ in checks]
        assert labels == [
            "sens_ess_soc",
            "sens_pv_production_active",
            "sens_ess_power",
            "sens_grid_power_active",
        ]
        assert "PV-Zähler" not in labels
        assert all(not lbl.startswith("set_") for lbl in labels)

    def test_collects_ev_sens_get_ios(self):
        consumers = [
            {
                "id": "ev1",
                "type": "ev",
                "loxone_inputs": {"power_name": "P_EV"},
                "loxone_outputs": {"enable_name": "En_EV"},
                "charging_schedule": {
                    "enabled": True,
                    "loxone": {
                        "plugged_in_name": "Plug",
                        "actual_soc_name": "EvSoc",
                        "ready_by_time_name": "Ready",
                    },
                },
            }
        ]
        with patch.object(lc.config, "get", side_effect=self._plant_get), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ), patch.object(
            lc.config.CONFIG, "get_resolved_runtime_settings", return_value={}
        ):
            checks = lc.collect_read_checks()

        labels = [label for label, _, _ in checks]
        assert "ev1:sens_evcs_active_power" in labels
        assert "ev1:sens_evcs_connected" in labels
        assert "ev1:sens_evcs_soc_act" in labels
        assert "ev1:get_evcs_ready_by_time" in labels
        assert "ev1:flex.power_name" not in labels

    def test_collects_non_ev_flex_power(self):
        consumers = [
            {
                "id": "swimspa",
                "loxone_inputs": {"power_name": "P_Spa"},
                "loxone_outputs": {"enable_name": "En_Spa"},
                "charging_schedule": None,
            },
            {
                "id": "wp_heating",
                "type": "thermal_annual",
                "loxone_inputs": {"power_name": "P_WP"},
            },
        ]
        with patch.object(lc.config, "get", side_effect=self._plant_get), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ), patch.object(
            lc.config.CONFIG, "get_resolved_runtime_settings", return_value={}
        ):
            checks = lc.collect_read_checks()

        by_label = {label: io for label, io, _ in checks}
        assert by_label["swimspa:flex.power_name"] == "P_Spa"
        assert by_label["wp_heating:flex.power_name"] == "P_WP"
        assert "swimspa:flex.enable_name" not in by_label

    def test_ev_detected_without_type_via_charging_loxone(self):
        consumers = [
            {
                "id": "ev",
                "loxone_inputs": {"power_name": "P_EV"},
                "charging_schedule": {
                    "loxone": {"plugged_in_name": "Plug", "actual_soc_name": "Soc"},
                },
            }
        ]
        with patch.object(lc.config, "get", side_effect=self._plant_get), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ), patch.object(
            lc.config.CONFIG,
            "get_resolved_runtime_settings",
            return_value={},
        ):
            checks = lc.collect_read_checks()

        labels = [label for label, _, _ in checks]
        assert "ev:sens_evcs_active_power" in labels
        assert "ev:sens_evcs_connected" in labels

    def test_house_profile_ehal_bindings_preferred_over_stripped_flex(self):
        """Greenfield: EV bindings on profile; flex bridge often drops ehal_bindings."""
        flex = [
            {
                "id": "ev",
                "loxone_inputs": {},
                "charging_schedule": {"weekday": {}, "weekend": {}},
            }
        ]
        profile = {
            "consumers": [
                {
                    "id": "ev",
                    "type": "ev",
                    "ehal_bindings": {
                        "sens_evcs_active_power": "Ernie_EAuto_P_act",
                        "sens_evcs_connected": "Ernie_EAuto_Da",
                        "get_evcs_ready_by_time": "Ernie_EAuto_FertigUm",
                    },
                }
            ]
        }
        with patch.object(lc.config, "get", side_effect=self._plant_get), patch.object(
            lc.config, "get_flexible_consumers", return_value=flex
        ), patch.object(
            lc.config.CONFIG,
            "get_resolved_runtime_settings",
            return_value={"_house_profile": profile},
        ):
            checks = lc.collect_read_checks()

        by_label = {label: io for label, io, _ in checks}
        assert by_label["ev:sens_evcs_active_power"] == "Ernie_EAuto_P_act"
        assert by_label["ev:sens_evcs_connected"] == "Ernie_EAuto_Da"
        assert by_label["ev:get_evcs_ready_by_time"] == "Ernie_EAuto_FertigUm"


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
            lc,
            "run_read_checks",
            return_value=[lc.LoxoneCheck("Test", "IO", False, "fehlgeschlagen")],
        ):
            ok, results = lc.verify_loxone_setup()
        assert ok is False
        assert len(results) == 1
