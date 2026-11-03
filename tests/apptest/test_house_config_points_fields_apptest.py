"""AppTest für die Earnie-Points-Felder im Hausprofil-Verbraucherformular.

``bidirectional`` (nur ev) ist optional und steht abgewählt als false im Ergebnis. Die frühere
„Geräteart“ (``appliance_kind``) gibt es nicht mehr: die Klimaanlage steht im Abschnitt „Kühlung“.
"""
from __future__ import annotations

from streamlit.testing.v1 import AppTest

_TIMEOUT_S = 10.0


def _ev_app():
    import streamlit as st

    from ui.house_config_profile_points import _render_points_fields

    consumer = {"type": "ev", "bidirectional": True}
    st.session_state["points_result"] = _render_points_fields(
        consumer, 0, "ev", session_scope="t"
    )


def _generic_app():
    import streamlit as st

    from ui.house_config_profile_points import _render_points_fields

    consumer = {"type": "generic"}
    st.session_state["points_result"] = _render_points_fields(
        consumer, 0, "generic", session_scope="t"
    )


def _thermal_annual_app():
    import streamlit as st

    from ui.house_config_profile_points import _render_points_fields

    st.session_state["points_result"] = _render_points_fields(
        {"type": "thermal_annual"}, 0, "thermal_annual", session_scope="t"
    )


def test_ev_shows_bidirectional_checkbox_and_returns_bool():
    at = AppTest.from_function(_ev_app).run(timeout=_TIMEOUT_S)
    assert not at.exception
    [box] = at.checkbox
    assert box.label == "Wallbox bidirektional (V2G)"
    assert box.value is True
    assert at.session_state["points_result"] == {"bidirectional": True}
    box.uncheck().run(timeout=_TIMEOUT_S)
    assert at.session_state["points_result"] == {"bidirectional": False}


def test_generic_has_no_appliance_kind_field():
    at = AppTest.from_function(_generic_app).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.selectbox
    assert at.session_state["points_result"] == {}


def test_thermal_annual_has_no_points_fields():
    at = AppTest.from_function(_thermal_annual_app).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert not at.checkbox
    assert not at.selectbox
    assert at.session_state["points_result"] == {}
