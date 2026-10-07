"""Pilot (spike/vo-push-pilot): Push-Inbox table logic and rendering."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runtime_store import loxone_push_inbox as inbox
from ui import loxone_push_inbox_ui as ui

T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EARNIE_RUNTIME_PATH", str(tmp_path))
    monkeypatch.delenv(inbox.REPEAT_ENV, raising=False)
    monkeypatch.delenv("EARNIE_PILOT_PUSH_TOKEN", raising=False)


def _poll(field: str, value: str, mapping: str = "Merker_X") -> dict[str, str]:
    return {"EHAL-Feld": field, "Mapping": mapping, "Wert": value, "Status": "OK"}


def test_rows_derived_states_and_age() -> None:
    inbox.record_push("sens_ess_soc", "55.3", "10.0.0.5", now=T0)
    inbox.record_push("sens_absent_mode", "n/a", "10.0.0.5", now=T0)
    inbox.record_push("sens_grid_power_active", "1.2", "10.0.0.5", now=T0 - timedelta(seconds=200))
    rows = {row["EHAL-ID"]: row for row in ui.build_inbox_rows(inbox.load_inbox(), now=T0 + timedelta(seconds=10))}
    assert rows["sens_ess_soc"]["Status"] == inbox.STATE_OK
    assert rows["sens_ess_soc"]["Wert (abgeleitet)"] == "55.3"
    assert rows["sens_ess_soc"]["Alter (s)"] == "10"
    assert rows["sens_absent_mode"]["Status"] == inbox.STATE_UNREADABLE
    assert rows["sens_absent_mode"]["Roh"] == "n/a"
    # analog, silent for 210 s while another analog signal is fresh -> link alive -> 0 assumed
    assert rows["sens_grid_power_active"]["Status"] == inbox.STATE_ZERO_ASSUMED_SILENT
    assert rows["sens_grid_power_active"]["Wert (abgeleitet)"] == "0"
    assert [row["EHAL-ID"] for row in ui.build_inbox_rows(inbox.load_inbox())] == sorted(rows)


def test_expected_signals_without_push_get_derived_state() -> None:
    inbox.record_push("heartbeat", "1", now=T0)
    ids = ["heartbeat", "evcs.e_auto.sens_evcs_active_power", "sens_absent_mode"]
    rows = {
        r["EHAL-ID"]: r
        for r in ui.build_inbox_rows(inbox.load_inbox(), now=T0 + timedelta(seconds=5), expected_ids=ids)
    }
    assert rows["heartbeat"]["Status"] == inbox.STATE_OK
    assert rows["evcs.e_auto.sens_evcs_active_power"]["Status"] == inbox.STATE_ZERO_ASSUMED_NEVER
    assert rows["evcs.e_auto.sens_evcs_active_power"]["Wert (abgeleitet)"] == "0"
    assert rows["sens_absent_mode"]["Anzahl"] == "0"


def test_expected_signals_without_any_link_are_unknown() -> None:
    rows = ui.build_inbox_rows({}, now=T0, expected_ids=["sens_ess_soc"])
    assert rows[0]["Status"] == inbox.STATE_UNKNOWN
    assert rows[0]["Wert (abgeleitet)"] == ""


def test_derived_zero_is_compared_with_the_poll_value() -> None:
    inbox.record_push("heartbeat", "1", now=T0)
    poll = [_poll("evcs.e_auto.sens_evcs_active_power", "0.0 kW")]
    rows = ui.build_inbox_rows(
        inbox.load_inbox(), poll, now=T0, expected_ids=["evcs.e_auto.sens_evcs_active_power"]
    )
    row = next(r for r in rows if r["EHAL-ID"] == "evcs.e_auto.sens_evcs_active_power")
    assert row["Abweichung"] == "gleich"


def test_compare_with_poll_equal_and_different() -> None:
    inbox.record_push("sens_ess_soc", "55.3", now=T0)
    inbox.record_push("sens_pv_production_active", "4.0", now=T0)
    poll = [_poll("sens_ess_soc", "55.3", "SOC Batterie"), _poll("sens_pv_production_active", "3.5 kW")]
    rows = {row["EHAL-ID"]: row for row in ui.build_inbox_rows(inbox.load_inbox(), poll, now=T0)}
    assert rows["sens_ess_soc"]["Abweichung"] == "gleich"
    assert rows["sens_ess_soc"]["Mapping (Poll)"] == "SOC Batterie"
    assert rows["sens_pv_production_active"]["Poll-Wert"] == "3.5"
    assert rows["sens_pv_production_active"]["Abweichung"] == "Δ +0.500"


def test_poll_row_matching_variants() -> None:
    by_field = {
        "ess.delta.sens_ess_soc": _poll("ess.delta.sens_ess_soc", "61"),
        "waschmaschine:flex.waschmaschine.sens_power_act": _poll(
            "waschmaschine:flex.waschmaschine.sens_power_act", "0.4"
        ),
        "pool_swimspa:sens_temperature_water": _poll("pool_swimspa:sens_temperature_water", "36.0"),
        "garage:sens_evcs_soc_act": _poll("garage:sens_evcs_soc_act", "40"),
        "garage:sens_evcs_active_power": _poll("garage:sens_evcs_active_power", "7.2"),
    }
    match = ui._poll_row_for
    assert match("ess.delta.sens_ess_soc", by_field)["Wert"] == "61"
    assert match("consumer.waschmaschine.sens_power_act", by_field)["Wert"] == "0.4"
    assert match("flex.waschmaschine.sens_power_act", by_field)["Wert"] == "0.4"  # legacy alias
    assert match("pool.pool_swimspa.sens_temperature_water", by_field)["Wert"] == "36.0"
    assert match("ev.garage.sens_evcs_soc_act", by_field)["Wert"] == "40"
    assert match("evcs.garage.sens_evcs_active_power", by_field)["Wert"] == "7.2"
    assert match("heatpump.waermepumpe.sens_temperature_heat_storage", by_field) is None
    assert match("sens_unknown", by_field) is None


def test_no_poll_rows_leaves_comparison_columns_empty() -> None:
    inbox.record_push("sens_ess_soc", "55", now=T0)
    row = ui.build_inbox_rows(inbox.load_inbox(), None, now=T0)[0]
    assert row["Poll-Wert"] == ""
    assert row["Abweichung"] == ""
    assert row["Mapping (Poll)"] == ""


def test_clear_inbox() -> None:
    inbox.record_push("sens_ess_soc", "55", now=T0)
    assert inbox.load_inbox()
    inbox.clear_inbox()
    assert inbox.load_inbox() == {}
    inbox.clear_inbox()  # idempotent


def test_section_renders_disabled_hint_and_empty_inbox() -> None:
    from streamlit.testing.v1 import AppTest

    def _app() -> None:
        from ui import loxone_push_inbox_ui as page

        page.expected_signal_ids = lambda: []  # no real bindings in tests
        page.render_push_inbox_section()

    at = AppTest.from_function(_app).run(timeout=15)
    assert not at.exception
    assert any("deaktiviert" in info.value for info in at.info)
    assert any("Noch keine Pushes" in caption.value for caption in at.caption)


def test_section_renders_table_with_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from streamlit.testing.v1 import AppTest

    monkeypatch.setenv("EARNIE_PILOT_PUSH_TOKEN", "t")
    inbox.record_push("sens_ess_soc", "55.3", "10.0.0.5")

    def _app() -> None:
        from ui import loxone_push_inbox_ui as page

        page._poll_rows = lambda: []  # no Miniserver in tests
        page.expected_signal_ids = lambda: []
        page.render_push_inbox_section()

    at = AppTest.from_function(_app).run(timeout=15)
    assert not at.exception
    assert not at.info
    assert len(at.dataframe) == 1
    assert "sens_ess_soc" in at.dataframe[0].value["EHAL-ID"].tolist()
