"""Reine Zustandslogik für S-2-Segment- und Zyklus-Navigation (testbar ohne Streamlit)."""
from __future__ import annotations


def s2_back_disabled(
    cycle_offset: int,
    segment_index: int,
    max_cycle: int,
) -> bool:
    """True, wenn „← Zurück“ deaktiviert sein soll."""
    if segment_index == 1:
        return False
    return cycle_offset >= max_cycle


def s2_forward_disabled(cycle_offset: int, segment_index: int) -> bool:
    """True, wenn „Vor →“ deaktiviert sein soll."""
    if segment_index >= 1:
        return True
    return False


def apply_s2_nav_back(
    cycle_offset: int,
    segment_index: int,
    max_cycle: int,
) -> tuple[int, int]:
    """
    Nächster Zustand nach „← Zurück“.

    Segment SA₁→SA₂ → SA₀→SA₁. Sonst einen SA-Zyklus zurück (Segment bleibt 0).
    """
    if segment_index == 1:
        return cycle_offset, 0
    if cycle_offset >= max_cycle:
        return cycle_offset, segment_index
    return cycle_offset + 1, 0


def apply_s2_nav_forward(
    cycle_offset: int,
    segment_index: int,
) -> tuple[int, int]:
    """
    Nächster Zustand nach „Vor →“.

    cycle_offset > 0: einen Zyklus nach vorne (Richtung Live).
    cycle_offset == 0: Wechsel zu SA₁→SA₂ (nur Live-Vorausschau).
    """
    if segment_index >= 1:
        return cycle_offset, segment_index
    if cycle_offset > 0:
        return cycle_offset - 1, 0
    return 0, 1
