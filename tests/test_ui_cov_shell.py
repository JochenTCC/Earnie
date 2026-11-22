"""Unit tests for app-shell helpers that no other test executed (coverage gap, 2026-11-22).

Pure functions and thin session-state helpers: truth banner origin/attribution text,
star formatting, setup readiness checks, runtime-config cache, navigation page map,
usage-ping consent persistence. Streamlit calls are replaced by recorders.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from ehal.ess_fields import ess_field
from ehal.required_signals import required_binding_keys
from house_config.powerstation import BACKING_PHYSICAL, BACKING_VIRTUAL, ROLE_STANDBY_BACKUP
from runtime_store.registry_entitlement import RegistryReport
from ui import navigation, runtime_config, setup_readiness, star_review_dialog, truth_banner
from ui import usage_ping_consent


# --- truth_banner -------------------------------------------------------------------------


def test_resolve_build_origin_prefers_env(monkeypatch):
    monkeypatch.setattr(truth_banner, "read_env", lambda name: "https://example.org/fork" if name == "BUILD_ORIGIN" else None)

    def _no_git(*_a, **_k):
        raise AssertionError("git must not be asked when BUILD_ORIGIN is set")

    monkeypatch.setattr(truth_banner.subprocess, "run", _no_git)
    assert truth_banner.resolve_build_origin() == "https://example.org/fork"


def test_resolve_build_origin_reads_git_remote(monkeypatch):
    monkeypatch.setattr(truth_banner, "read_env", lambda _name: None)
    calls: list[list[str]] = []

    def _fake_run(cmd, **_kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="  git@github.com:someone/Earnie.git\n")

    monkeypatch.setattr(truth_banner.subprocess, "run", _fake_run)
    assert truth_banner.resolve_build_origin() == "git@github.com:someone/Earnie.git"
    assert calls == [["git", "remote", "get-url", "origin"]]


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(returncode=128, stdout="fatal"),
        SimpleNamespace(returncode=0, stdout="   "),
    ],
    ids=["git-fails", "empty-output"],
)
def test_resolve_build_origin_none_without_usable_remote(monkeypatch, result):
    monkeypatch.setattr(truth_banner, "read_env", lambda _name: None)
    monkeypatch.setattr(truth_banner.subprocess, "run", lambda *_a, **_k: result)
    assert truth_banner.resolve_build_origin() is None


@pytest.mark.parametrize("exc", [OSError("no git"), subprocess.TimeoutExpired("git", 2)])
def test_resolve_build_origin_none_when_git_missing_or_slow(monkeypatch, exc):
    monkeypatch.setattr(truth_banner, "read_env", lambda _name: None)

    def _raise(*_a, **_k):
        raise exc

    monkeypatch.setattr(truth_banner.subprocess, "run", _raise)
    assert truth_banner.resolve_build_origin() is None


def test_attribution_and_unofficial_texts_carry_required_phrases(monkeypatch):
    monkeypatch.setattr(truth_banner, "display_version", lambda: "9.9.9-test")
    line = truth_banner._attribution_line()
    assert line.startswith("**Earnie**")
    assert "nicht-kommerziell" in line
    assert truth_banner.OFFICIAL_REPO_URL in line
    assert line.endswith("Version 9.9.9-test")

    msg = truth_banner._unofficial_message()
    assert msg.startswith("**Inoffizieller / geänderter Build** (Banner der Wahrheit)")
    assert f"[{truth_banner.OFFICIAL_REPO_URL}]({truth_banner.OFFICIAL_REPO_URL})" in msg
    assert "Version 9.9.9-test." in msg


def test_safe_registry_report_swallows_errors(monkeypatch):
    def _boom():
        raise RuntimeError("registry file unreadable")

    monkeypatch.setattr(truth_banner, "registry_status", _boom)
    assert truth_banner._safe_registry_report() is None

    report = RegistryReport(status="valid", fingerprint="a" * 64, fingerprint_display="aaaa")
    monkeypatch.setattr(truth_banner, "registry_status", lambda: report)
    assert truth_banner._safe_registry_report() is report


@pytest.mark.parametrize(
    ("status", "color", "text"),
    [
        ("valid", "#008000", "Registry: bound"),
        ("unbound", "#c62828", "Registry: unbound"),
        ("mismatch", "#c62828", "Registry: mismatch"),
        ("invalid_sig", "#c62828", "Registry: invalid_sig"),
    ],
)
def test_registry_status_line_html_has_only_the_suffix(status, color, text):
    report = RegistryReport(status=status, fingerprint="", fingerprint_display="")
    html = truth_banner._registry_status_line_html(report)
    assert html == f'<p style="color:{color};font-size:0.875rem;margin:0;">{text}</p>'


# --- star_review_dialog -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "★☆☆☆☆ (1)"), (3, "★★★☆☆ (3)"), (5, "★★★★★ (5)")],
)
def test_format_star(n, expected):
    assert star_review_dialog._format_star(n) == expected


def test_arm_scenario_explorer_review_prompt_sets_pending(monkeypatch):
    session: dict[str, Any] = {}
    monkeypatch.setattr(star_review_dialog.st, "session_state", session)
    star_review_dialog.arm_scenario_explorer_review_prompt()
    assert session == {star_review_dialog.SESSION_SE_REVIEW_PENDING_KEY: True}


def _patch_prompt(monkeypatch, *, started: bool, done: bool) -> list[tuple]:
    opened: list[tuple] = []
    monkeypatch.setattr(star_review_dialog, "se_simulation_started", lambda: started)
    monkeypatch.setattr(star_review_dialog, "is_review_done", lambda _rid: done)
    monkeypatch.setattr(star_review_dialog, "_review_dialog", lambda *a: opened.append(a))
    return opened


def test_maybe_prompt_does_nothing_when_not_armed(monkeypatch):
    session: dict[str, Any] = {}
    monkeypatch.setattr(star_review_dialog.st, "session_state", session)
    opened = _patch_prompt(monkeypatch, started=True, done=False)
    star_review_dialog.maybe_prompt_scenario_explorer_review()
    assert opened == []
    assert session == {}


@pytest.mark.parametrize(("started", "done"), [(False, False), (True, True)])
def test_maybe_prompt_disarms_without_simulation_or_after_review(monkeypatch, started, done):
    key = star_review_dialog.SESSION_SE_REVIEW_PENDING_KEY
    session: dict[str, Any] = {key: True}
    monkeypatch.setattr(star_review_dialog.st, "session_state", session)
    opened = _patch_prompt(monkeypatch, started=started, done=done)
    star_review_dialog.maybe_prompt_scenario_explorer_review()
    assert opened == []
    assert session[key] is False


def test_maybe_prompt_opens_se_review_with_three_questions(monkeypatch):
    key = star_review_dialog.SESSION_SE_REVIEW_PENDING_KEY
    session: dict[str, Any] = {key: True}
    monkeypatch.setattr(star_review_dialog.st, "session_state", session)
    opened = _patch_prompt(monkeypatch, started=True, done=False)
    star_review_dialog.maybe_prompt_scenario_explorer_review()
    assert len(opened) == 1
    review_id, overall, questions = opened[0]
    assert review_id == star_review_dialog.REVIEW_ID_SCENARIO_EXPLORER
    assert overall.startswith("Wie war die Simulation?")
    assert len(questions) == 3
    assert session[key] is True  # stays armed until the dialog is answered


# --- setup_readiness ----------------------------------------------------------------------


def test_missing_planning_setup_items_reads_active_config(monkeypatch, tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{"marker": 1}', encoding="utf-8")
    monkeypatch.setattr(setup_readiness, "resolve_config_json_path", lambda: str(cfg))
    monkeypatch.setattr(setup_readiness, "resolve_components_json_path", lambda: "C.json")
    monkeypatch.setattr(setup_readiness, "resolve_tariffs_json_path", lambda: "T.json")
    monkeypatch.setattr(setup_readiness, "resolve_house_profiles_json_path", lambda: "H.json")
    seen: list[tuple] = []

    def _spy(raw, **kw):
        seen.append((raw, kw))
        return ["Hausprofil anlegen"]

    monkeypatch.setattr(setup_readiness, "missing_planning_setup_items_for", _spy)
    assert setup_readiness.missing_planning_setup_items() == ["Hausprofil anlegen"]
    assert seen == [
        (
            {"marker": 1},
            {"components_path": "C.json", "tariffs_path": "T.json", "house_profiles_path": "H.json"},
        )
    ]


def _inv_pv_keys(inverter_id: str) -> tuple[str, ...]:
    return required_binding_keys(
        component_kind="inverter",
        entity_id=inverter_id,
        control=setup_readiness_default_control(),
        has_attached_pv=True,
    )


def setup_readiness_default_control() -> str:
    from house_config.inverter import DEFAULT_INVERTER_CONTROL

    return DEFAULT_INVERTER_CONTROL


def test_inv_pv_activations_present_without_pv_systems():
    components = {"inverters": [{"id": "wr1"}, "not-a-dict", {"id": ""}], "pv_systems": []}
    assert setup_readiness._required_inv_pv_activations_present(components) is True


def test_inv_pv_activations_missing_for_inverter_with_pv():
    keys = _inv_pv_keys("wr1")
    assert keys, "inverter with attached PV must require at least one binding key"
    components = {
        "inverters": [{"id": "wr1", "ehal_bindings": {}}],
        "pv_systems": [{"id": "pv1", "inverter_id": "wr1"}],
    }
    assert setup_readiness._required_inv_pv_activations_present(components) is False


def test_inv_pv_activations_complete_for_inverter_with_pv():
    keys = _inv_pv_keys("wr1")
    components = {
        "inverters": [
            {"id": "wr1", "ehal_bindings": {k: "" for k in keys}},
            {"id": "wr2", "ehal_bindings": {}},  # no PV attached: not required
        ],
        "pv_systems": [{"id": "pv1", "inverter_id": "wr1"}],
    }
    assert setup_readiness._required_inv_pv_activations_present(components) is True


def _powerstation(bid: str, **extra) -> dict:
    return {"id": bid, "type": "powerstation", "role": ROLE_STANDBY_BACKUP, **extra}


def test_standby_backup_messages_empty_without_battery_list():
    assert setup_readiness.standby_backup_readiness_messages({"batteries": None}) == []


def test_standby_backup_messages_flag_virtual_and_unmapped():
    components = {
        "batteries": [
            {"id": "house", "type": "house"},  # not a powerstation
            {"id": "ps0", "type": "powerstation", "role": "single_use", "backing": BACKING_PHYSICAL},
            "junk",
            _powerstation("ps_virt", backing=BACKING_VIRTUAL),
            _powerstation("ps_phys", backing=BACKING_PHYSICAL, ehal_bindings={}),
            _powerstation(
                "ps_ok",
                backing=BACKING_PHYSICAL,
                ehal_bindings={ess_field("ps_ok", "set_ess_source_select"): "VI42"},
            ),
        ]
    }
    messages = setup_readiness.standby_backup_readiness_messages(components)
    assert len(messages) == 2
    assert messages[0].startswith("Powerstation „ps_virt“: Standby-Backup ist nur mit Backing „Physisch“")
    assert messages[1].startswith("Powerstation „ps_phys“ (Standby-Backup): Mapping für")
    assert ess_field("ps_phys", "set_ess_source_select") in messages[1]
    assert messages[1].endswith("Funktion nicht verfügbar.")


def test_standby_backup_messages_read_components_file_when_not_given(monkeypatch, tmp_path):
    import json

    path = tmp_path / "components.json"
    path.write_text(
        json.dumps({"batteries": [_powerstation("ps_file", backing=BACKING_VIRTUAL)]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_readiness, "resolve_components_json_path", lambda: str(path))
    messages = setup_readiness.standby_backup_readiness_messages()
    assert len(messages) == 1
    assert "„ps_file“" in messages[0]


# --- runtime_config -----------------------------------------------------------------------


def test_invalidate_live_optimization_cache_drops_only_live_keys(monkeypatch):
    live_keys = [
        "live_optimization_cache_key",
        "live_opt_in_cache_key",
        "live_display_snapshot_cache_key",
        "live_optimization_df",
        "live_savings_info",
        "live_optimization_matrix",
        "live_planning_window",
        "live_display_bundle",
        "live_opt_in_simulation_confirmed",
    ]
    session: dict[str, Any] = {k: object() for k in live_keys[::2]}
    session["unrelated"] = "keep"
    monkeypatch.setattr(runtime_config.st, "session_state", session)
    runtime_config.invalidate_live_optimization_cache()
    assert session == {"unrelated": "keep"}


# --- navigation ---------------------------------------------------------------------------


def test_nav_pages_by_url_creates_and_reuses_session_map(monkeypatch):
    import streamlit as st

    session: dict[str, Any] = {}
    monkeypatch.setattr(st, "session_state", session)
    first = navigation._nav_pages_by_url()
    assert first == {}
    first["cockpit"] = "page"
    assert navigation._nav_pages_by_url() is first
    assert session[navigation._NAV_PAGES_SESSION_KEY] is first


def test_switch_to_page_switches_to_registered_page(monkeypatch):
    import streamlit as st

    page = object()
    monkeypatch.setattr(st, "session_state", {navigation._NAV_PAGES_SESSION_KEY: {"cockpit": page}})
    switched: list[object] = []
    monkeypatch.setattr(st, "switch_page", switched.append)
    navigation.switch_to_page("cockpit")
    assert switched == [page]


def test_switch_to_page_unknown_url_names_available_pages(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "session_state", {navigation._NAV_PAGES_SESSION_KEY: {"b": 1, "a": 2}})
    monkeypatch.setattr(st, "switch_page", lambda _p: pytest.fail("must not switch"))
    with pytest.raises(RuntimeError, match=r"'nope' is not in the current navigation\. Available: a, b"):
        navigation.switch_to_page("nope")


def test_switch_to_page_without_navigation_says_none(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(st, "session_state", {})
    with pytest.raises(RuntimeError, match=r"Available: \(none\)"):
        navigation.switch_to_page("cockpit")


# --- usage_ping_consent -------------------------------------------------------------------


def test_apply_consent_success(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(usage_ping_consent, "set_consent", calls.append)
    monkeypatch.setattr(usage_ping_consent.st, "error", lambda *_a: pytest.fail("no error expected"))
    assert usage_ping_consent._apply_consent("on") is True
    assert calls == ["on"]


def test_apply_consent_failure_shows_error(monkeypatch):
    def _fail(_value):
        raise OSError("disk full")

    errors: list[str] = []
    monkeypatch.setattr(usage_ping_consent, "set_consent", _fail)
    monkeypatch.setattr(usage_ping_consent.st, "error", errors.append)
    assert usage_ping_consent._apply_consent("off") is False
    assert errors == ["Nutzungsstatistik konnte nicht gespeichert werden: disk full"]


@pytest.mark.parametrize(("toggle", "expected"), [(True, ["on"]), (False, ["off"])])
def test_save_usage_ping_toggle_writes_toggle_state(monkeypatch, toggle, expected):
    calls: list[str] = []
    monkeypatch.setattr(usage_ping_consent, "is_kill_switch_off", lambda: False)
    monkeypatch.setattr(usage_ping_consent, "set_consent", calls.append)
    monkeypatch.setattr(usage_ping_consent.st, "session_state", {"usage_ping_settings_toggle": toggle})
    usage_ping_consent._save_usage_ping_toggle()
    assert calls == expected


def test_save_usage_ping_toggle_ignored_under_kill_switch(monkeypatch):
    monkeypatch.setattr(usage_ping_consent, "is_kill_switch_off", lambda: True)
    monkeypatch.setattr(usage_ping_consent, "set_consent", lambda _v: pytest.fail("must not save"))
    monkeypatch.setattr(usage_ping_consent.st, "session_state", {"usage_ping_settings_toggle": True})
    usage_ping_consent._save_usage_ping_toggle()
