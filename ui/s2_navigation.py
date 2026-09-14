"""Reine Zustandslogik für S-2-Segment- und Zyklus-Navigation (testbar ohne Streamlit)."""
from __future__ import annotations

from data.planning_window import ChartSpan


def s2_back_disabled(
    cycle_offset: int,
    segment_index: int,
    max_cycle: int,
    *,
    span: ChartSpan = "segment",
) -> bool:
    """True, wenn „← Zurück“ deaktiviert sein soll."""
    if span == "full":
        return cycle_offset >= max_cycle
    if segment_index == 1:
        return False
    return cycle_offset >= max_cycle


def s2_forward_disabled(
    cycle_offset: int,
    segment_index: int,
    *,
    span: ChartSpan = "segment",
) -> bool:
    """True, wenn „Vor →“ deaktiviert sein soll."""
    if span == "full":
        # Forecast already on the SA₀→SA₂ plot; → only moves toward live.
        return cycle_offset == 0
    if segment_index >= 1:
        return True
    return False


def s2_heute_disabled(
    cycle_offset: int,
    segment_index: int,
    *,
    span: ChartSpan = "segment",
) -> bool:
    """True, wenn „Heute“ deaktiviert sein soll (bereits Live-Fenster)."""
    if span == "full":
        return cycle_offset == 0
    return cycle_offset == 0 and segment_index == 0


def apply_s2_nav_heute(*, span: ChartSpan = "segment") -> tuple[int, int]:
    """Zustand nach „Heute“: Live-Fenster (Segment 0 / full SA₀→SA₂)."""
    return 0, 0


def apply_s2_nav_back(
    cycle_offset: int,
    segment_index: int,
    max_cycle: int,
    *,
    span: ChartSpan = "segment",
) -> tuple[int, int]:
    """
    Nächster Zustand nach „← Zurück“.

    Segment-Modus: SA₁→SA₂ → SA₀→SA₁; sonst einen SA-Zyklus zurück.
    Full-Span: immer einen Zyklus zurück (Segment bleibt 0).
    """
    if span == "full":
        if cycle_offset >= max_cycle:
            return cycle_offset, 0
        return cycle_offset + 1, 0
    if segment_index == 1:
        return cycle_offset, 0
    if cycle_offset >= max_cycle:
        return cycle_offset, segment_index
    return cycle_offset + 1, 0


def apply_s2_nav_forward(
    cycle_offset: int,
    segment_index: int,
    *,
    span: ChartSpan = "segment",
) -> tuple[int, int]:
    """
    Nächster Zustand nach „Vor →“.

    Segment-Modus: cycle_offset > 0 → Zyklus Richtung Live; Live → SA₁→SA₂.
    Full-Span: nur Zyklus Richtung Live; bei Live no-op (→ disabled).
    """
    if span == "full":
        if cycle_offset > 0:
            return cycle_offset - 1, 0
        return 0, 0
    if segment_index >= 1:
        return cycle_offset, segment_index
    if cycle_offset > 0:
        return cycle_offset - 1, 0
    return 0, 1
