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
    assert "valid" in (soft_registry_caption(report) or "")


def test_attribution_registry_suffix_and_bound() -> None:
    from runtime_store.registry_entitlement import RegistryReport
    from ui.truth_banner import (
        attribution_registry_suffix,
        colored_attribution_html,
        registry_is_bound,
    )

    unbound = RegistryReport(
        status="unbound",
        fingerprint="a" * 64,
        fingerprint_display="a" * 16,
        detail="no entitlement file",
    )
    valid = RegistryReport(
        status="valid",
        fingerprint="b" * 64,
        fingerprint_display="b" * 16,
        detail="bound",
    )
    mismatch = RegistryReport(
        status="mismatch",
        fingerprint="c" * 64,
        fingerprint_display="c" * 16,
        detail="fingerprint does not match entitlement",
    )
    assert registry_is_bound(valid) is True
    assert registry_is_bound(unbound) is False
    assert attribution_registry_suffix(valid) == "· Registry: bound"
    assert attribution_registry_suffix(unbound) == "· Registry: unbound"
    assert attribution_registry_suffix(mismatch) == "· Registry: mismatch"
    html_bound = colored_attribution_html(valid)
    html_unbound = colored_attribution_html(unbound)
    assert "#008000" in html_bound
    assert "Registry: bound" in html_bound
    assert "#c62828" in html_unbound
    assert "Registry: unbound" in html_unbound
    assert OFFICIAL_REPO_URL in html_bound


def test_registry_problem_note_mismatch_and_invalid() -> None:
    from runtime_store.registry_entitlement import RegistryReport
    from ui.truth_banner import registry_problem_note

    mismatch = RegistryReport(
        status="mismatch",
        fingerprint="c" * 64,
        fingerprint_display="c" * 16,
        detail="fingerprint does not match entitlement",
    )
    invalid = RegistryReport(
        status="invalid_sig",
        fingerprint="d" * 64,
        fingerprint_display="d" * 16,
        detail="Ed25519 signature mismatch",
    )
    unbound = RegistryReport(
        status="unbound",
        fingerprint="e" * 64,
        fingerprint_display="e" * 16,
        detail="no entitlement file",
    )
    assert registry_problem_note(mismatch) is not None
    assert "mismatch" in (registry_problem_note(mismatch) or "").lower() or "Fingerprint" in (
        registry_problem_note(mismatch) or ""
    )
    assert registry_problem_note(invalid) is not None
    assert "Signatur" in (registry_problem_note(invalid) or "")
    assert registry_problem_note(unbound) is None


def test_build_registry_mailto_url_includes_fingerprint() -> None:
    from urllib.parse import unquote

    from ui.truth_banner import (
        REGISTRY_MAIL_GDPR_DISCLAIMER,
        SUPPORT_EMAIL,
        build_registry_mailto_url,
    )

    fp = "ab" * 32
    url = build_registry_mailto_url(fp)
    assert url.startswith(f"mailto:{SUPPORT_EMAIL}?")
    assert "Earnie%20Registry" in url or "Earnie+Registry" in url
    assert fp in url or "ab%20" in url or "abab" in url
    decoded = unquote(url)
    assert "Datenschutzhinweis (DSGVO)" in decoded
    assert "[x] Nein" in decoded
    assert "[ ] Ja" in decoded
    assert "Supportzwecke" in decoded
    assert "DSGVO" in REGISTRY_MAIL_GDPR_DISCLAIMER


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
