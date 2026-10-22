"""EHAL-Com Schreibtest keeps its expander open and its ticked rows across reruns (bench B2).

The expander has no state of its own, so a remount (the page above it changed between two
runs) used to collapse it. Working in it now renders it ``expanded`` from ``session_state``.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

_FIELD = "ess.house.set_ess_charge_power_limit"


def _script() -> None:
    from unittest.mock import patch

    import streamlit as st

    from ui import ehal_write_test as ui

    with patch.object(ui, "writes_allowed", return_value=True), patch.object(
        ui, "allowed_probe_fields", return_value=["ess.house.set_ess_charge_power_limit"]
    ), patch.object(
        ui,
        "mapped_write_targets",
        return_value={"ess.house.set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit"},
    ), patch.object(ui, "default_ev_nominal_a", return_value=None), patch.object(
        ui.config, "get_battery_params", return_value={"max_power_kw": 5.0}
    ):
        st.write("a row above the expander that may come and go")
        ui.render_write_test_section()


def _script_incomplete_scenario() -> None:
    """Like ``_script`` but the live scenario has no battery maximum (HA testbed F20)."""
    from unittest.mock import patch

    from ui import ehal_write_test as ui

    with patch.object(ui, "writes_allowed", return_value=True), patch.object(
        ui, "allowed_probe_fields", return_value=["ess.house.set_ess_charge_power_limit"]
    ), patch.object(
        ui,
        "mapped_write_targets",
        return_value={"ess.house.set_ess_charge_power_limit": "ess.house.set_ess_charge_power_limit"},
    ), patch.object(ui, "default_ev_nominal_a", return_value=None), patch.object(
        ui.config, "get_battery_params", return_value={}
    ):
        ui.render_write_test_section()


def test_incomplete_live_scenario_shows_power_limit_warning() -> None:
    at = AppTest.from_function(_script_incomplete_scenario).run()
    assert not at.exception
    assert any("Keine Batterie-Maximalleistung" in w.value for w in at.warning)


def test_complete_live_scenario_shows_no_power_limit_warning() -> None:
    at = AppTest.from_function(_script).run()
    assert not at.exception
    assert not any("Keine Batterie-Maximalleistung" in w.value for w in at.warning)


def _expanded(at: AppTest) -> bool:
    return bool(at.expander[0].proto.expanded)


def test_expander_starts_collapsed() -> None:
    at = AppTest.from_function(_script).run()
    assert not at.exception
    assert not _expanded(at)


def test_working_in_the_expander_keeps_it_open_on_later_runs() -> None:
    at = AppTest.from_function(_script).run()
    at.checkbox(key=f"ehal_write_test_incl_{_FIELD}").check().run()
    assert _expanded(at)
    at.run()  # a refresh / rerun without interaction
    assert _expanded(at)


def test_ticked_row_survives_reruns() -> None:
    at = AppTest.from_function(_script).run()
    at.checkbox(key=f"ehal_write_test_incl_{_FIELD}").check().run()
    at.run()
    assert at.checkbox(key=f"ehal_write_test_incl_{_FIELD}").value is True
