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


def test_soft_registry_caption_unbound_with_fp() -> None:
    from runtime_store.registry_entitlement import RegistryReport
    from ui.truth_banner import soft_registry_caption

    report = RegistryReport(
        status="unbound",
        fingerprint="a" * 64,
        fingerprint_display="a" * 16,
        detail="no entitlement file",
    )
    line = soft_registry_caption(report)
    assert line is not None
    assert "unbound" in line
    assert "`aaaaaaaaaaaaaaaa`" in line


def test_soft_registry_caption_valid() -> None:
    from runtime_store.registry_entitlement import RegistryReport
    from ui.truth_banner import soft_registry_caption

    report = RegistryReport(
        status="valid",
        fingerprint="b" * 64,
        fingerprint_display="b" * 16,
        detail="bound",
    )
    assert "bound" in (soft_registry_caption(report) or "")


def test_app_py_calls_render_truth_banner() -> None:
    root = Path(__file__).resolve().parents[1]
    app_src = (root / "app.py").read_text(encoding="utf-8")
    info_src = (root / "ui" / "info_sidebar.py").read_text(encoding="utf-8")
    assert "from ui.info_sidebar import render_info_sidebar" in app_src
    assert "render_info_sidebar()" in app_src
    assert "render_truth_banner(where=\"main\")" in app_src
    assert "render_truth_banner(where=\"inline\")" in info_src
    assert "render_registry_status_caption()" in info_src
    # Main banner must sit below page content (after navigation.run()).
    nav_idx = app_src.index("navigation.run()")
    banner_idx = app_src.index('render_truth_banner(where="main")')
    assert banner_idx > nav_idx
