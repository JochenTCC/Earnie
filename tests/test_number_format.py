"""Decimal separator from the viewer's browser language (ui/number_format.py)."""
from __future__ import annotations

import pytest

from ui import number_format
from ui.number_format import (
    decimal_separator_for_accept_language,
    format_cent_kwh,
    format_decimal,
    format_euro,
    plotly_separators,
)
from ui.saving_text import saving_text


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", ","),
        ("de-AT", ","),
        ("fr-FR,fr;q=0.9", ","),
        ("en-US,en;q=0.9,de;q=0.8", "."),
        ("en", "."),
        ("EN-gb", "."),
        ("ja-JP", "."),
        ("zh_CN", "."),
        ("*", ","),
        ("", ","),
        (None, ","),
    ],
)
def test_first_browser_language_decides(header: str | None, expected: str) -> None:
    assert decimal_separator_for_accept_language(header) == expected


def test_without_request_header_the_separator_is_a_comma() -> None:
    assert format_euro(12.345) == "12,35 €"
    assert plotly_separators() == ",."


@pytest.fixture
def english_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(number_format, "_request_accept_language", lambda: "en-US,en;q=0.9")


@pytest.mark.usefixtures("english_viewer")
def test_english_viewer_gets_a_point() -> None:
    assert format_euro(-3.5, signed=True) == "-3.50 €"
    assert saving_text(-2.18) == "2.18 € mehr ausgegeben"
    assert plotly_separators() == ".,"


def test_signed_and_digits() -> None:
    assert format_decimal(0.2, signed=True) == "+0,20"
    assert format_euro(-100.0, signed=True) == "-100,00 €"
    assert format_cent_kwh(-0.1234, 3, signed=True) == "-0,123 Cent/kWh"
    assert format_cent_kwh(28.5, 1) == "28,5 Cent/kWh"
