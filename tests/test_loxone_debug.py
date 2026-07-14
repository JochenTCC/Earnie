"""Tests für Loxone-Debug-Hilfsfunktionen und run_state-Schreibtrace."""
from __future__ import annotations

import os

os.environ.setdefault("ENERGY_OPTIMIZER_OFFLINE", "1")

from integrations.loxone_comm_trace import LoxoneWriteRecord, serialize_write_records
from integrations.loxone_connectivity import LoxoneCheck
from ui.loxone_debug import (
    build_intended_write_rows,
    build_read_rows,
    build_write_rows_from_trace,
    read_check_status_label,
    write_summary_text,
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
        LoxoneCheck("SoC", "Ernie_SOC", True, "Wert=65.0"),
        LoxoneCheck("PV", "Ernie_PV", False, "Timeout", severity="warning"),
    ]
    rows = build_read_rows(checks, "2026-07-14T12:00:00")
    assert len(rows) == 2
    assert rows[0]["Status"] == "OK"
    assert rows[0]["Zuletzt gelesen"] == "2026-07-14T12:00:00"
    assert rows[1]["Status"] == "Warnung"


def test_read_check_status_label():
    assert read_check_status_label(LoxoneCheck("x", "io", True, "ok")) == "OK"
    assert read_check_status_label(LoxoneCheck("x", "io", False, "bad", severity="warning")) == "Warnung"
    assert read_check_status_label(LoxoneCheck("x", "io", False, "bad")) == "Fehler"


def test_build_write_rows_from_trace():
    rows = build_write_rows_from_trace(
        [{"io_name": "A", "value": 1.5, "success": True, "written_at": "2026-07-14T10:00:00"}]
    )
    assert rows[0]["Erfolg"] == "Ja"
    assert rows[0]["Wert"] == "1.5"


def test_build_intended_write_rows_for_silent_mode():
    rows = build_intended_write_rows({"Ernie_Mode": 2.0}, "2026-07-14T09:00:00")
    assert rows[0]["Status"] == "Nicht gesendet (Silent-Modus)"
    assert rows[0]["Sollwert"] == "2.0"


def test_write_summary_text():
    assert write_summary_text([]) == "Keine Schreibvorgänge erfasst."
    assert write_summary_text([{"success": True}, {"success": False}]) == "1/2 Schreibvorgänge erfolgreich"
