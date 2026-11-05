"""Euro and cent amounts in the viewer's browser language (ui/number_format.py)."""
from __future__ import annotations

import pytest

from ui import number_format
from ui.number_format import (
    decimal_separator,
    format_cent_kwh,
    format_decimal,
    format_euro,
    plotly_separators,
    viewer_language,
)
from ui.saving_text import saving_text


def _viewer(monkeypatch: pytest.MonkeyPatch, header: str | None) -> None:
    monkeypatch.setattr(number_format, "_request_accept_language", lambda: header)


@pytest.mark.parametrize(
    ("header", "language"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", "de"),
        ("en-US,en;q=0.9,de;q=0.8", "en"),
        ("fr-FR,fr;q=0.9,en;q=0.8", "en"),
        ("fr-FR,ja", "de"),
        (None, "de"),
    ],
)
def test_viewer_language_falls_back_to_the_german_ui(
    monkeypatch: pytest.MonkeyPatch, header: str | None, language: str
) -> None:
    _viewer(monkeypatch, header)
    assert viewer_language() == language


def test_without_request_header_the_separator_is_a_comma() -> None:
    assert decimal_separator() == ","
    assert format_euro(12.345) == "12,35 €"
    assert plotly_separators() == ",."


def test_english_viewer_gets_a_point(monkeypatch: pytest.MonkeyPatch) -> None:
    _viewer(monkeypatch, "en-US,en;q=0.9")
    assert format_euro(-3.5, signed=True) == "-3.50 €"
    assert saving_text(-2.18) == "2.18 € mehr ausgegeben"
    assert plotly_separators() == ".,"


def test_signed_and_digits() -> None:
    assert format_decimal(0.2, signed=True) == "+0,20"
    assert format_euro(-100.0, signed=True) == "-100,00 €"
    assert format_cent_kwh(-0.1234, 3, signed=True) == "-0,123 Cent/kWh"
    assert format_cent_kwh(28.5, 1) == "28,5 Cent/kWh"
