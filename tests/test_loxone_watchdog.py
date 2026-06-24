"""Tests für Loxone-Watchdog: Soll-Ist-Vergleich und Korrektur."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from integrations import loxone_watchdog as wd


class TestExpectedSnapshotFromRunState:
    def test_uses_stored_loxone_sent_when_present(self):
        state = {
            "success": True,
            "loxone_sent": {"Ernie_Ziel_SoC": 75.0, "Ernie_Steuerbefehl": 0.0},
        }
        snapshot = wd.expected_loxone_snapshot_from_run_state(state)
        assert snapshot == {"Ernie_Ziel_SoC": 75.0, "Ernie_Steuerbefehl": 0.0}

    def test_returns_none_without_success(self):
        assert wd.expected_loxone_snapshot_from_run_state({"success": False}) is None

    def test_rebuilds_from_mode_when_loxone_sent_missing(self):
        state = {
            "success": True,
            "mode": 1,
            "target_power_kw": 2.0,
            "target_soc_percent": 60.0,
            "consumer_powers_kw": {},
        }
        with patch.object(
            wd.loxone_client,
            "build_sent_loxone_snapshot",
            return_value={"SoC": 60.0},
        ) as mock_build:
            snapshot = wd.expected_loxone_snapshot_from_run_state(state)

        assert snapshot == {"SoC": 60.0}
        mock_build.assert_called_once_with(1, 2.0, 60.0, {}, None)


class TestVerifyAndRestore:
    def test_no_mismatch_when_within_tolerance(self):
        expected = {"Ernie_Ziel_LadeLeistung": 2.0}
        with patch.object(
            wd.loxone_client, "fetch_loxone_generic_value", return_value=2.02
        ), patch.object(wd.config, "get_flexible_consumers", return_value=[]), patch.object(
            wd.config, "get", return_value=""
        ), patch.object(wd.loxone_client, "send_loxone_value") as mock_send:
            mismatches = wd.verify_and_restore_loxone_states(expected)

        assert mismatches == []
        mock_send.assert_not_called()

    def test_corrects_soc_outside_tolerance(self):
        expected = {"Ernie_Ziel_SoC": 80.0}
        with patch.object(
            wd.loxone_client, "fetch_loxone_generic_value", return_value=79.0
        ), patch.object(wd.config, "get_flexible_consumers", return_value=[]), patch.object(
            wd.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
                "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
            }.get(name, "")
        ), patch.object(wd.loxone_client, "send_loxone_value", return_value=True) as mock_send:
            mismatches = wd.verify_and_restore_loxone_states(expected)

        assert len(mismatches) == 1
        assert mismatches[0].expected == 80.0
        assert mismatches[0].actual == 79.0
        assert mismatches[0].corrected is True
        mock_send.assert_called_once_with("Ernie_Ziel_SoC", 80.0)

    def test_read_failure_is_reported_without_send(self):
        expected = {"Ernie_Steuerbefehl": 1.0}
        with patch.object(
            wd.loxone_client, "fetch_loxone_generic_value", return_value=None
        ), patch.object(wd.config, "get_flexible_consumers", return_value=[]), patch.object(
            wd.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
            }.get(name, "")
        ), patch.object(wd.loxone_client, "send_loxone_value") as mock_send:
            mismatches = wd.verify_and_restore_loxone_states(expected)

        assert len(mismatches) == 1
        assert mismatches[0].read_failed is True
        assert mismatches[0].corrected is False
        mock_send.assert_not_called()
