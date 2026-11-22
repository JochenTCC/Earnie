"""Szenarienkonfigurator: overview table (docs/dev/scenario-editor-usability.md § 4).

The rows open a scenario, carry its position and are the only writer of ``enabled``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.apptest.fields import SCENARIO_ID, SCENARIO_RADIO_LABEL
from tests.apptest.helpers import (
    file_snapshot,
    open_scenario,
    open_scenario_label,
    scenario_row_labels,
)

_SCRIPT = Path(__file__).parent / "scripts" / "run_page_scenario_editor.py"
_TIMEOUT_S = 30.0
_FIXED = "fixture_5kwh_fixed"
_FIXED_LABEL = "Fixture 5 kWh fixe Einspeise"


def _path() -> Path:
    return Path(os.environ["EARNIE_BACKTESTING_SCENARIOS_PATH"])


def _doc() -> dict:
    return json.loads(_path().read_text(encoding="utf-8"))


def _by_id() -> dict[str, dict]:
    return {s["id"]: s for s in _doc()["scenarios"]}


def _session() -> AppTest:
    at = AppTest.from_file(str(_SCRIPT)).run(timeout=_TIMEOUT_S)
    assert not at.exception, [e.value for e in at.exception]
    return at


def _without_enabled(scenario: dict) -> dict:
    return {k: v for k, v in scenario.items() if k != "enabled"}


def test_rows_in_file_order_with_live_first_and_locked() -> None:
    at = _session()
    assert scenario_row_labels(at) == ["Live", _FIXED_LABEL, SCENARIO_RADIO_LABEL]
    assert open_scenario_label(at) == "Live"
    live_box = at.checkbox(key="scenario_active__live")
    assert live_box.value is True and live_box.disabled is True
    assert not [w for w in at.selectbox if w.key == "scenario_pos__live"]
    # The form has no activation box any more: the row is the only writer.
    assert not [w for w in at.checkbox if str(w.key).endswith("__scenario_enabled")]


def test_opening_and_switching_writes_nothing() -> None:
    before = file_snapshot(_path())
    at = _session()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    assert open_scenario_label(at) == SCENARIO_RADIO_LABEL
    open_scenario(at, _FIXED_LABEL)
    open_scenario(at, "Live")
    assert not at.exception
    assert file_snapshot(_path()) == before


def test_toggle_other_scenario_changes_only_its_enabled() -> None:
    before = _by_id()
    at = _session()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    at.checkbox(key=f"scenario_active__{_FIXED}").uncheck().run(timeout=_TIMEOUT_S)
    assert not at.exception
    after = _by_id()
    assert after[_FIXED]["enabled"] is False
    assert _without_enabled(after[_FIXED]) == _without_enabled(before[_FIXED])
    assert after[SCENARIO_ID] == before[SCENARIO_ID]
    assert after["live"] == before["live"]
    # The open form stays open, without an unsaved-edit prompt, and does not write back.
    assert open_scenario_label(at) == SCENARIO_RADIO_LABEL
    assert not [w for w in at.warning if "ungespeicherte" in w.value]
    at.run(timeout=_TIMEOUT_S)
    assert _by_id()[_FIXED]["enabled"] is False


def test_toggle_open_scenario_is_not_written_back_by_the_form() -> None:
    at = _session()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    at.checkbox(key=f"scenario_active__{SCENARIO_ID}").uncheck().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _by_id()[SCENARIO_ID]["enabled"] is False
    at.run(timeout=_TIMEOUT_S)
    assert _by_id()[SCENARIO_ID]["enabled"] is False
    assert at.checkbox(key=f"scenario_active__{SCENARIO_ID}").value is False
    assert not [w for w in at.warning if "ungespeicherte" in w.value]
    at.checkbox(key=f"scenario_active__{SCENARIO_ID}").check().run(timeout=_TIMEOUT_S)
    assert _by_id()[SCENARIO_ID]["enabled"] is True


def test_position_select_reorders_and_live_stays_first() -> None:
    at = _session()
    assert at.selectbox(key=f"scenario_pos__{SCENARIO_ID}").value == 3
    at.selectbox(key=f"scenario_pos__{SCENARIO_ID}").set_value(2).run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert [s["id"] for s in _doc()["scenarios"]] == ["live", SCENARIO_ID, _FIXED]
    assert scenario_row_labels(at) == ["Live", SCENARIO_RADIO_LABEL, _FIXED_LABEL]
    assert at.selectbox(key=f"scenario_pos__{SCENARIO_ID}").value == 2


def test_duplicate_copies_the_open_scenario() -> None:
    at = _session()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    at.button(key="scenario_duplicate").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    scenarios = _doc()["scenarios"]
    assert len(scenarios) == 4
    copy = scenarios[-1]
    assert copy["label"] == f"{SCENARIO_RADIO_LABEL} copy"
    assert copy["settings"] == _by_id()[SCENARIO_ID]["settings"]
    assert open_scenario_label(at) == copy["label"]


def test_new_empty_starts_without_settings() -> None:
    at = _session()
    open_scenario(at, SCENARIO_RADIO_LABEL)
    at.button(key="scenario_new_empty").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    created = _doc()["scenarios"][-1]
    # No settings taken from the open scenario (nor from Live).
    assert created == {"id": "mein_szenario", "label": "Mein Szenario", "enabled": True, "settings": {}}
    assert open_scenario_label(at) == "Mein Szenario"
    assert at.selectbox(key="mein_szenario__scenario_profile").value == "— keine —"


def test_delete_asks_first_and_live_has_no_delete() -> None:
    at = _session()
    assert not [b for b in at.button if b.key == "scenario_delete"]  # Live is open
    open_scenario(at, _FIXED_LABEL)
    at.button(key="scenario_delete").click().run(timeout=_TIMEOUT_S)
    assert _FIXED in _by_id()
    at.button(key="scenario_delete_cancel").click().run(timeout=_TIMEOUT_S)
    assert _FIXED in _by_id()
    at.button(key="scenario_delete").click().run(timeout=_TIMEOUT_S)
    at.button(key="scenario_delete_confirm_yes").click().run(timeout=_TIMEOUT_S)
    assert not at.exception
    assert _FIXED not in _by_id()
    assert open_scenario_label(at) == "Live"
