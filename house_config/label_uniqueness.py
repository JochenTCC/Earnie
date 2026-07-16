"""Unique Bezeichnung (label) checks for multi-instance entities."""
from __future__ import annotations

from typing import Any


def normalize_entity_label(label: Any) -> str:
    return str(label or "").strip()


def label_compare_key(label: Any) -> str:
    return normalize_entity_label(label).casefold()


def duplicate_label_message(label: Any) -> str:
    display = normalize_entity_label(label) or "(leer)"
    return (
        f'Die Bezeichnung „{display}“ ist bereits vergeben. '
        "Bitte eine eindeutige Bezeichnung wählen."
    )


def find_conflicting_label(
    label: Any,
    items: list[dict],
    *,
    exclude_id: str | None = None,
) -> dict | None:
    """Return first sibling with the same label (case-insensitive), excluding ``exclude_id``."""
    key = label_compare_key(label)
    if not key:
        return None
    exclude = str(exclude_id or "").strip()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip()
        if exclude and item_id == exclude:
            continue
        if label_compare_key(item.get("label")) == key:
            return item
    return None


def find_duplicate_labels(items: list[dict]) -> list[str]:
    """Return distinct normalized labels that appear more than once in ``items``."""
    counts: dict[str, str] = {}
    duplicates: list[str] = []
    seen_dup: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw = normalize_entity_label(item.get("label"))
        key = label_compare_key(raw)
        if not key:
            continue
        if key in counts:
            if key not in seen_dup:
                duplicates.append(counts[key])
                seen_dup.add(key)
        else:
            counts[key] = raw
    return duplicates


def assert_unique_label(
    label: Any,
    items: list[dict],
    *,
    exclude_id: str | None = None,
) -> None:
    """Raise ``ValueError`` with a user-facing message if ``label`` is taken."""
    if find_conflicting_label(label, items, exclude_id=exclude_id) is not None:
        raise ValueError(duplicate_label_message(label))


def assert_unique_labels_in_list(items: list[dict]) -> None:
    """Raise ``ValueError`` if any non-empty label is duplicated within ``items``."""
    dups = find_duplicate_labels(items)
    if dups:
        raise ValueError(duplicate_label_message(dups[0]))
