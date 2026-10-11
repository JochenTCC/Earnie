"""Sidebar logo assets ship with the UI package (Docker/HA image)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import ui.branding as branding


def test_logo_asset_files_exist() -> None:
    assert branding._LOGO_LIGHT.is_file()
    assert branding._LOGO_DARK.is_file()
    assert branding._ASSETS == Path(branding.__file__).resolve().parent / "assets"


def test_render_app_logo_calls_st_logo(monkeypatch) -> None:
    calls: list[tuple] = []
    fake_st = MagicMock()
    fake_st.context.theme = {"type": "light"}
    fake_st.logo = lambda path, size="large": calls.append((path, size))
    monkeypatch.setattr(branding, "st", fake_st)

    branding.render_app_logo()

    assert len(calls) == 1
    assert calls[0][0] == str(branding._LOGO_LIGHT)
    assert calls[0][1] == "large"
