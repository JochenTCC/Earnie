"""Tests für Loxone-Kommunikation: Parsing, HTTP-Abruf/-Senden, Steuerwerte."""
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import MagicMock, patch

import pytest
import requests

os.environ.setdefault("EARNIE_OFFLINE", "1")

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
            result = lc.fetch_loxone_raw_value("Earnie_SOC")

        assert result == "3.5 kW"
        mock_get.assert_called_once()
        assert mock_get.call_args.kwargs["auth"].username == "user"
        assert "jdev/sps/io/Earnie_SOC" in mock_get.call_args.args[0]

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


def _alarm_clock_all_payload(*, tna="Morgen, 11:00", special10=555135300.0):
    ll = {
        "Code": "200",
        "control": "dev/sps/io/Ladewecker/all",
        "value": "0",
        "output7": {"name": "Tna", "nr": 8, "value": tna},
    }
    if special10 is not None:
        ll["SpecialState10"] = {
            "uuid": "20e3f09d-02a2-e285-ffff912d5ec91829",
            "nr": 11,
            "value": special10,
        }
    return {"LL": ll}


class TestFetchLoxoneAlarmClockTna:
    def test_extracts_tna_from_all(self):
        response = _mock_http_response(json_data=_alarm_clock_all_payload())
        with patch.object(lc.requests, "get", return_value=response) as mock_get, patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "192.168.1.1",
                "LOXONE_USER": "user",
                "LOXONE_PASS": "pass",
            }.get(name, kw.get("default", 5)),
        ):
            assert lc.fetch_loxone_alarm_clock_tna("Ladewecker") == "Morgen, 11:00"
        assert "/jdev/sps/io/Ladewecker/all" in mock_get.call_args.args[0]

    def test_missing_tna_returns_none(self):
        response = _mock_http_response(
            json_data={"LL": {"Code": "200", "value": "0", "output0": {"name": "A", "value": 0}}}
        )
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", return_value="x"
        ):
            assert lc.fetch_loxone_alarm_clock_tna("Ladewecker") is None


class TestFetchLoxoneReadyByTime:
    def test_prefers_special_state10_unix(self):
        response = _mock_http_response(json_data=_alarm_clock_all_payload())
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "192.168.1.1",
                "LOXONE_USER": "user",
                "LOXONE_PASS": "pass",
            }.get(name, kw.get("default", 5)),
        ), patch.object(lc, "fetch_loxone_raw_value") as raw:
            got = lc.fetch_loxone_ready_by_time("Ladewecker")
        assert got == pytest.approx(555135300.0 + lc.LOXONE_EPOCH_TO_UNIX)
        raw.assert_not_called()

    def test_falls_back_to_tna_when_special10_missing(self):
        response = _mock_http_response(
            json_data=_alarm_clock_all_payload(special10=None)
        )
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", return_value="x"
        ), patch.object(lc, "fetch_loxone_raw_value") as raw:
            assert lc.fetch_loxone_ready_by_time("Ladewecker") == "Morgen, 11:00"
        raw.assert_not_called()

    def test_falls_back_to_tna_when_special10_zero(self):
        response = _mock_http_response(
            json_data=_alarm_clock_all_payload(special10=0.0)
        )
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", return_value="x"
        ):
            assert lc.fetch_loxone_ready_by_time("Ladewecker") == "Morgen, 11:00"

    def test_falls_back_to_raw_merker(self):
        with patch.object(lc, "_fetch_loxone_io_all", return_value=None), patch.object(
            lc, "fetch_loxone_raw_value", return_value="Heute, 08:00"
        ):
            assert lc.fetch_loxone_ready_by_time("Legacy_FertigUm") == "Heute, 08:00"

    def test_falls_back_to_raw_converts_loxone_counter(self):
        with patch.object(lc, "_fetch_loxone_io_all", return_value=None), patch.object(
            lc, "fetch_loxone_raw_value", return_value="555135300"
        ):
            got = lc.fetch_loxone_ready_by_time("Legacy_Counter")
        assert got == pytest.approx(555135300.0 + lc.LOXONE_EPOCH_TO_UNIX)


class TestFormatReadyByDisplay:
    def test_converts_loxone_counter_to_human_unix(self):
        text = lc.format_ready_by_display(555135300.0)
        unix = int(555135300.0 + lc.LOXONE_EPOCH_TO_UNIX)
        assert f"unix {unix}" in text
        assert text.startswith("20")

    def test_keeps_already_unix(self):
        unix = 555135300.0 + lc.LOXONE_EPOCH_TO_UNIX
        text = lc.format_ready_by_display(unix)
        assert f"unix {int(unix)}" in text

    def test_keeps_tna_text(self):
        assert lc.format_ready_by_display("Morgen, 11:00") == "Morgen, 11:00"


class TestFetchLoxoneGenericValue:
    def test_parses_numeric_with_unit(self):
        with patch.object(lc, "fetch_loxone_raw_value", return_value="65.5 %"):
            assert lc.fetch_loxone_generic_value("SOC") == pytest.approx(65.5)

    def test_invalid_numeric_returns_none(self):
        with patch.object(lc, "fetch_loxone_raw_value", return_value="nicht-numerisch"):
            assert lc.fetch_loxone_generic_value("Bad") is None


class TestSendLoxoneValueTraced:
    def test_success_record(self):
        response = _mock_http_response()
        with patch.object(lc.requests, "get", return_value=response), patch.object(
            lc.config, "get", side_effect=lambda name, **kw: {
                "LOXONE_IP": "10.0.0.5",
                "LOXONE_USER": "admin",
                "LOXONE_PASS": "secret",
            }.get(name, kw.get("default", 5))
        ):
            record = lc._send_loxone_value_traced("Earnie_Mode", 2.0)

        assert record.io_name == "Earnie_Mode"
        assert record.value == pytest.approx(2.0)
        assert record.success is True
        assert record.written_at

    def test_failure_record_on_timeout(self):
        with patch.object(
            lc.requests, "get", side_effect=requests.exceptions.Timeout()
        ), patch.object(lc.config, "get", return_value=5):
            record = lc._send_loxone_value_traced("Earnie_Mode", 1.0)

        assert record.success is False
        assert record.io_name == "Earnie_Mode"


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
            assert lc.send_loxone_value("Earnie_Mode", 2) is True

        url = mock_get.call_args.args[0]
        assert url == "http://10.0.0.5/dev/sps/io/Earnie_Mode/2"

    def test_timeout_returns_false(self):
        with patch.object(
            lc.requests, "get", side_effect=requests.exceptions.Timeout()
        ), patch.object(lc.config, "get", return_value=5):
            assert lc.send_loxone_value("Earnie_Mode", 1) is False


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


class TestEssSetpointsMapping:
    @pytest.mark.parametrize(
        "mode,target,max_kw,active,charge,discharge,cmd",
        [
            (0, 2.0, 5.0, None, 5.0, 5.0, 0),
            (1, 2.5, 5.0, -2.5, 5.0, 0.0, 1),
            (2, 1.0, 5.0, None, 5.0, 0.0, 1),
            (3, 1.8, 5.0, 1.8, 0.0, 5.0, 2),
        ],
    )
    def test_map_ess_setpoints(self, mode, target, max_kw, active, charge, discharge, cmd):
        assert lc.map_ess_setpoints(mode, target, max_kw) == (
            active,
            charge,
            discharge,
            cmd,
        )


class TestFlexibleConsumerHelpers:
    def _consumer(self, *, signal_type: str = "power") -> dict:
        return {
            "id": "swimspa",
            "name": "SwimSpa",
            "nominal_power_kw": 2.8,
            "ehal_bindings": {
                "flex.swimspa.set_enable": "Earnie_SwimSpa_Freigabe",
                "flex.swimspa.sens_power_act": "Earnie_Swim-Spa-P_act",
            },
            "loxone_inputs": {"signal_type": signal_type},
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

    def _ev_consumer(self) -> dict:
        return {
            "id": "eauto",
            "name": "E-Auto",
            "nominal_power_kw": 3.5,
            "min_power_kw": 1.4,
            "ehal_bindings": {
                "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                "set_evcs_mode": "Earnie_EAuto_Modus",
            },
        }

    def test_flex_consumer_setpoint_skipped_on_immediate_charge(self):
        """Sofort laden schreibt nur den Modus Merker (now=2), keinen pv_follow."""
        consumer = self._ev_consumer()
        ctx = {"eauto": {"skip_loxone_output": True}}
        assert lc._flexible_consumer_output_values(consumer, {"eauto": 3.5}, ctx) == {
            "Earnie_EAuto_Modus": 2.0,
        }

    def test_flex_consumer_setpoint_clamped(self):
        consumer = self._ev_consumer()
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 2.1}, {}, {"eauto": 0}) == 2.1
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 2.1}, {}, {"eauto": 1}) == 3.5
        assert lc.flex_consumer_power_setpoint_kw(consumer, {"eauto": 0.0}, {}, {"eauto": 1}) == 0.0

    def test_no_pv_follow_write_helper(self):
        assert not hasattr(lc, "flex_consumer_pv_follow_value")

    def test_resolve_live_power_binary_signal(self):
        consumer = self._consumer(signal_type="binary")
        with patch.object(lc, "fetch_loxone_generic_value", return_value=1.0):
            assert lc.resolve_consumer_live_power_kw(consumer) == 2.8
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.0):
            assert lc.resolve_consumer_live_power_kw(consumer) == 0.0

    def test_resolve_live_power_reads_pattern_b_binding(self):
        """EHAL-only consumers resolve the power Merker from ``flex.{id}.sens_power_act``."""
        consumer = {
            "id": "waschmaschine",
            "name": "Waschmaschine",
            "nominal_power_kw": 2.0,
            "signal_type": "power",
            "ehal_bindings": {
                "flex.waschmaschine.sens_power_act": "Zaehler Waschmaschine"
            },
            "loxone_inputs": {},
        }
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.85) as fetch:
            assert lc.resolve_consumer_live_power_kw(consumer) == 0.85
            fetch.assert_called_with("Zaehler Waschmaschine")
        live = None
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.85):
            live = lc.resolve_flexible_consumers_live_power(consumers=[consumer])
        assert live.measured_ids == frozenset({"waschmaschine"})
        assert live.chart_kw["waschmaschine"] == 0.85
        assert live.kw["waschmaschine"] == 0.85

    def test_default_live_power_includes_house_profile_known_meter(self, monkeypatch):
        """Known house-profile loads with Merker must enter live flex/Sankey."""
        known = {
            "id": "tv",
            "label": "TV",
            "type": "generic",
            "earnie_role": "known",
            "ehal_bindings": {"flex.tv.sens_power_act": "Zaehler TV"},
        }
        monkeypatch.setattr(
            lc.config,
            "get_flexible_consumers",
            lambda optimizer_only=False: [],
        )
        monkeypatch.setattr(
            lc,
            "_house_profile_power_consumers",
            lambda: [known],
        )
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.14):
            live = lc.resolve_flexible_consumers_live_power()
        assert "tv" in live.measured_ids
        assert live.kw["tv"] == 0.14
        assert live.chart_kw["tv"] == 0.14

    def test_generic_with_zaehler_binding_keeps_analog_kw(self):
        """Manual generic + Zähler must not collapse analog kW via binary 0.5 threshold."""
        from house_config.planning_flex_bridge import planning_consumer_to_milp

        house = {
            "id": "geschirrspueler",
            "label": "Geschirrspüler",
            "type": "generic",
            "earnie_role": "manual",
            "nominal_power_kw": 0.35,
            "schedule": {
                "runs_per_week": 6,
                "duration_h": 2.5,
                "start_hour": 12,
                "start_shift_h": 8.0,
            },
            "ehal_bindings": {
                "flex.geschirrspueler.sens_power_act": "Zähler Geschirrspüler"
            },
        }
        milp = planning_consumer_to_milp(house)
        assert milp["signal_type"] == "power"
        with patch.object(lc, "fetch_loxone_generic_value", return_value=0.06):
            live = lc.resolve_flexible_consumers_live_power(consumers=[milp])
        assert live.kw["geschirrspueler"] == 0.06
        assert live.chart_kw["geschirrspueler"] == 0.06


class TestSharedMeterSubtraction:
    """Fall B: SwimSpa-Heizungszähler misst Heizung + Filter am selben Zähler."""

    def _consumers(self) -> list[dict]:
        return [
            {
                "id": "swimspa",
                "name": "SwimSpa",
                "nominal_power_kw": 2.8,
                "signal_type": "power",
                "ehal_bindings": {
                    "flex.swimspa.sens_power_act": "Earnie_Swim-Spa-P_act",
                },
                "loxone_inputs": {
                    "subtract_consumer_ids": ["pool_filter"],
                },
            },
            {
                "id": "pool_filter",
                "name": "SwimSpa Filter",
                "nominal_power_kw": 0.18,
                "signal_type": "binary",
                "ehal_bindings": {
                    "flex.pool_filter.sens_power_act": "homie_bwa_spa_filter2",
                    "sens_filter_active": "homie_bwa_spa_filter1",
                },
                "loxone_inputs": {
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
            {"Earnie_Swim-Spa-P_act": 2.98, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["pool_filter"] == 0.18
        assert result["swimspa"] == 2.8
        assert round(result["swimspa"] + result["pool_filter"], 3) == 2.98

    def test_filter_active_alone_assigns_chart_without_sens_power_act(self):
        """Dump 20260808_232225: only sens_filter_active bound — still chart-Ist."""
        consumers = [
            {
                "id": "pool_swimspa",
                "name": "Pool / SwimSpa",
                "nominal_power_kw": 2.8,
                "signal_type": "power",
                "ehal_bindings": {
                    "flex.pool_swimspa.sens_power_act": "Zaehler Swimspa",
                },
                "loxone_inputs": {
                    "subtract_consumer_ids": ["pool_filter"],
                },
            },
            {
                "id": "pool_filter",
                "name": "Pool-Filter",
                "nominal_power_kw": 0.18,
                "signal_type": "binary",
                "ehal_bindings": {
                    "sens_filter_active": "Earnie_Pool_Filter_aktiv",
                    "flex.pool_filter.set_enable": "Earnie_Pool_Filter_Freigabe",
                },
            },
        ]
        reads = self._reads(
            {"Zaehler Swimspa": 0.18, "Earnie_Pool_Filter_aktiv": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            live = lc.resolve_flexible_consumers_live_power(
                fallbacks={"pool_filter": 0.18},
                consumers=consumers,
            )
        assert live.kw["pool_filter"] == 0.18
        assert live.chart_kw["pool_filter"] == 0.18
        assert "pool_filter" in live.measured_ids
        assert live.kw["pool_swimspa"] == 0.0

    def test_native_filter1_when_filter2_off(self):
        """Autonomer Filter: filter1=1, filter2=0, Gesamtzähler nur Filterlast."""
        reads = self._reads(
            {
                "Earnie_Swim-Spa-P_act": 0.18,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 1.0,
            }
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["pool_filter"] == 0.18
        assert result["swimspa"] == 0.0

    def test_native_filter_inferred_when_binary_silent_in_native_window(self):
        """Prod-Dump 2026-07-07 10:15: Merker 0, Gesamtzähler nur Filterlast."""
        reads = self._reads(
            {
                "Earnie_Swim-Spa-P_act": 0.18,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 0.0,
            }
        )
        filter_contexts = {
            "pool_filter": {
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
        assert live.kw["pool_filter"] == 0.18
        assert live.kw["swimspa"] == 0.0
        assert live.chart_kw["pool_filter"] == 0.18
        assert live.chart_kw["swimspa"] == 0.0

    def test_native_filter_inferred_at_sub_nominal_meter_reading(self):
        """Prod-Dump 2026-07-09 12:05: Gesamtzähler ~0,15 kW, Toleranz ±0,05."""
        reads = self._reads(
            {
                "Earnie_Swim-Spa-P_act": 0.15,
                "homie_bwa_spa_filter2": 0.0,
                "homie_bwa_spa_filter1": 0.0,
            }
        )
        filter_contexts = {
            "pool_filter": {
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
        assert live.kw["pool_filter"] == 0.18
        assert live.kw["swimspa"] == 0.0

    def test_chart_kw_omits_milp_fallback_when_meter_missing(self):
        reads = self._reads(
            {"Earnie_Swim-Spa-P_act": None, "homie_bwa_spa_filter2": 0.0}
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
            {"Earnie_Swim-Spa-P_act": 2.8, "homie_bwa_spa_filter2": 0.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["pool_filter"] == 0.0
        assert result["swimspa"] == 2.8

    def test_no_subtraction_when_heating_uses_fallback(self):
        """Zähler antwortet nicht → Fallback (Heizungs-Soll, bereits filterfrei), kein Abzug."""
        reads = self._reads(
            {"Earnie_Swim-Spa-P_act": None, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(
                fallbacks={"swimspa": 2.8}, consumers=self._consumers()
            )
        assert result["swimspa"] == 2.8
        assert result["pool_filter"] == 0.18

    def test_deduction_clamped_to_zero(self):
        reads = self._reads(
            {"Earnie_Swim-Spa-P_act": 0.1, "homie_bwa_spa_filter2": 1.0}
        )
        with patch.object(lc, "fetch_loxone_generic_value", side_effect=reads):
            result = lc.fetch_flexible_consumers_live_kw(consumers=self._consumers())
        assert result["swimspa"] == 0.0

    def test_resolve_nominal_current_binding_as_amperes(self):
        consumer = {
            "id": "eauto",
            "nominal_power_kw": 3.5,
            "ehal_bindings": {"get_evcs_nominal_current": "Ladestrom Max"},
            "charging_schedule": {
                "nominal_power_voltage_v": 230.0,
                "nominal_power_phases": 3,
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="16"):
            live = lc.resolve_consumer_nominal_power_kw(consumer)
        assert live == pytest.approx(11.04)

    def test_resolve_nominal_current_binding_with_unit_suffix(self):
        consumer = {
            "id": "eauto",
            "nominal_power_kw": 3.5,
            "ehal_bindings": {"get_evcs_nominal_current": "Ladestrom Max"},
            "charging_schedule": {
                "nominal_power_voltage_v": 230.0,
                "nominal_power_phases": 3,
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="16 A"):
            live = lc.resolve_consumer_nominal_power_kw(consumer)
        assert live == pytest.approx(11.04)

    def test_resolve_nominal_power_ignores_legacy_charging_nest(self):
        """Nest-only ``nominal_power_kw_name`` is no longer resolved (Pattern B only)."""
        consumer = {
            "id": "eauto",
            "nominal_power_kw": 3.5,
            "charging_schedule": {
                "loxone": {"nominal_power_kw_name": "Ladestrom Max"},
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="16 A"):
            assert lc.resolve_consumer_nominal_power_kw(consumer) == 3.5

    def test_resolve_nominal_power_fallback_on_missing_io(self):
        consumer = {"id": "x", "nominal_power_kw": 1.6, "ehal_bindings": {}}
        assert lc.resolve_consumer_nominal_power_kw(consumer) == 1.6

    def test_resolve_battery_capacity_from_binding(self):
        consumer = {
            "id": "eauto",
            "ehal_bindings": {"sens_evcs_bat_capacity": "Batteriekapazität_E-Auto"},
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="77 kWh"):
            assert lc.resolve_consumer_battery_capacity_kwh(consumer) == pytest.approx(77.0)

    def test_resolve_battery_capacity_ignores_legacy_charging_nest(self):
        consumer = {
            "id": "eauto",
            "charging_schedule": {
                "loxone": {"battery_capacity_kwh_name": "Batteriekapazität_E-Auto"},
            },
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value="77 kWh"):
            assert lc.resolve_consumer_battery_capacity_kwh(consumer) is None

    def test_resolve_battery_capacity_fails_without_loxone_value(self):
        consumer = {
            "id": "eauto",
            "ehal_bindings": {"sens_evcs_bat_capacity": "Batteriekapazität_E-Auto"},
        }
        with patch.object(lc, "fetch_loxone_raw_value", return_value=None):
            assert lc.resolve_consumer_battery_capacity_kwh(consumer) is None

    def test_resolve_battery_capacity_fails_without_io_name(self):
        consumer = {"id": "eauto", "ehal_bindings": {}}
        assert lc.resolve_consumer_battery_capacity_kwh(consumer) is None


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
                "ehal_bindings": {
                    "flex.swimspa.set_enable": "Earnie_SwimSpa_Freigabe",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_ACTIVE_POWER_NAME": "Earnie_Batterie_Sollleistung",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
        }

        with patch.object(lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)), patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ), patch.object(
            lc.config, "get_flexible_consumers", return_value=consumers
        ):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=1,
                target_power_kw=2.0,
                target_soc=80.0,
                consumer_powers={"swimspa": 2.8},
                charging_contexts={},
            )

        assert "Earnie_Ziel_SoC" not in snapshot
        assert snapshot["Earnie_Batterie_Sollleistung"] == -2.0
        assert snapshot["Earnie_Ziel_LadeLeistung"] == 5.0
        assert snapshot["Earnie_Ziel_Entladeleistung"] == 0.0
        assert snapshot["Earnie_Steuerbefehl"] == 1.0
        assert snapshot["Earnie_SwimSpa_Freigabe"] == 1.0

    def test_snapshot_contains_power_setpoint_as_amps(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Ziel_kW",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
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

        # 2.5 kW @ 230 V / 1 ph → A
        assert snapshot["Earnie_EAuto_Ziel_kW"] == pytest.approx(2.5 * 1000.0 / 230.0, abs=1e-3)
        assert "Earnie_EAuto_pv_follow" not in snapshot

    def test_snapshot_pv_follow_sends_pmax_as_amps(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Ziel_kW",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
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

        assert snapshot["Earnie_EAuto_Ziel_kW"] == pytest.approx(3.5 * 1000.0 / 230.0, abs=1e-3)
        assert snapshot["Earnie_EAuto_Modus"] == 1.0

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
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Ziel_kW",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
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

        assert snapshot["Earnie_EAuto_Ziel_kW"] == 0.0
        assert snapshot["Earnie_EAuto_Modus"] == 0.0

    def test_snapshot_set_evcs_mode_off_when_absent_or_standby(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
        }
        cases = (
            {
                "powers": {"eauto": 2.0},
                "pv_follow": {"eauto": 1},
                "ctx": {
                    "eauto": {
                        "active": True,
                        "plugged_in": False,
                        "anticipated": True,
                        "target_kwh": 10.0,
                    }
                },
                "expect_amps": 0.0,
                "expect_mode": 0.0,
            },
            {
                "powers": {"eauto": 2.0},
                "pv_follow": {"eauto": 0},
                "ctx": {
                    "eauto": {
                        "active": False,
                        "plugged_in": True,
                        "target_kwh": 0.0,
                    }
                },
                "expect_amps": 0.0,
                "expect_mode": 0.0,
            },
            {
                "powers": {"eauto": 0.0},
                "pv_follow": {"eauto": 0},
                "ctx": {"eauto": {"active": True, "plugged_in": True}},
                "expect_amps": 0.0,
                "expect_mode": 0.0,
            },
        )
        for case in cases:
            with patch.object(
                lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)
            ), patch.object(lc.config, "get_flexible_consumers", return_value=consumers):
                snapshot = lc.build_sent_loxone_snapshot(
                    mode=0,
                    target_power_kw=0.0,
                    target_soc=80.0,
                    consumer_powers=case["powers"],
                    charging_contexts=case["ctx"],
                    consumer_pv_follow=case["pv_follow"],
                )
            assert snapshot["Earnie_EAuto_Soll_A"] == case["expect_amps"]
            assert snapshot["Earnie_EAuto_Modus"] == case["expect_mode"]
            assert "Earnie_EAuto_pv_follow" not in snapshot

    def test_snapshot_set_evcs_mode_pv_and_now_encoding(self):
        consumers = [
            {
                "id": "eauto",
                "name": "E-Auto",
                "nominal_power_kw": 3.5,
                "min_power_kw": 1.4,
                "optimizer_enabled": True,
                "daily_target_kwh": 10.0,
                "daily_target_source": "config",
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Soll_A",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
        }
        # PV surplus → mode=1
        with patch.object(
            lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)
        ), patch.object(lc.config, "get_flexible_consumers", return_value=consumers):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.0},
                charging_contexts={"eauto": {"active": True, "plugged_in": True}},
                consumer_pv_follow={"eauto": 1},
            )
        assert snapshot["Earnie_EAuto_Modus"] == 1.0
        assert "Earnie_EAuto_pv_follow" not in snapshot

        # Fixed set_evcs_max_current (not PV) → mode=2
        with patch.object(
            lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)
        ), patch.object(lc.config, "get_flexible_consumers", return_value=consumers):
            snapshot = lc.build_sent_loxone_snapshot(
                mode=0,
                target_power_kw=0.0,
                target_soc=80.0,
                consumer_powers={"eauto": 2.0},
                charging_contexts={"eauto": {"active": True, "plugged_in": True}},
                consumer_pv_follow={"eauto": 0},
            )
        assert snapshot["Earnie_EAuto_Soll_A"] > 0.0
        assert snapshot["Earnie_EAuto_Modus"] == 2.0
        assert "Earnie_EAuto_pv_follow" not in snapshot

        # Sofort laden skip → mode=2 (no amp setpoint from Earnie)
        with patch.object(
            lc.config, "get", side_effect=lambda name, **kw: config_map.get(name)
        ), patch.object(lc.config, "get_flexible_consumers", return_value=consumers):
            values = lc._flexible_consumer_output_values(
                consumers[0],
                {"eauto": 3.5},
                {"eauto": {"skip_loxone_output": True}},
            )
        assert values["Earnie_EAuto_Modus"] == 2.0
        assert "Earnie_EAuto_pv_follow" not in values


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
                "ehal_bindings": {
                    "set_evcs_max_current": "Earnie_EAuto_Ziel_kW",
                    "set_evcs_mode": "Earnie_EAuto_Modus",
                },
            }
        ]
        config_map = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Earnie_Ziel_LadeLeistung",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Earnie_Ziel_Entladeleistung",
            "LOXONE_CONTROL_CMD_NAME": "Earnie_Steuerbefehl",
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
        assert snapshot["Earnie_EAuto_Ziel_kW"] == pytest.approx(2.5 * 1000.0 / 230.0, abs=1e-3)
        # Earnie charges via set_evcs_max_current without PV-follow → Modus "now"
        assert snapshot["Earnie_EAuto_Modus"] == 2.0


class TestSendHuaweiAndConsumers:
    def test_send_huawei_modbus_states_returns_c1_records(self):
        names = {
            "LOXONE_TARGET_ACTIVE_POWER_NAME": "Active",
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Charge",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Discharge",
            "LOXONE_CONTROL_CMD_NAME": "Cmd",
        }
        fake_record = lc.LoxoneWriteRecord(
            io_name="x", value=1.0, success=True, written_at="2026-07-14T10:00:00"
        )
        with patch.object(lc.config, "get", side_effect=lambda name, **kw: names.get(name)), patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ), patch.object(
            lc, "_send_loxone_value_traced", return_value=fake_record
        ) as mock_send:
            records = lc.send_huawei_modbus_states(mode=3, target_power_kw=1.5, target_soc=55.0)

        assert len(records) == 4
        assert mock_send.call_count == 4
        mock_send.assert_any_call("Active", 1.5)
        mock_send.assert_any_call("Charge", 0.0)
        mock_send.assert_any_call("Discharge", 5.0)
        mock_send.assert_any_call("Cmd", 2.0)
        called_names = [c.args[0] for c in mock_send.call_args_list]
        assert "SoC" not in called_names

    def test_send_huawei_modbus_states_calls_ess_outputs_only(self):
        names = {
            "LOXONE_TARGET_CHARGE_POWER_NAME": "Charge",
            "LOXONE_TARGET_DISCHARGE_POWER_NAME": "Discharge",
            "LOXONE_CONTROL_CMD_NAME": "Cmd",
        }
        with patch.object(lc.config, "get", side_effect=lambda name, **kw: names.get(name)), patch.object(
            lc.config, "get_battery_params", return_value={"max_power_kw": 5.0}
        ), patch.object(
            lc, "_send_loxone_value_traced", return_value=lc.LoxoneWriteRecord("x", 0.0, True, "t")
        ) as mock_send:
            lc.send_huawei_modbus_states(mode=3, target_power_kw=1.5, target_soc=55.0)

        assert mock_send.call_count == 3
        mock_send.assert_any_call("Charge", 0.0)
        mock_send.assert_any_call("Discharge", 5.0)
        mock_send.assert_any_call("Cmd", 2.0)
        called_names = [c.args[0] for c in mock_send.call_args_list]
        assert "SoC" not in called_names

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
            lc, "_send_loxone_value_traced", return_value=lc.LoxoneWriteRecord("x", 0.0, True, "t")
        ) as mock_send:
            lc.send_flexible_consumer_states({"hidden": 1.0})

        mock_send.assert_not_called()
