"""Tests für Loxone-Kommunikation: Parsing, HTTP-Abruf/-Senden, Steuerwerte."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

import pytest
import requests

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from integrations import loxone_client as lc
from integrations.loxone_client import (
    _parse_loxone_numeric,
    _parse_loxone_value,
)


class TestLoxoneValueParsing:
    @pytest.mark.parametrize(
        "raw,expected_value,expected_unit",
        [
            ("3.5 kW", 3.5, "kw"),
            ("3,5 kW", 3.5, "kw"),
            ("16 A", 16.0, "a"),
            ("16A", 16.0, "a"),
            ("50 %", 50.0, "pct"),
            ("1200 W", 1200.0, "w"),
            ("42", 42.0, None),
            ("  7.2 kWh  ", 7.2, "kwh"),
            ("21.7°", 21.7, "c"),
            ("21,7 °C", 21.7, "c"),
            ("4 h", 4.0, "h"),
        ],
    )
    def test_parse_loxone_value_with_units(self, raw, expected_value, expected_unit):
        value, unit = _parse_loxone_value(raw)
        assert value == pytest.approx(expected_value)
        assert unit == expected_unit

    def test_parse_empty_raises(self):
        with pytest.raises(ValueError, match="leerer Wert"):
            _parse_loxone_value("")

    def test_parse_loxone_numeric_strips_units(self):
        assert _parse_loxone_numeric("65.5 %") == pytest.approx(65.5)


class TestFilterNativeStartHourParsing:
    @pytest.mark.parametrize(
        "raw,expected_hour,expected_fmt",
        [
            ("10", 10.0, "integer"),
            ("10.0", 10.0, "integer"),
            ("10 h", 10.0, "integer"),
            ("10:30", 10.0, "hm"),
            ("00:00", 0.0, "hm"),
            (22, 22.0, "integer"),
        ],
    )
    def test_parse_filter_start_hour(self, raw, expected_hour, expected_fmt):
        hour, fmt = lc.parse_filter_native_start_hour(raw)
        assert hour == pytest.approx(expected_hour)
        assert fmt == expected_fmt

    def test_parse_unknown_returns_none(self):
        hour, fmt = lc.parse_filter_native_start_hour("morgen")
        assert hour is None
        assert fmt == "unknown"


def _mock_http_response(*, json_data: dict | None = None, status_ok: bool = True) -> MagicMock:
    response = MagicMock()
    response.json.return_value = json_data or {}
    if status_ok:
        response.raise_for_status.return_value = None
    else:
        response.raise_for_status.side_effect = requests.HTTPError("HTTP 500")
    return response


class TestFetchLoxoneRawValue:
    def test_success_returns_trimmed_string(self):
        response = _mock_http_response(json_data={"LL": {"value": "  3.5 kW  "}})
        with patch.object(lc.requests, "get", return_value=response) as mock_get, patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "192.168.1.1",
                "LOXONE_USER": "user",
                "LOXONE_PASS": "pass",
            }.get(name, kw.get("default", 5))
        ):
            result = lc.fetch_loxone_raw_value("Ernie_SOC")

        assert result == "3.5 kW"
        mock_get.assert_called_once()
        assert mock_get.call_args.kwargs["auth"].username == "user"
        assert "jdev/sps/io/Ernie_SOC" in mock_get.call_args.args[0]

    def test_empty_io_name_returns_none(self):
        assert lc.fetch_loxone_raw_value("") is None
        assert lc.fetch_loxone_raw_value(None) is None

    def test_missing_value_in_response_returns_none(self):
        response = _mock_http_response(json_data={"LL": {"value": ""}})
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", return_value="x"
        ):
            assert lc.fetch_loxone_raw_value("Missing") is None

    def test_timeout_returns_none(self):
        with patch.object(
            lc.requests, "get", side_effect=requests.exceptions.Timeout()
        ), patch.object(lc.config, "get", return_value=5):
            assert lc.fetch_loxone_raw_value("Timeout_IO") is None

    def test_network_error_returns_none(self):
        with patch.object(
            lc.requests, "get", side_effect=requests.exceptions.ConnectionError("offline")
        ), patch.object(lc.config, "get", return_value=5):
            assert lc.fetch_loxone_raw_value("Net_IO") is None


class TestFetchLoxoneGenericValue:
    def test_parses_numeric_with_unit(self):
        with patch.object(lc, "fetch_loxone_raw_value", return_value="65.5 %"):
            assert lc.fetch_loxone_generic_value("SOC") == pytest.approx(65.5)

    def test_invalid_numeric_returns_none(self):
        with patch.object(lc, "fetch_loxone_raw_value", return_value="nicht-numerisch"):
            assert lc.fetch_loxone_generic_value("Bad") is None


class TestSendLoxoneValue:
    def test_success_returns_true(self):
        response = _mock_http_response()
        with patch.object(lc.requests, "get", return_value=response) as mock_get, patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "10.0.0.5",
                "LOXONE_USER": "admin",
                "LOXONE_PASS": "secret",
            }.get(name, kw.get("default", 5))
        ):
            assert lc.send_loxone_value("Ernie_Mode", 2) is True

        url = mock_get.call_args.args[0]
        assert url == "http://10.0.0.5/dev/sps/io/Ernie_Mode/2"

    def test_timeout_returns_false(self):
        with patch.object(
            lc.requests, "get", side_effect=requests.exceptions.Timeout()
        ), patch.object(lc.config, "get", return_value=5):
            assert lc.send_loxone_value("Ernie_Mode", 1) is False


class TestFetchLoxoneLivePower:
    def test_computes_house_from_components(self):
        with patch.object(
            lc, "fetch_loxone_generic_value", side_effect=[2.5, -1.0, 0.5]
        ), patch.object(lc.config, "get", return_value="io"):
            result = lc.fetch_loxone_live_power()

        assert result == {
            "pv": 2.5,
            "battery": -1.0,
            "grid": 0.5,
            "house": 2.0,
        }

    def test_negative_pv_is_clamped_to_zero(self):
        with patch.object(
            lc, "fetch_loxone_generic_value", side_effect=[-0.3, 1.0, 0.2]
        ), patch.object(lc.config, "get", return_value="io"):
            result = lc.fetch_loxone_live_power()

        assert result["pv"] == 0.0
        assert result["house"] == pytest.approx(1.2)

    def test_returns_none_when_any_value_missing(self):
        with patch.object(
            lc, "fetch_loxone_generic_value", side_effect=[1.0, None, 0.5]
        ), patch.object(lc.config, "get", return_value="io"):
            assert lc.fetch_loxone_live_power() is None


class TestHuaweiModbusMapping:
    @pytest.mark.parametrize(
        "mode,target,charge,discharge,cmd",
        [
            (0, 2.0, 0.0, 0.0, 0),
            (1, 2.5, 2.5, 0.0, 1),
            (2, 1.0, 0.0, 0.0, 1),
            (3, 1.8, 0.0, 1.8, 2),
        ],
    )
    def test_map_huawei_modbus_values(self, mode, target, charge, discharge, cmd):
        assert lc.map_huawei_modbus_values(mode, target) == (charge, discharge, cmd)


class TestFlexibleConsumerHelpers:
    def _consumer(self, *, signal_type: str = "power") -> dict:
        return {
            "id": "swimspa",
            "name": "SwimSpa",
            "nominal_power_kw": 2.8,
            "loxone_outputs": {"enable_name": "Ernie_SwimSpa_Freigabe"},
            "loxone_inputs": {"power_name": "Ernie_Swim-Spa-P_act", "signal_type": signal_type},
        }

    def test_flex_consumer_enable_on_when_power_positive(self):
        consumer = self._consumer()
        enabled = lc.flex_consumer_enable_value(consumer, {"swimspa": 1.2}, {})
        assert enabled == 1

    def test_flex_consumer_enable_off_when_inactive_context(self):
        consumer = self._consumer()
        ctx = {"swimspa": {"active": False}}
        enabled = lc.flex_consumer_enable_value(consumer, {"swimspa": 2.0}, ctx)
        assert enabled == 0

    def test_flex_consumer_setpoint_skipped_on_immediate_charge(self):
        consumer = {
            "id": "eauto",
            "name": "E-Auto",
            "nominal_power_kw": 3.5,
            "min_power_kw": 1.4,
            "loxone_outputs": {
                "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                "pv_follow_name": "Ernie_EAuto_pv_follow",
            },
        }
        ctx = {"eauto": {"skip_loxone_output": True}}
        assert lc._flexible_consumer_output_values(consumer, {"eauto": 3.5}, ctx) == {
            "Ernie_EAuto_pv_follow": 0.0,
        }

    def test_flex_consumer_setpoint_clamped(self):
        consumer = {
            "id": "eauto",
            "name": "E-Auto",
            "nominal_power_kw": 3.5,
            "min_power_kw": 1.4,
            "loxone_outputs": {
                "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                "pv_follow_name": "Ernie_EAuto_pv_follow",
            },
        }
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 2.1}, {}, {"eauto": 0}) == 2.1
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 2.1}, {}, {"eauto": 1}) == 3.5
        assert lc.flex_consumer_pv_follow_value(consumer, {"eauto": 2.1}, {}, {"eauto": 1}) == 1
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 0.0}, {}, {"eauto": 1}) == 0.0
        assert lc.flex_consumer_pv_follow_value(consumer, {"eauto": 0.0}, {}, {"eauto": 1}) == 0

    def test_resolve_live_power_binary_signal(self):
        consumer = self._consumer(signal_type="binary")
        with patch.object(lc, "fetch_loxone_generic_value", return_value=1.0):
            assert lc.resolve_consumer_live_power_kw(consumer) == 2.8
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.0):
            assert lc.resolve_consumer_live_power_kw(consumer) == 0.0


class TestSharedMeterSubtraction:
    """Fall B: SwimSpa-Heizungszähler misst Heizung + Filter am selben Zähler."""

    def _consumers(self) -> list[dict]:
        return [
            {
                "id": "swimspa",
                "name": "SwimSpa",
                "nominal_power_kw": 2.8,
                "signal_type": "power",
                "loxone_inputs": {
                    "power_name": "Ernie_Swim-Spa-P_act",
                    "subtract_consumer_ids": ["swimspa_filter"],
                },
            },
            {
                "id": "swimspa_filter",
                "name": "SwimSpa Filter",
                "nominal_power_kw": 0.18,
                "signal_type": "binary",
                "loxone_inputs": {
                    "power_name": "homie_bwa_spa_filter2",
                    "alternate_binary_power_name": "homie_bwa_spa_filter1",
                    "signal_type": "binary",
                },
            },
        ]

    def _reads(self, mapping: dict[str, float | None]):
        def _fake(io_name: str):
            return mapping.get(io_name)

        return _fake

    def test_filter_running_is_subtracted_from_heating_total(self):
        reads = self._reads(
            {"Ernie_Swim-Spa-P_act": 2.98, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["swimspa_filter"] == 0.18
        assert result["swimspa"] == 2.8
        assert round(result["swimspa"] + result["swimspa_filter"], 3) == 2.98

    def test_native_filter1_when_filter2_off(self):
        """Autonomer Filter: filter1=1, filter2=0, Gesamtzähler nur Filterlast."""
        reads = self._reads(
            {
                "Ernie_Swim-Spa-P_act": 0.18,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 1.0,
            }
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["swimspa_filter"] == 0.18
        assert result["swimspa"] == 0.0

    def test_native_filter_inferred_when_binary_silent_in_native_window(self):
        """Prod-Dump 2026-07-07 10:15: Merker 0, Gesamtzähler nur Filterlast."""
        reads = self._reads(
            {
                "Ernie_Swim-Spa-P_act": 0.18,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 0.0,
            }
        )
        filter_contexts = {
            "swimspa_filter": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            }
        }
        slot = datetime(2026, 7, 7, 10, 15)
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            live = lc.resolve_flexible_consumers_live_power(
                consumers=self._consumers(),
                filter_contexts=filter_contexts,
                slot_datetime=slot,
            )
        assert live.kw["swimspa_filter"] == 0.18
        assert live.kw["swimspa"] == 0.0
        assert live.chart_kw["swimspa_filter"] == 0.18
        assert live.chart_kw["swimspa"] == 0.0

    def test_native_filter_inferred_at_sub_nominal_meter_reading(self):
        """Prod-Dump 2026-07-09 12:05: Gesamtzähler ~0,15 kW, Toleranz ±0,05."""
        reads = self._reads(
            {
                "Ernie_Swim-Spa-P_act": 0.15,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 0.0,
            }
        )
        filter_contexts = {
            "swimspa_filter": {
                "native_start_hour": 10,
                "native_duration_hours": 4.0,
            }
        }
        slot = datetime(2026, 7, 9, 12, 5, tzinfo=ZoneInfo("Europe/Vienna"))
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            live = lc.resolve_flexible_consumers_live_power(
                consumers=self._consumers(),
                filter_contexts=filter_contexts,
                slot_datetime=slot,
            )
        assert live.kw["swimspa_filter"] == 0.18
        assert live.kw["swimspa"] == 0.0

    def test_chart_kw_omits_milp_fallback_when_meter_missing(self):
        reads = self._reads(
            {"Ernie_Swim-Spa-P_act": None, "homie_bwa_spa_filter2": 0.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            live = lc.resolve_flexible_consumers_live_power(
                fallbacks={"swimspa": 2.8},
                consumers=self._consumers(),
            )
        assert live.kw["swimspa"] == 2.8
        assert "swimspa" not in live.chart_kw
        assert "swimspa" not in live.measured_ids

    def test_filter_off_leaves_heating_unchanged(self):
        reads = self._reads(
            {"Ernie_Swim-Spa-P_act": 2.8, "homie_bwa_spa_filter2": 0.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["swimspa_filter"] == 0.0
        assert result["swimspa"] == 2.8

    def test_no_subtraction_when_heating_uses_fallback(self):
        """Zähler antwortet nicht → Fallback (Heizungs-Soll, bereits filterfrei), kein Abzug."""
        reads = self._reads(
            {"Ernie_Swim-Spa-P_act": None, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(
                fallbacks={"swimspa": 2.8}, consumers=self._consumers()
            )
        assert result["swimspa"] == 2.8
        assert result["swimspa_filter"] == 0.18

    def test_deduction_clamped_to_zero(self):
        reads = self._reads(
            {"Ernie_Swim-Spa-P_act": 0.1, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["swimspa"] == 0.0

    def test_resolve_nominal_power_from_ampere(self):
        consumer = {
            "id": "eauto",
            "nominal_power_kw": 3.5,
            "charging_schedule": {
                "loxone": {
                    "nominal_power_kw_name": "Ladestrom Max",
                    "nominal_power_voltage_v": 230.0,
                    "nominal_power_phases": 3,
                }
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="16 A"):
            live = lc.resolve_consumer_nominal_power_kw(consumer)
        assert live == pytest.approx(11.04)

    def test_resolve_nominal_power_fallback_on_missing_io(self):
        consumer = {"id": "x", "nominal_power_kw": 1.6, "charging_schedule": {"loxone": {}}}
        assert lc.resolve_consumer_nominal_power_kw(consumer) == 1.6

    def test_resolve_battery_capacity_from_loxone(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {
                "loxone": {"battery_capacity_kwh_name": "Batteriekapazität_E-Auto"},
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="77 kWh"):
            assert lc.resolve_consumer_battery_capacity_kwh(consumer) == pytest.approx(77.0)

    def test_resolve_battery_capacity_fails_without_loxone_value(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {
                "loxone": {"battery_capacity_kwh_name": "Batteriekapazität_E-Auto"},
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value=None):
            assert lc.resolve_consumer_battery_capacity_kwh(consumer) is None

    def test_resolve_battery_capacity_fails_without_io_name(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {"loxone": {}},
        }
        assert lc.resolve_consumer_battery_capacity_kwh(consumer) is None

    def test_fetch_charge_immediate_remaining_seconds(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {
                "loxone": {"charge_immediate_remaining_name": "Ernie_Restzeit_Sofortladen"},
            },
        }
        with patch.object(lc, "fetch_loxone_generic_value", return_value=5400.0):
            assert lc.fetch_charge_immediate_remaining_seconds(consumer) == pytest.approx(5400.0)

    def test_fetch_charge_immediate_remaining_seconds_invalid(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {
                "loxone": {"charge_immediate_remaining_name": "Ernie_Restzeit_Sofortladen"},
            },
        }
        with patch.object(lc, "fetch_loxone_generic_value", return_value=-1.0):
            assert lc.fetch_charge_immediate_remaining_seconds(consumer) is None


class TestBuildSentSnapshot:
    def test_snapshot_contains_huawei_and_consumer_merker(self):
        consumers = [
            {
                "id": "swimspa",
                "name": "SwimSpa",
                "nominal_power_kw": 2.8,
                "optimizer_enabled": True,
                "daily_target_kwh": 8.0,
                "daily_target_source": "historical",
                "loxone_outputs": {"enable_name": "Ernie_SwimSpa_Freigabe"},
            }
        ]
        config_map = {
            "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Ernie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Ernie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=1,
                target_power_kw=2.0,
                target_soc=80.0,
                consumer_powers={"swimspa": 2.8},
                charging_contexts={},
            )

        assert snapshot["Ernie_Ziel_SoC"] == 80.0
        assert snapshot["Ernie_Ziel_LadeLeistung"] == 2.0
        assert snapshot["Ernie_Ziel_Entladeleistung"] == 0.0
        assert snapshot["Ernie_Steuerbefehl"] == 1.0
        assert snapshot["Ernie_SwimSpa_Freigabe"] == 1.0

    def test_snapshot_contains_power_setpoint(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "loxone_outputs": {
                    "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                    "pv_follow_name": "Ernie_EAuto_pv_follow",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Ernie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Ernie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.5},
                charging_contexts={},
                consumer_pv_follow={"eauto": 0},
            )

        assert snapshot["Ernie_EAuto_Ziel_kW"] == 2.5
        assert snapshot["Ernie_EAuto_pv_follow"] == 0.0

    def test_snapshot_pv_follow_sends_pmax(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "loxone_outputs": {
                    "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                    "pv_follow_name": "Ernie_EAuto_pv_follow",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Ernie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Ernie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.0},
                charging_contexts={},
                consumer_pv_follow={"eauto": 1},
            )

        assert snapshot["Ernie_EAuto_Ziel_kW"] == 3.5
        assert snapshot["Ernie_EAuto_pv_follow"] == 1.0

    def test_snapshot_suppresses_power_when_anticipated_absent(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "loxone_outputs": {
                    "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                    "pv_follow_name": "Ernie_EAuto_pv_follow",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Ernie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Ernie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
        }
        absent_ctx = {
            "eauto": {
                "active": True,
                "plugged_in": False,
                "anticipated": True,
                "target_kwh": 14.222,
            }
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.76},
                charging_contexts=absent_ctx,
                consumer_pv_follow={"eauto": 1},
            )

        assert snapshot["Ernie_EAuto_Ziel_kW"] == 0.0
        assert snapshot["Ernie_EAuto_pv_follow"] == 0.0


    def test_build_snapshot_does_not_send_to_loxone(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "loxone_outputs": {
                    "power_setpoint_name": "Ernie_EAuto_Ziel_kW",
                    "pv_follow_name": "Ernie_EAuto_pv_follow",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_SOC_NAME": "Ernie_Ziel_SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Ernie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Ernie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Ernie_Steuerbefehl",
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ), patch.object(lc, "send_loxone_value") as mock_send:
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.5},
                charging_contexts={},
                consumer_pv_follow={"eauto": 0},
            )

        mock_send.assert_not_called()
        assert snapshot["Ernie_EAuto_Ziel_kW"] == 2.5
        assert snapshot["Ernie_EAuto_pv_follow"] == 0.0


class TestSendHuaweiAndConsumers:
    def test_send_huawei_modbus_states_calls_all_outputs(self):
        names = {
            "LOXONE_TARGET_SOC_NAME": "SoC",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Charge",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Discharge",
            "LOXONE_CONTROL_CMD_NAME": "Cmd",
        }
        with patch.object(lc.config, "get", side_effect=lambda name, **kw: names[name]), patch.object(
            lc, "send_loxone_value", return_value=True
        ) as mock_send:
            lc.send_huawei_modbus_states(mode=3, target_power_kw=1.5, target_soc=55.0)

        assert mock_send.call_count == 4
        mock_send.assert_any_call("SoC", 55.0)
        mock_send.assert_any_call("Charge", 0.0)
        mock_send.assert_any_call("Discharge", 1.5)
        mock_send.assert_any_call("Cmd", 2)

    def test_send_flexible_consumer_states_skips_without_output(self):
        consumers = [
            {
                "id": "hidden",
                "name": "Hidden",
                "nominal_power_kw": 1.0,
                "optimizer_enabled": True,
                "daily_target_kwh": 1.0,
                "daily_target_source": "config",
                "loxone_outputs": {},
            }
        ]
        with patch.object(lc.config, "get_flexible_consumers", return_value=consumers), patch.object(
            lc, "send_loxone_value"
        ) as mock_send:
            lc.send_flexible_consumer_states({"hidden": 1.0})

        mock_send.assert_not_called()


class TestFetchLoxoneCsvFile:
    def test_ftp_download_success(self, tmp_path):
        local_path = str(tmp_path / "live_consumption.csv")

        class FakeFTP:
            def __init__(self, host, timeout):
                self.host = host

            def login(self, user, passwd):
                self.user = user
                self.passwd = passwd

            def cwd(self, path):
                assert path == "log"

            def retrbinary(self, cmd, callback):
                callback(b"timestamp;value\n")

            def quit(self):
                pass

        with patch.object(lc, "FTP", FakeFTP), patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "192.168.0.10",
                "LOXONE_USER": "lox",
                "LOXONE_PASS": "pw",
                "LOXONE_LOG_FILENAME": "Verbrauch.csv",
            }[name]
        ):
            result = lc.fetch_loxone_csv_file(local_path)

        assert result == local_path
        assert (tmp_path / "live_consumption.csv").read_bytes() == b"timestamp;value\n"

    def test_ftp_error_returns_none_and_removes_partial_file(self, tmp_path):
        local_path = str(tmp_path / "partial.csv")
        (tmp_path / "partial.csv").write_text("partial", encoding="utf-8")

        class FailingFTP:
            def __init__(self, host, timeout):
                pass

            def login(self, user, passwd):
                raise OSError("connection refused")

            def quit(self):
                pass

            def close(self):
                pass

        with patch.object(lc, "FTP", FailingFTP), patch.object(
            lc.config, "get", return_value="x"
        ):
            assert lc.fetch_loxone_csv_file(local_path) is None

        assert not os.path.exists(local_path)
