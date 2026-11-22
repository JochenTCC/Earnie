"""Coverage: S-2 navigation state setters and label-select display refresh (fake ``st``)."""
from __future__ import annotations

import pytest

from ui import history_navigation, label_select


class _FakeSt:
    def __init__(self) -> None:
        self.session_state: dict = {}
        self.reruns = 0

    def rerun(self) -> None:
        self.reruns += 1


@pytest.fixture
def nav_st(monkeypatch) -> _FakeSt:
    fake = _FakeSt()
    monkeypatch.setattr(history_navigation, "st", fake)
    return fake


@pytest.fixture
def label_st(monkeypatch) -> _FakeSt:
    fake = _FakeSt()
    monkeypatch.setattr(label_select, "st", fake)
    return fake


# --- history_navigation -----------------------------------------------------------------


@pytest.mark.parametrize(("raw", "stored"), [(3, 3), (0, 0), (-2, 0), ("4", 4)])
def test_set_s2_cycle_offset_clamps_at_zero(nav_st, raw, stored) -> None:
    history_navigation._set_s2_cycle_offset(raw)
    assert nav_st.session_state[history_navigation.SESSION_S2_CYCLE_OFFSET] == stored


@pytest.mark.parametrize(("raw", "stored"), [(1, 1), (0, 0), (2, 0), (-1, 0), ("1", 1)])
def test_set_s2_segment_index_only_knows_0_and_1(nav_st, raw, stored) -> None:
    history_navigation._set_s2_segment_index(raw)
    assert nav_st.session_state[history_navigation.SESSION_S2_SEGMENT_INDEX] == stored


def test_apply_s2_nav_state_stores_both_and_reruns(nav_st) -> None:
    history_navigation._apply_s2_nav_state(5, 1)
    assert nav_st.session_state == {
        history_navigation.SESSION_S2_CYCLE_OFFSET: 5,
        history_navigation.SESSION_S2_SEGMENT_INDEX: 1,
    }
    assert nav_st.reruns == 1
    assert history_navigation.get_s2_cycle_offset() == 5


# --- label_select.refresh_label_select_display --------------------------------------------


_MAP = {"a": {"label": "Alpha"}, "b": {"label": "Beta neu"}}
_IDS = ["a", "b"]


def _refresh(selected_id, *, new_option=label_select.NEW_OPTION) -> None:
    _displays, id_by_display = label_select.label_select_choices(_MAP, _IDS, new_option=new_option)
    label_select.refresh_label_select_display(
        select_key="sel",
        selected_id=selected_id,
        entity_map=_MAP,
        entity_ids=_IDS,
        id_by_display=id_by_display,
        new_option=new_option,
    )


def test_refresh_keeps_a_current_valid_display(label_st) -> None:
    label_st.session_state["sel"] = "Alpha"
    _refresh("b")  # the id store is not consulted while the widget text is valid
    assert label_st.session_state["sel"] == "Alpha"


def test_refresh_rewrites_stale_text_from_the_selected_id(label_st) -> None:
    label_st.session_state["sel"] = "Beta"  # old Bezeichnung before the rename
    _refresh("b")
    assert label_st.session_state["sel"] == "Beta neu"


def test_refresh_selects_the_new_option(label_st) -> None:
    label_st.session_state["sel"] = "gone"
    _refresh(label_select.NEW_OPTION)
    assert label_st.session_state["sel"] == label_select.NEW_OPTION


def test_refresh_maps_a_pending_entity_id_in_the_widget(label_st) -> None:
    label_st.session_state["sel"] = "a"  # pending select stored the stable id
    _refresh("unknown")
    assert label_st.session_state["sel"] == "Alpha"


def test_refresh_leaves_unknown_state_alone(label_st) -> None:
    label_st.session_state["sel"] = "zzz"
    _refresh("unknown")
    assert label_st.session_state["sel"] == "zzz"
    del label_st.session_state["sel"]
    _refresh(None, new_option=None)
    assert "sel" not in label_st.session_state


def test_refresh_does_not_touch_the_id_store(label_st) -> None:
    label_st.session_state.update({"sel": "Beta", "sel_id": "a"})
    _refresh("b")
    assert label_st.session_state["sel_id"] == "a"
