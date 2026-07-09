"""Tests für ui.scenario_form_helpers."""
from __future__ import annotations

from ui.scenario_form_helpers import (
    NONE_LABEL,
    default_label_index,
    lookup_entity_id,
    options_for_entities,
)


def test_lookup_entity_id_none_returns_empty():
    mapping = {"Label (bat)": "bat"}
    assert lookup_entity_id(mapping, None) == ""


def test_lookup_entity_id_unknown_returns_empty():
    mapping = {"Label (bat)": "bat"}
    assert lookup_entity_id(mapping, "unbekannt") == ""


def test_lookup_entity_id_resolves_label():
    mapping = {"Meine Batterie (bat1)": "bat1"}
    assert lookup_entity_id(mapping, "Meine Batterie (bat1)") == "bat1"


def test_options_empty_without_allow_none():
    labels, mapping = options_for_entities([], allow_none=False)
    assert labels == []
    assert mapping == {}


def test_options_empty_with_allow_none():
    labels, mapping = options_for_entities([], allow_none=True)
    assert labels == [NONE_LABEL]
    assert mapping[NONE_LABEL] == ""


def test_options_builds_labels_and_mapping():
    items = [{"id": "pv1", "label": "Dach"}]
    labels, mapping = options_for_entities(items)
    assert labels == ["Dach (pv1)"]
    assert mapping["Dach (pv1)"] == "pv1"


def test_default_label_index_finds_id():
    options = ["— keine —", "Batterie (bat)"]
    assert default_label_index(options, "bat") == 1


def test_default_label_index_missing_returns_zero():
    options = ["Batterie (bat)"]
    assert default_label_index(options, "missing") == 0
