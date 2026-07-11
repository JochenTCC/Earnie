"""Tests für Loxone-Startup-Prüfung."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from integrations.loxone_connectivity import LoxoneCheck
from scripts import startup_checks as sc


class TestRunLoxoneVerifyOnStartup:
    def test_skipped_when_env_disabled(self, monkeypatch):
        monkeypatch.setenv("ENERGY_OPTIMIZER_SKIP_LOXONE_VERIFY", "1")
        with patch.object(sc, "verify_loxone_setup") as mock_verify:
            sc.run_loxone_verify_on_startup()
        mock_verify.assert_not_called()

    def test_skipped_without_loxone_env(self, monkeypatch):
        monkeypatch.delenv("ENERGY_OPTIMIZER_SKIP_LOXONE_VERIFY", raising=False)
        with (
            patch.object(sc, "loxone_env_configured", return_value=False),
            patch.object(sc, "verify_loxone_setup") as mock_verify,
        ):
            sc.run_loxone_verify_on_startup()
        mock_verify.assert_not_called()

    def test_logs_success(self, monkeypatch):
        monkeypatch.delenv("ENERGY_OPTIMIZER_SKIP_LOXONE_VERIFY", raising=False)
        with (
            patch.object(sc, "loxone_env_configured", return_value=True),
            patch.object(
                sc,
                "verify_loxone_setup",
                return_value=(
                    True,
                    [LoxoneCheck("Test", "IO", True, "ok")],
                ),
            ),
        ):
            sc.run_loxone_verify_on_startup()

    def test_strict_mode_exits_on_failure(self, monkeypatch):
        monkeypatch.setenv("ENERGY_OPTIMIZER_STRICT_LOXONE_VERIFY", "1")
        with (
            patch.object(sc, "loxone_env_configured", return_value=True),
            patch.object(
                sc,
                "verify_loxone_setup",
                return_value=(
                    False,
                    [LoxoneCheck("Test", "IO", False, "fehlgeschlagen")],
                ),
            ),
        ):
            with pytest.raises(SystemExit) as exc:
                sc.run_loxone_verify_on_startup()
        assert exc.value.code == 1

    def test_non_strict_continues_on_failure(self, monkeypatch):
        monkeypatch.delenv("ENERGY_OPTIMIZER_STRICT_LOXONE_VERIFY", raising=False)
        with (
            patch.object(sc, "loxone_env_configured", return_value=True),
            patch.object(
                sc,
                "verify_loxone_setup",
                return_value=(
                    False,
                    [LoxoneCheck("Test", "IO", False, "fehlgeschlagen")],
                ),
            ),
        ):
            sc.run_loxone_verify_on_startup()

    def test_tariff_validate_skipped_when_env_set(self, monkeypatch):
        monkeypatch.setenv("ENERGY_OPTIMIZER_SKIP_TARIFF_VALIDATE", "1")
        with patch.object(sc, "collect_tariff_plausibility_errors") as mock_collect:
            sc.run_tariff_plausibility_on_startup()
        mock_collect.assert_not_called()

    def test_tariff_validate_strict_exits_on_error(self, monkeypatch):
        monkeypatch.setenv("ENERGY_OPTIMIZER_STRICT_TARIFF_VALIDATE", "1")
        with patch.object(
            sc,
            "collect_tariff_plausibility_errors",
            return_value=["tariffs.json ungültig"],
        ):
            with pytest.raises(SystemExit) as exc:
                sc.run_tariff_plausibility_on_startup()
        assert exc.value.code == 1

    def test_warning_severity_does_not_count_as_failed(self, monkeypatch):
        monkeypatch.delenv("ENERGY_OPTIMIZER_STRICT_LOXONE_VERIFY", raising=False)
        with (
            patch.object(sc, "loxone_env_configured", return_value=True),
            patch.object(
                sc,
                "verify_loxone_setup",
                return_value=(
                    True,
                    [
                        LoxoneCheck(
                            "Event-Trigger E-Auto Fertig-Uhrzeit",
                            "Ernie_EAuto_FertigUm",
                            False,
                            "Lesen fehlgeschlagen (kein Wert)",
                            severity="warning",
                        )
                    ],
                ),
            ),
        ):
            sc.run_loxone_verify_on_startup()
