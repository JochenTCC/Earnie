"""AppTest: EHAL-Com Live-Lesen telemetry table (HA / OpenEMS) and Live-Schreiben summary.

The network adapter is a stub returning fixed telemetry; backend selection and the HA push
inbox are patched inside the script. No hub is contacted.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

from tests.apptest.helpers import assert_clean

_TIMEOUT = 30


def _telemetry_script() -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    import streamlit as st

    from integrations import ehal_debug_mapping, ehal_live
    from ui import loxone_debug

    backend = st.session_state.get("cov_backend", "openems")
    is_ha = backend == "ha"
    telemetry = {"sens_grid_power_active": 1200.0, "sens_ess_power": -500.0}

    class _Adapter:
        cfg = SimpleNamespace(
            ess_component="ess0",
            evcs_channels=(),
            sign={"sens_grid_power_active": "negate"},
        )

        def read_telemetry(self):
            failure = st.session_state.get("cov_read_raises")
            if failure:
                raise OSError(failure)
            return dict(telemetry)

    def _push_info(sign):
        st.session_state["cov_push_sign"] = dict(sign)
        return (
            {"grid.meter.sens_grid_power_active": ("ok", "2026-07-05T10:00:00", 1200.0)},
            {"grid.meter.sens_grid_power_active": "Vorzeichen gedreht (ehal.ha.sign: negate)"},
        )

    power = st.session_state.get("cov_power")
    with patch.object(ehal_live, "is_ehal_network_backend", return_value=True), patch.object(
        ehal_live, "is_ha_backend", return_value=is_ha
    ), patch.object(ehal_live, "is_openems_backend", return_value=not is_ha), patch.object(
        ehal_live, "get_network_adapter", return_value=_Adapter()
    ), patch.object(ehal_live, "read_live_power_kw", return_value=power), patch.object(
        ehal_debug_mapping,
        "ha_entity_scoped_live_mapping",
        return_value={"sens_grid_power_active": "sensor.grid"},
    ), patch.object(
        ehal_debug_mapping, "expand_ha_telemetry_for_live", side_effect=lambda t, house: dict(t)
    ), patch.object(
        ehal_debug_mapping,
        "expected_live_read_fields",
        return_value=["sens_grid_power_active", "sens_ess_power"],
    ), patch(
        "ui.house_config_io.load_house_profiles", return_value={}
    ), patch.object(loxone_debug, "_ha_push_read_info", side_effect=_push_info):
        loxone_debug.render_live_reads_section()


def _run(**state) -> AppTest:
    at = AppTest.from_function(_telemetry_script, default_timeout=_TIMEOUT)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_clean(at)
    return at


def _table(at: AppTest):
    (frame,) = [df.value for df in at.dataframe]
    return getattr(frame, "data", frame)  # Styler -> DataFrame


def test_openems_telemetry_table_shows_values_and_channels() -> None:
    at = _run(cov_backend="openems")
    assert any(c.value.startswith("EHAL-Telemetrie · Stand") for c in at.caption)
    assert any("Backend **OpenEMS/EHAL**" in c.value for c in at.caption)
    rows = {row["EHAL-Feld"]: row for row in _table(at).to_dict("records")}
    # Mapped via the OpenEMS channel map -> read OK with hub and EHAL value.
    grid = rows["grid.meter.sens_grid_power_active"]
    assert (grid["Status"], grid["Wert"], grid["Wert (EHAL)"]) == ("OK", "1200 W", "1200 W")
    # Derived consumers are mapped but absent in the telemetry.
    assert rows["sens_power_consumers"]["Status"] == "Fehlt"
    # No wallbox channels configured -> optional EVCS power has no mapping.
    assert rows["sens_evcs_active_power"]["Status"] == "Kein Mapping"
    # No live power -> no power caption.
    assert not any(c.value.startswith("Live-Leistung") for c in at.caption)


def test_live_power_caption_when_available() -> None:
    at = _run(
        cov_backend="openems",
        cov_power={"pv": 3.1, "house": 0.9, "battery": -1.0, "grid": 0.2},
    )
    assert "Live-Leistung (kW): PV 3.1 · Haus 0.9 · Batterie -1.0 · Netz 0.2" in [
        c.value for c in at.caption
    ]


def test_ha_telemetry_uses_push_info_with_adapter_sign() -> None:
    at = _run(cov_backend="ha")
    assert any("Backend **HA/EHAL**" in c.value for c in at.caption)
    assert at.session_state["cov_push_sign"] == {"sens_grid_power_active": "negate"}
    rows = {row["EHAL-Feld"]: row for row in _table(at).to_dict("records")}
    grid = rows["grid.meter.sens_grid_power_active"]
    assert grid["Detail"] == "Vorzeichen gedreht (ehal.ha.sign: negate)"
    assert grid["Wert (EHAL)"] == "1200 W"
    # Expected field without an HA binding is still listed.
    assert rows["sens_ess_power"]["Status"] == "Kein Mapping"


def test_telemetry_read_error_is_shown() -> None:
    at = _run(cov_backend="openems", cov_read_raises="connection refused")
    assert "EHAL-Telemetrie fehlgeschlagen: connection refused" in [e.value for e in at.error]
    assert list(at.dataframe) == []


# --- Live-Schreiben summary ---------------------------------------------------------------


def _summary_script() -> None:
    import streamlit as st

    from ui import loxone_debug

    loxone_debug._render_write_summary(
        st.session_state["cov_rows"], st.session_state["cov_raw_count"]
    )


def _summary(rows, raw_count) -> AppTest:
    at = AppTest.from_function(_summary_script, default_timeout=_TIMEOUT)
    at.session_state["cov_rows"] = rows
    at.session_state["cov_raw_count"] = raw_count
    at.run()
    assert_clean(at)
    return at


def test_write_summary_all_ok() -> None:
    at = _summary([{"Erfolg": "Ja"}, {"Erfolg": "Ja"}], 2)
    assert [s.value for s in at.success] == ["2/2 Schreibvorgänge erfolgreich"]
    assert list(at.error) == [] and list(at.caption) == []


def test_write_summary_with_failure_and_omitted_legacy_merker() -> None:
    at = _summary([{"Erfolg": "Ja"}, {"Erfolg": "Nein"}, {"Erfolg": "—"}], 5)
    assert [e.value for e in at.error] == ["1/2 Schreibvorgänge erfolgreich"]
    assert [c.value for c in at.caption] == [
        "3 weitere Schreibvorgänge (nicht gemappte Legacy-Merker) sind nicht in der Tabelle."
    ]
