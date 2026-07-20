"""Tests for Banner der Wahrheit (attribution module + app wiring)."""
from __future__ import annotations

from pathlib import Path

from ui.truth_banner import (
    BANNER_LABEL,
    OFFICIAL_REPO_URL,
    REQUIRED_PHRASE_NONCOMMERCIAL,
    REQUIRED_PHRASE_PRODUCT,
    is_unofficial_origin,
)


def test_official_constants_present() -> None:
    assert OFFICIAL_REPO_URL == "https://github.com/JochenTCC/Earnie"
    assert REQUIRED_PHRASE_PRODUCT == "Earnie"
    assert "nicht-kommerziell" in REQUIRED_PHRASE_NONCOMMERCIAL
    assert BANNER_LABEL == "Banner der Wahrheit"


def test_is_unofficial_origin_none_or_empty_is_official() -> None:
    assert is_unofficial_origin(None) is False
    assert is_unofficial_origin("") is False
    assert is_unofficial_origin("   ") is False


def test_is_unofficial_origin_accepts_official_https_and_ssh() -> None:
    assert is_unofficial_origin("https://github.com/JochenTCC/Earnie") is False
    assert is_unofficial_origin("https://github.com/JochenTCC/Earnie.git") is False
    assert is_unofficial_origin("git@github.com:JochenTCC/Earnie.git") is False
    assert is_unofficial_origin("git@github.com:JochenTCC/Earnie") is False


def test_is_unofficial_origin_detects_other_repo() -> None:
    assert is_unofficial_origin("https://github.com/someone/forked-earnie") is True
    assert is_unofficial_origin("git@github.com:other/Earnie.git") is True


def test_app_py_calls_render_truth_banner() -> None:
    root = Path(__file__).resolve().parents[1]
    app_src = (root / "app.py").read_text(encoding="utf-8")
    info_src = (root / "ui" / "info_sidebar.py").read_text(encoding="utf-8")
    assert "from ui.info_sidebar import render_info_sidebar" in app_src
    assert "render_info_sidebar()" in app_src
    assert "render_truth_banner(where=\"main\")" in app_src
    assert "render_truth_banner(where=\"inline\")" in info_src
