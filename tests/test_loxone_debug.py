"""Tests für Loxone-Debug-Hilfsfunktionen und run_state-Schreibtrace."""
from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault("EARNIE_OFFLINE", "1")

from integrations.loxone_comm_trace import LoxoneWriteRecord, serialize_write_records
from integrations.loxone_connectivity import LoxoneCheck
from ui.loxone_debug import (
    _omitted_write_caption,
    build_ehal_write_rows,
    build_intended_write_rows,
    build_read_rows,
    build_telemetry_rows,
    build_write_rows_from_trace,
    mapping_column_label,
    read_check_status_label,
    rows_with_mapping_column_label,
    write_summary_from_rows,
)


def test_serialize_write_records():
    records = [
        LoxoneWriteRecord("Ernie_Mode", 1.0, True, "2026-07-14T10:00:00"),
        LoxoneWriteRecord("Ernie_SoC", 80.0, False, "2026-07-14T10:00:01"),
    ]
    payload = serialize_write_records(records)
    assert payload == [
        {"io_name": "Ernie_Mode", "value": 1.0, "success": True, "written_at": "2026-07-14T10:00:00"},
        {"io_name": "Ernie_SoC", "value": 80.0, "success": False, "written_at": "2026-07-14T10:00:01"},
    ]


def test_build_read_rows_includes_timestamp():
    checks = [
        LoxoneCheck("sens_ess_soc", "Ernie_SOC", True, "Wert=65.0"),
        LoxoneCheck("sens_pv_production_active", "Ernie_PV", False, "Timeout", severity="warning"),
    ]
    rows = build_read_rows(
        checks,
        "2026-07-14T12:00:00",
        expected_fields=["sens_ess_soc", "sens_pv_production_active"],
    )
    assert len(rows) == 2
    assert rows[0]["EHAL-Feld"] == "sens_ess_soc"
    assert rows[0]["Mapping"] == "Ernie_SOC"
    assert rows[0]["Wert"] == "65.0"
    assert rows[0]["Status"] == "OK"
    assert rows[0]["Zuletzt gelesen"] == "2026-07-14T12:00:00"
    assert rows[1]["Status"] == "Warnung"
    assert rows[1]["Wert"] == ""
    assert rows[1]["Detail"] == "Timeout"


def test_build_read_rows_formats_ready_by_loxone_counter():
    from integrations.loxone_client import LOXONE_EPOCH_TO_UNIX, format_ready_by_display

    lox_counter = 555135300.0
    checks = [
        LoxoneCheck(
            "ev:get_evcs_ready_by_time",
            "Ladewecker",
            True,
            f"raw={lox_counter!r}",
        ),
    ]
    rows = build_read_rows(
        checks,
        "t0",
        expected_fields=["ev:get_evcs_ready_by_time"],
    )
    unix = int(lox_counter + LOXONE_EPOCH_TO_UNIX)
    assert rows[0]["Wert"] == format_ready_by_display(lox_counter)
    assert f"unix {unix}" in rows[0]["Wert"]
    assert rows[0]["Wert"].count("-") >= 2


def test_build_read_rows_ready_by_keeps_tna_text():
    checks = [
        LoxoneCheck(
            "ev:get_evcs_ready_by_time",
            "Ladewecker",
            True,
            "Wert=Morgen, 11:00",
        ),
    ]
    rows = build_read_rows(
        checks,
        "t0",
        expected_fields=["ev:get_evcs_ready_by_time"],
    )
    assert rows[0]["Wert"] == "Morgen, 11:00"


def test_build_read_rows_includes_flex_power():
    checks = [
        LoxoneCheck("wp:flex.wp.sens_power_act", "Ernie_WP", True, "Wert=1.2"),
    ]
    rows = build_read_rows(checks, "t0", expected_fields=["wp:flex.wp.sens_power_act"])
    assert len(rows) == 1
    assert rows[0]["EHAL-Feld"] == "wp:flex.wp.sens_power_act"
    assert rows[0]["Mapping"] == "Ernie_WP"


def test_build_read_rows_unmapped_expected_empty_mapping():
    rows = build_read_rows(
        [],
        "t0",
        expected_fields=["sens_ess_soc", "car:sens_evcs_active_power"],
    )
    assert len(rows) == 2
    assert rows[0]["Mapping"] == ""
    assert rows[0]["Status"] == "Kein Mapping"
    assert rows[1]["EHAL-Feld"] == "car:sens_evcs_active_power"
    assert rows[1]["Mapping"] == ""


def test_read_check_status_label():
    assert read_check_status_label(LoxoneCheck("x", "io", True, "ok")) == "OK"
    assert read_check_status_label(LoxoneCheck("x", "io", False, "bad", severity="warning")) == "Warnung"
    assert read_check_status_label(LoxoneCheck("x", "io", False, "bad")) == "Fehler"


def test_build_write_rows_from_trace_maps_set_fields():
    with patch(
        "ui.loxone_debug.build_loxone_setpoint_io_index",
        return_value={"Ernie_Charge": "set_ess_charge_power_limit"},
    ), patch(
        "ui.loxone_debug.loxone_write_field_to_io",
        return_value={"set_ess_charge_power_limit": "Ernie_Charge"},
    ):
        rows = build_write_rows_from_trace(
            [
                {
                    "io_name": "Ernie_Charge",
                    "value": 1.5,
                    "success": True,
                    "written_at": "2026-07-14T10:00:00",
                },
                {
                    "io_name": "Other_Marker",
                    "value": 0.0,
                    "success": True,
                    "written_at": "2026-07-14T10:00:01",
                },
            ],
            expected_fields=["set_ess_charge_power_limit"],
        )
    assert len(rows) == 1
    assert rows[0]["EHAL-Feld"] == "set_ess_charge_power_limit"
    assert rows[0]["Mapping"] == "Ernie_Charge"
    assert rows[0]["Erfolg"] == "Ja"
    assert rows[0]["Wert"] == "1.5"


def test_build_write_rows_includes_unmapped_expected():
    with patch("ui.loxone_debug.build_loxone_setpoint_io_index", return_value={}), patch(
        "ui.loxone_debug.loxone_write_field_to_io", return_value={}
    ):
        rows = build_write_rows_from_trace(
            [],
            expected_fields=["set_ess_charge_power_limit", "set_ess_mode"],
        )
    assert len(rows) == 2
    assert rows[0]["Mapping"] == ""
    assert rows[0]["Wert"] == ""
    assert rows[1]["EHAL-Feld"] == "set_ess_mode"


def test_build_ehal_write_rows_includes_mapping():
    rows = build_ehal_write_rows(
        [
            {
                "field": "set_ess_charge_power_limit",
                "value": 1000,
                "success": True,
                "written_at": "t0",
                "message": "",
            }
        ],
        mapping={"set_ess_charge_power_limit": "number.ess_charge"},
        expected_fields=["set_ess_charge_power_limit"],
    )
    assert rows[0]["EHAL-Feld"] == "set_ess_charge_power_limit"
    assert rows[0]["Mapping"] == "number.ess_charge"


def test_build_intended_write_rows_for_silent_mode():
    with patch(
        "ui.loxone_debug.build_loxone_setpoint_io_index",
        return_value={"Ernie_Mode": "set_ess_mode"},
    ), patch(
        "ui.loxone_debug.loxone_write_field_to_io",
        return_value={"set_ess_mode": "Ernie_Mode"},
    ):
        rows = build_intended_write_rows(
            {"Ernie_Mode": 2.0},
            "2026-07-14T09:00:00",
            expected_fields=["set_ess_mode"],
        )
    assert rows[0]["EHAL-Feld"] == "set_ess_mode"
    assert rows[0]["Mapping"] == "Ernie_Mode"
    assert rows[0]["Meldung"] == "Nicht gesendet (Silent-Modus)"
    assert rows[0]["Wert"] == "2.0"


def test_write_summary_from_rows_matches_table_not_raw_trace():
    rows = [
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
        {"Erfolg": ""},
        {"Erfolg": "Nein"},
    ]
    assert write_summary_from_rows(rows) == "2/3 Schreibvorgänge erfolgreich"
    assert write_summary_from_rows([{"Erfolg": ""}]) == "Keine Schreibvorgänge erfasst."
    assert _omitted_write_caption(8, [
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
        {"Erfolg": "Ja"},
    ]) == (
        "2 weitere Schreibvorgänge (nicht gemappte Legacy-Merker) "
        "sind nicht in der Tabelle."
    )
    assert _omitted_write_caption(6, [{"Erfolg": "Ja"}] * 6) is None


def test_build_telemetry_rows_filters_and_maps():
    rows = build_telemetry_rows(
        {
            "schema_version": 2,
            "ts": "t",
            "adapter_id": "ha",
            "sens_ess_soc": 55.0,
            "sens_grid_power_active": 100,
        },
        "t0",
        mapping={"sens_ess_soc": "sensor.soc", "sens_grid_power_active": "sensor.grid"},
        expected_fields=["sens_ess_soc", "sens_grid_power_active"],
    )
    assert len(rows) == 2
    assert rows[0]["EHAL-Feld"] == "sens_ess_soc"
    assert rows[0]["Mapping"] == "sensor.soc"
    assert "schema_version" not in {r["EHAL-Feld"] for r in rows}


def test_build_telemetry_rows_pads_unmapped_expected():
    rows = build_telemetry_rows(
        {"sens_ess_soc": 10.0},
        "t0",
        mapping={"sens_ess_soc": "sensor.soc"},
        expected_fields=["sens_ess_soc", "sens_grid_power_active"],
    )
    assert len(rows) == 2
    by_field = {r["EHAL-Feld"]: r for r in rows}
    assert by_field["sens_grid_power_active"]["Mapping"] == ""
    assert by_field["sens_grid_power_active"]["Status"] == "Kein Mapping"


def test_mapping_column_label_by_backend():
    with patch("ui.loxone_debug.config.is_ehal_ha_backend", return_value=True), patch(
        "ui.loxone_debug.config.is_ehal_openems_backend", return_value=False
    ):
        assert mapping_column_label() == "Mapping auf Home Assistant"
    with patch("ui.loxone_debug.config.is_ehal_ha_backend", return_value=False), patch(
        "ui.loxone_debug.config.is_ehal_openems_backend", return_value=True
    ):
        assert mapping_column_label() == "Mapping auf OpenEMS"
    with patch("ui.loxone_debug.config.is_ehal_ha_backend", return_value=False), patch(
        "ui.loxone_debug.config.is_ehal_openems_backend", return_value=False
    ):
        assert mapping_column_label() == "Mapping auf Loxone"


def test_rows_with_mapping_column_label_renames_key():
    with patch("ui.loxone_debug.config.is_ehal_ha_backend", return_value=False), patch(
        "ui.loxone_debug.config.is_ehal_openems_backend", return_value=False
    ):
        out = rows_with_mapping_column_label(
            [
                {
                    "EHAL-Feld": "sens_ess_soc",
                    "Mapping": "Ernie_SOC",
                    "Wert": "1",
                    "Status": "OK",
                }
            ]
        )
    assert list(out[0].keys()) == [
        "EHAL-Feld",
        "Mapping auf Loxone",
        "Wert",
        "Status",
    ]
    assert out[0]["Mapping auf Loxone"] == "Ernie_SOC"
