"""Earnie brand assets for the Streamlit chrome (sidebar logo)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ASSETS = _REPO_ROOT / "docs" / "assets"
_LOGO_LIGHT = _ASSETS / "Earnie-Logo-Simple-Light.png"
_LOGO_DARK = _ASSETS / "Earnie-Logo-Simple_Dark.png"


def _active_theme_type() -> str:
    """Return ``light`` or ``dark``; default light when theme is unknown."""
    theme = getattr(st.context, "theme", None)
    if theme is None:
        return "light"
    theme_type = theme.get("type") if hasattr(theme, "get") else getattr(theme, "type", None)
    if theme_type == "dark":
        return "dark"
    return "light"


def render_app_logo() -> None:
    """Show the theme-matching logo in Streamlit's sidebar chrome via ``st.logo``."""
    logo = _LOGO_DARK if _active_theme_type() == "dark" else _LOGO_LIGHT
    if not logo.is_file():
        return
    st.logo(str(logo), size="large")
