"""House configurator: plant auto-save must not reset the house-profile form.

The plant section (export limit, grid-meter assertions) writes ``house_profiles.json``.
``_sync_profile_session`` re-seeds the profile form whenever the file stamp differs from
the session's, so a plant write of this session whose stamp the session does not record
drops the user's next unsaved edit (bugfix „Plant auto-save resets the house-profile
form“). The profile auto-save records the stamp after its own write; these tests cover
the runs where it does not save (no grid area chosen, run stopped after the plant
section) and the plant write that happens on its own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_house_config.py"
_TIMEOUT_S = 30.0
_SOURCE = "test_home__hc_g0_heat_source_0"
_EXPORT_ENABLED = "house_config_plant_max_export_enabled"


def _house_path() -> Path:
    return Path(os.environ["EARNIE_HOUSE_PROFILES_PATH"])


def _house_doc() -> dict:
    return json.loads(_house_path().read_text(encoding="utf-8"))


def _write_house(**fields) -> None:
    from house_config.profiles_store import clear_house_profiles_doc_cache

    doc = _house_doc()
    doc["profiles"][0].update(fields)
    _house_path().write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    clear_house_profiles_doc_cache()


@pytest.fixture(autouse=True)
def _isolated(_isolated_backtesting_config):
    from house_config.components_store import clear_components_doc_cache
    from tests.conftest import _reinit_config_offline

    # Room for the baseload check, as in test_heating_reference_change_apptest.
    _write_house(annual_kwh=200000.0)
    clear_components_doc_cache()
    _reinit_config_offline()
    yield


def _run(at: AppTest) -> AppTest:
    at.run(timeout=_TIMEOUT_S)
    assert not at.exception
    return at


def _assert_gas_kept(at: AppTest) -> None:
    assert at.selectbox(key=_SOURCE).value == "gas"
    assert [w.value for w in at.warning if "Heizsystem geändert" in w.value]


def _to_gas(at: AppTest) -> AppTest:
    at.selectbox(key=_SOURCE).set_value("gas")
    return _run(at)


def _toggle_export_limit(at: AppTest) -> AppTest:
    at.checkbox(key=_EXPORT_ENABLED).check()
    at = _run(at)
    assert _house_doc()["plant"]["max_export_power_kw"] == 5.0
    return at


def test_heat_source_change_survives_plant_edit() -> None:
    """The profile is saved already, so only the plant section writes the file."""
    at = _toggle_export_limit(_run(AppTest.from_file(str(_SCRIPT))))
    at = _to_gas(at)
    _assert_gas_kept(at)


def test_held_heat_source_change_survives_plant_edit() -> None:
    """A held heating-system change does not save the profile; a plant edit must keep it."""
    at = _to_gas(_run(AppTest.from_file(str(_SCRIPT))))
    _assert_gas_kept(at)
    at = _run(_toggle_export_limit(at))  # the run after the plant write
    _assert_gas_kept(at)


def test_heat_source_change_survives_run_stopped_after_plant_write(monkeypatch) -> None:
    """A rerun request stops the slow first run after the form, before the profile save."""
    import ui.house_config_profile_form as form

    original = form._render_baseload_preview
    calls = {"n": 0}

    def _stopped_on_first_call(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            st.stop()
        return original(*args, **kwargs)

    monkeypatch.setattr(form, "_render_baseload_preview", _stopped_on_first_call)
    at = _run(AppTest.from_file(str(_SCRIPT)))
    at = _to_gas(at)
    _assert_gas_kept(at)


def test_plant_section_does_not_rewrite_an_unchanged_house_file(monkeypatch) -> None:
    import ui.house_config_plant as plant

    _run(AppTest.from_file(str(_SCRIPT)))  # first session saves the plant once
    writes: list[dict] = []
    original = plant.save_house_profiles
    monkeypatch.setattr(
        plant, "save_house_profiles", lambda doc: (writes.append(doc), original(doc))
    )
    _run(AppTest.from_file(str(_SCRIPT)))
    assert writes == []
