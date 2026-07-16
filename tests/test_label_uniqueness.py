"""Tests for unique Bezeichnung (label) validation."""
from __future__ import annotations

import pytest

from house_config.label_uniqueness import (
    assert_unique_label,
    assert_unique_labels_in_list,
    duplicate_label_message,
    find_conflicting_label,
    find_duplicate_labels,
    label_compare_key,
)


def test_label_compare_key_is_casefold_stripped() -> None:
    assert label_compare_key("  Dach Süd  ") == "dach süd"


def test_find_conflicting_label_ignores_self() -> None:
    items = [
        {"id": "a", "label": "Dach"},
        {"id": "b", "label": "Ost"},
    ]
    assert find_conflicting_label("Dach", items, exclude_id="a") is None
    conflict = find_conflicting_label("dach", items, exclude_id="b")
    assert conflict is not None
    assert conflict["id"] == "a"


def test_find_conflicting_label_skips_empty() -> None:
    items = [{"id": "a", "label": ""}]
    assert find_conflicting_label("", items, exclude_id=None) is None


def test_find_duplicate_labels_within_list() -> None:
    items = [
        {"id": "c1", "label": "Waschmaschine"},
        {"id": "c2", "label": "waschmaschine"},
        {"id": "c3", "label": "Trockner"},
    ]
    assert find_duplicate_labels(items) == ["Waschmaschine"]


def test_assert_unique_label_raises() -> None:
    items = [{"id": "pv1", "label": "Dach Süd"}]
    with pytest.raises(ValueError, match="bereits vergeben"):
        assert_unique_label("Dach süd", items, exclude_id=None)


def test_assert_unique_labels_in_list_raises() -> None:
    items = [
        {"id": "1", "label": "A"},
        {"id": "2", "label": "A"},
    ]
    with pytest.raises(ValueError, match="bereits vergeben"):
        assert_unique_labels_in_list(items)


def test_duplicate_label_message_quotes_label() -> None:
    assert "Dach" in duplicate_label_message("Dach")
    assert "eindeutige" in duplicate_label_message("Dach")
