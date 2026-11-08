"""Savings as text: the amount without a sign, its meaning in words.

One place for the wording, so the Monitor tile and Chart 2 write a figure the same way.
The decimal separator follows the viewer's browser language (`ui/number_format.py`).
"""
from __future__ import annotations

from ui.number_format import format_euro


def euro_amount(euro: float) -> str:
    return format_euro(abs(euro))


def saving_is_loss(euro: float) -> bool:
    """A result that rounds to 0.00 € counts as saved, so no "0.00 € mehr ausgegeben" appears."""
    return round(euro, 2) < 0


def saving_text(euro: float) -> str:
    word = "mehr ausgegeben" if saving_is_loss(euro) else "gespart"
    return f"{euro_amount(euro)} {word}"


def soc_correction_text(euro: float) -> str:
    word = "abgezogen" if saving_is_loss(euro) else "gutgeschrieben"
    return f"{euro_amount(euro)} {word}"
