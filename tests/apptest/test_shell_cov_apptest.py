"""AppTest: app-shell widgets no other test rendered (coverage gap, 2026-11-22).

Shadow banner, Banner der Wahrheit, Info / About sidebar, month-end tariff hint,
star review dialog, usage-ping toggle, Loxone verify results, first-run EHAL page,
global CSS, navigation map. One dispatch script, case chosen via ``cov_case``.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

import pytest
from streamlit.testing.v1 import AppTest

from integrations.loxone_connectivity_base import LoxoneCheck
from runtime_store.registry_entitlement import RegistryReport
from tests.apptest.helpers import assert_clean, click

_SCRIPT = Path(__file__).parent / "scripts" / "run_cov_shell.py"
_FP = "ab" * 32


def _run(case: str, **state) -> AppTest:
    at = AppTest.from_file(str(_SCRIPT), default_timeout=30)
    at.session_state["cov_case"] = case
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    assert_clean(at)
    return at


def _link_buttons(at: AppTest, *, sidebar: bool = False) -> dict[str, str]:
    root = at.sidebar if sidebar else at
    return {e.proto.label: e.proto.url for e in root.get("link_button")}


# --- shadow banner ------------------------------------------------------------------------


@pytest.fixture
def shadow_on(monkeypatch):
    from ui import shadow_banner

    monkeypatch.setattr(shadow_banner, "is_shadow_mode", lambda: True)
    monkeypatch.setattr(shadow_banner, "is_shadow_config_readonly", lambda: True)
    return shadow_banner


def test_shadow_banner_fresh_feed_is_info(shadow_on, monkeypatch):
    monkeypatch.setattr(
        shadow_on,
        "feed_health",
        lambda: {"heartbeat_age_sec": 12.7, "heartbeat_ts": "2026-11-22T10:00:00Z", "stale": False, "prod_version": "2.7.3"},
    )
    at = _run("shadow_banner")
    assert not at.warning
    (info,) = at.info
    assert info.value.startswith("**Shadow-Modus** — Eingänge aus Prod-Feed (Stand ")
    assert "Alter 12 s" in info.value
    assert "2026-11-22T10:00:00Z" not in info.value  # ISO heartbeat shown as local clock time
    assert info.value.endswith("Konfiguration schreibgeschützt (Prod-Config)")
    assert at.caption[0].value.endswith("· Prod v2.7.3")


def test_shadow_banner_stale_feed_is_warning(shadow_on, monkeypatch):
    monkeypatch.setattr(shadow_on, "is_shadow_config_readonly", lambda: False)
    monkeypatch.setattr(
        shadow_on,
        "feed_health",
        lambda: {"heartbeat_age_sec": None, "heartbeat_ts": "kaputtZ", "stale": True},
    )
    at = _run("shadow_banner")
    assert not at.info
    (warning,) = at.warning
    assert "(Stand kaputtZ, Alter ?)" in warning.value
    assert "lokale Config schreibbar" in warning.value
    assert warning.value.endswith("— **Prod-Feed veraltet**")
    assert at.caption[0].value.endswith("· Prod v?")


def test_shadow_banner_hidden_outside_shadow(monkeypatch):
    from ui import shadow_banner

    monkeypatch.setattr(shadow_banner, "is_shadow_mode", lambda: False)
    at = _run("shadow_banner")
    assert not at.info and not at.warning and not at.caption


def test_shadow_would_write_table_newest_first(shadow_on, monkeypatch):
    rows = [
        {"ts": "t1", "cycle_seq": 1, "backend": "loxone", "target": "VI1", "value": 1.5, "source": "ess"},
        {"ts": "t2", "cycle_seq": 2, "backend": "loxone", "target": "VI2", "value": 0, "source": "fc"},
    ]
    seen_limit: list[int] = []

    def _read(*, limit):
        seen_limit.append(limit)
        return rows

    monkeypatch.setattr(shadow_on, "read_shadow_writes", _read)
    at = _run("shadow_table")
    assert seen_limit == [50]
    assert at.subheader[0].value == "Shadow — would write"
    frame = at.dataframe[0].value
    assert list(frame["Zeit"]) == ["t2", "t1"]
    assert list(frame["Wert"]) == ["0", "1.5"]
    assert list(frame.columns) == ["Zeit", "cycle_seq", "Backend", "Ziel", "Wert", "Quelle"]


def test_shadow_would_write_table_empty(shadow_on, monkeypatch):
    monkeypatch.setattr(shadow_on, "read_shadow_writes", lambda *, limit: [])
    at = _run("shadow_table")
    assert not at.dataframe
    assert at.caption[0].value == "Noch keine blockierten Schreibvorgänge in dieser Runtime."


# --- Banner der Wahrheit ------------------------------------------------------------------


def _patch_registry(monkeypatch, report: RegistryReport | Exception, *, origin: str | None = None):
    from ui import truth_banner

    def _status():
        if isinstance(report, Exception):
            raise report
        return report

    monkeypatch.setattr(truth_banner, "registry_status", _status)
    monkeypatch.setattr(truth_banner, "resolve_build_origin", lambda: origin)
    monkeypatch.setattr(truth_banner, "display_version", lambda: "9.9.9-test")


def test_truth_banner_main_official_bound_is_green(monkeypatch):
    _patch_registry(monkeypatch, RegistryReport(status="valid", fingerprint=_FP, fingerprint_display="abab"))
    at = _run("truth_main")
    assert not at.warning
    (md,) = at.markdown
    assert md.value.startswith('<p style="color:#008000;')
    assert "Version 9.9.9-test · Registry: bound" in md.value


def test_truth_banner_without_registry_falls_back_to_plain_caption(monkeypatch):
    _patch_registry(monkeypatch, RuntimeError("no registry"))
    at = _run("truth_main")
    (caption,) = at.caption
    assert caption.value.startswith("**Earnie** · privat, nicht-kommerziell")
    assert caption.value.endswith("Version 9.9.9-test")


def test_truth_banner_sidebar_unofficial_build_warns(monkeypatch):
    _patch_registry(
        monkeypatch,
        RegistryReport(status="unbound", fingerprint=_FP, fingerprint_display="abab"),
        origin="https://github.com/someone-else/Earnie",
    )
    at = _run("truth_sidebar")
    assert not at.main.warning
    (warning,) = at.sidebar.warning
    assert warning.value.startswith("**Inoffizieller / geänderter Build**")
    (md,) = at.sidebar.markdown
    assert md.value == '<p style="color:#c62828;font-size:0.875rem;margin:0;">Registry: unbound</p>'


def test_truth_banner_unofficial_without_registry_only_warns(monkeypatch):
    _patch_registry(monkeypatch, RuntimeError("x"), origin="git@example.org:fork/Earnie.git")
    at = _run("truth_main")
    assert len(at.warning) == 1
    assert not at.markdown


def test_registry_caption_valid_shows_success_and_no_request_button(monkeypatch):
    _patch_registry(monkeypatch, RegistryReport(status="valid", fingerprint=_FP, fingerprint_display="abab"))
    at = _run("registry_caption")
    assert at.markdown[0].value == "**Hardware-Fingerprint** (vollständig, kopierbar)"
    assert at.code[0].value == _FP
    assert at.success[0].value == "Registry: bound (valid) · kurz `abab`"
    assert not at.warning
    assert _link_buttons(at) == {}


def test_registry_caption_mismatch_warns_and_offers_mail(monkeypatch):
    _patch_registry(monkeypatch, RegistryReport(status="mismatch", fingerprint=_FP, fingerprint_display="abab"))
    at = _run("registry_caption")
    assert any(c.value.startswith("Registry: mismatch · kurz `abab`") for c in at.caption)
    assert at.warning[0].value.startswith("Hardware-Registry: Fingerprint weicht")
    url = _link_buttons(at)["Registry per E-Mail anfordern"]
    assert url.startswith("mailto:support@earnie-hems.com?subject=Earnie%20Registry")
    assert _FP in unquote(url)


def test_registry_caption_without_fingerprint(monkeypatch):
    _patch_registry(monkeypatch, RegistryReport(status="unbound", fingerprint="", fingerprint_display=""))
    at = _run("registry_caption")
    assert not at.code
    captions = [c.value for c in at.caption]
    assert "Fingerprint nicht verfügbar." in captions
    assert "Registry: unbound (optional)" in captions
    assert _link_buttons(at) == {}


def test_registry_caption_renders_nothing_when_status_fails(monkeypatch):
    _patch_registry(monkeypatch, RuntimeError("broken"))
    at = _run("registry_caption")
    assert not at.markdown and not at.code and not at.caption


# --- Info / About sidebar -----------------------------------------------------------------


def test_info_sidebar_links_and_private_mail_follow_topic(monkeypatch):
    _patch_registry(monkeypatch, RegistryReport(status="unbound", fingerprint=_FP, fingerprint_display="abab"))
    at = _run("info_sidebar")
    links = _link_buttons(at, sidebar=True)
    assert links["Benutzer-Handbuch"].startswith("http")
    assert links["Website"] == "https://earnie-hems.com"
    assert links["GitHub / Issues"] == "https://github.com/JochenTCC/Earnie/issues"
    assert links["GitHub-Issue öffnen"].startswith("https://github.com/JochenTCC/Earnie/issues/new")
    assert links["Private E-Mail vorbereiten"].startswith("mailto:support@earnie-hems.com?subject=Earnie%20Support")
    assert at.sidebar.selectbox(key="info_contact_kind").options

    at.text_input(key="info_contact_topic").set_value("Akku lädt nicht")
    at.text_area(key="info_contact_description").set_value("Seit gestern")
    at.run()
    assert_clean(at)
    links = _link_buttons(at, sidebar=True)
    private = unquote(links["Private E-Mail vorbereiten"])
    assert "subject=Akku lädt nicht" in private
    assert "Seit gestern" in private
    assert "Support-Paket" in private
    assert "Akku" in unquote(links["GitHub-Issue öffnen"])


@pytest.fixture
def month_end(monkeypatch):
    import config
    from house_config import tariff_month_hints

    monkeypatch.setattr(config, "is_runtime_params_deferred", lambda: False)
    monkeypatch.setattr(
        config,
        "get_resolved_runtime_settings",
        lambda: {"_import_tariff_spec": {"id": "imp"}, "_export_tariff_spec": None},
    )
    monkeypatch.setattr(tariff_month_hints, "is_within_days_of_next_month", lambda _now, days: True)
    monkeypatch.setattr(tariff_month_hints, "next_calendar_month", lambda _y, _m: (2026, 12))
    seen: list[dict] = []

    def _hints(**kw):
        seen.append(kw)
        return ["Bezug „Monatstarif“: Dezember fehlt"]

    monkeypatch.setattr(tariff_month_hints, "missing_next_month_tariff_hints", _hints)
    return seen


def test_missing_next_month_tariff_warns_near_month_end(month_end):
    at = _run("missing_tariff")
    (warning,) = at.sidebar.warning
    assert warning.value.startswith("**Monatstarif fehlt für 2026-12** (nächster Monat):")
    assert "- Bezug „Monatstarif“: Dezember fehlt" in warning.value
    assert month_end == [
        {"import_tariff": {"id": "imp"}, "export_tariff": None, "year": 2026, "month": 12}
    ]


def test_missing_next_month_tariff_silent_mid_month(month_end, monkeypatch):
    from house_config import tariff_month_hints

    monkeypatch.setattr(tariff_month_hints, "is_within_days_of_next_month", lambda _now, days: False)
    at = _run("missing_tariff")
    assert not at.sidebar.warning
    assert month_end == []


def test_missing_next_month_tariff_silent_without_hints(month_end, monkeypatch):
    from house_config import tariff_month_hints

    monkeypatch.setattr(tariff_month_hints, "missing_next_month_tariff_hints", lambda **_kw: [])
    at = _run("missing_tariff")
    assert not at.sidebar.warning


def test_missing_next_month_tariff_silent_when_runtime_deferred_or_broken(month_end, monkeypatch):
    import config

    monkeypatch.setattr(config, "is_runtime_params_deferred", lambda: True)
    assert not _run("missing_tariff").sidebar.warning

    def _boom():
        raise ValueError("bad config")

    monkeypatch.setattr(config, "is_runtime_params_deferred", lambda: False)
    monkeypatch.setattr(config, "get_resolved_runtime_settings", _boom)
    assert not _run("missing_tariff").sidebar.warning
    assert month_end == []


# --- star review dialog -------------------------------------------------------------------


@pytest.fixture
def review_spy(monkeypatch):
    from ui import star_review_dialog

    calls: dict[str, list] = {"send": [], "done": []}
    monkeypatch.setattr(star_review_dialog, "send_review", lambda **kw: calls["send"].append(kw))
    monkeypatch.setattr(
        star_review_dialog,
        "mark_review_done",
        lambda rid, *, sent: calls["done"].append((rid, sent)),
    )
    return calls


def test_star_review_dialog_shows_questions(review_spy):
    at = _run("star_review")
    assert at.markdown[0].value == "**Wie war es?**"
    assert "anonyme" in at.caption[0].value
    sliders = at.select_slider
    assert [s.label for s in sliders] == ["Einfach", "Verständlich"]
    assert [s.value for s in sliders] == [3, 3]


def test_star_review_send_posts_ratings_and_comment(review_spy):
    at = _run("star_review")
    at.select_slider(key="star_review_cov_review_q0").set_value(5)
    at.text_area(key="star_review_cov_review_comment").set_value("  gut  ")
    click(at, "star_review_cov_review_send")
    assert_clean(at)
    assert review_spy["send"] == [{"review_id": "cov_review", "ratings": [5, 3], "comment": "gut"}]
    assert review_spy["done"] == [("cov_review", True)]


def test_star_review_send_failure_shows_error(review_spy, monkeypatch):
    from ui import star_review_dialog

    def _fail(**_kw):
        raise RuntimeError("server down")

    monkeypatch.setattr(star_review_dialog, "send_review", _fail)
    at = click(_run("star_review"), "star_review_cov_review_send")
    assert_clean(at)
    assert [e.value for e in at.error] == ["Feedback konnte nicht gesendet werden: server down"]
    assert review_spy["done"] == []


def test_star_review_abort_marks_done_without_sending(review_spy):
    at = click(_run("star_review"), "star_review_cov_review_abort")
    assert_clean(at)
    assert review_spy["send"] == []
    assert review_spy["done"] == [("cov_review", False)]


# --- usage ping toggle --------------------------------------------------------------------


def test_usage_ping_toggle_saves_consent(monkeypatch):
    from runtime_store import usage_ping as up
    from ui import usage_ping_consent

    monkeypatch.delenv("EARNIE_USAGE_PING", raising=False)
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: False)
    saved: list[str] = []
    monkeypatch.setattr(usage_ping_consent, "set_consent", saved.append)

    at = _run("usage_settings")
    toggle = at.toggle(key="usage_ping_settings_toggle")
    assert toggle.value is False
    toggle.set_value(True).run()
    assert_clean(at)
    assert saved == ["on"]


def test_usage_ping_toggle_save_failure_shows_error(monkeypatch):
    from runtime_store import usage_ping as up
    from ui import usage_ping_consent

    monkeypatch.delenv("EARNIE_USAGE_PING", raising=False)
    monkeypatch.delenv("EARNIE_CLOUD_DEMO", raising=False)
    monkeypatch.setattr(up, "spawn_maybe_send_ping", lambda: False)

    def _fail(_value):
        raise OSError("read-only")

    monkeypatch.setattr(usage_ping_consent, "set_consent", _fail)
    at = _run("usage_settings")
    at.toggle(key="usage_ping_settings_toggle").set_value(True).run()
    assert_clean(at)
    assert "Nutzungsstatistik konnte nicht gespeichert werden: read-only" in [e.value for e in at.error]
    assert up.load_state().get("consent", "unset") == "unset"


# --- Loxone verify results / first-run EHAL page ------------------------------------------


def test_loxone_verify_results_mixed(monkeypatch):
    from runtime_store import loxone_auth_error

    monkeypatch.setattr(loxone_auth_error, "clear_loxone_auth_error", lambda: pytest.fail("must not clear on failure"))
    results = [
        LoxoneCheck(label="Netzleistung", io_name="AI_Grid", passed=True, detail="1.2 kW"),
        LoxoneCheck(label="SoC", io_name="", passed=False, detail="nicht gefunden", severity="warning"),
        LoxoneCheck(label="Sollwert", io_name="VI_Set", passed=False, detail="HTTP 404"),
    ]
    at = _run("loxone_verify", cov_ok=False, cov_results=results)
    assert [e.value for e in at.success] == ["**Netzleistung** (AI_Grid): 1.2 kW"]
    assert [e.value for e in at.warning] == ["**SoC**: nicht gefunden"]
    assert [e.value for e in at.error] == [
        "**Sollwert** (VI_Set): HTTP 404",
        "1 von 3 Prüfungen fehlgeschlagen.",
    ]


def test_loxone_verify_results_all_ok_clears_auth_error(monkeypatch):
    from runtime_store import loxone_auth_error

    cleared: list[int] = []
    monkeypatch.setattr(loxone_auth_error, "clear_loxone_auth_error", lambda: cleared.append(1))
    results = [LoxoneCheck(label="Netzleistung", io_name="AI_Grid", passed=True, detail="ok")]
    at = _run("loxone_verify", cov_ok=True, cov_results=results)
    assert [e.value for e in at.success] == [
        "**Netzleistung** (AI_Grid): ok",
        "Alle Loxone-Prüfungen erfolgreich.",
    ]
    assert not at.error
    assert cleared == [1]


def test_ehal_setup_page_shows_version_and_sb_page(monkeypatch):
    import streamlit as st

    from ui import setup_dotenv
    from ui.pages import page_smarthome_backend

    monkeypatch.setattr(setup_dotenv, "display_version", lambda: "9.9.9-test")
    monkeypatch.setattr(page_smarthome_backend, "render", lambda: st.markdown("SB-Seite"))
    at = _run("ehal_setup")
    assert at.caption[0].value == "Version 9.9.9-test"
    assert [m.value for m in at.markdown] == ["SB-Seite"]


# --- global CSS + chunk recovery ----------------------------------------------------------


def test_styles_and_chunk_recovery_reach_the_page():
    at = _run("styles")
    css = "\n".join(m.value for m in at.markdown)
    assert css.count("<style>") == 5
    for selector in (
        ".block-container",
        '[data-testid="stMetricValue"]',
        'st-key-help_hint__',
        'button[aria-label="Add files"]',
        '[data-testid="stCheckbox"]',
    ):
        assert selector in css, selector
    html = [e.proto.body for e in at.get("html")]
    assert len(html) == 1
    assert "Failed to fetch dynamically imported module" in html[0]
    assert "earnie_chunk_reloaded" in html[0]


# --- navigation ---------------------------------------------------------------------------


def test_build_navigation_registers_pages_by_url(monkeypatch):
    import streamlit as st

    from ui import navigation

    def _page():
        st.write("x")

    specs = [
        navigation.PageSpec(render=_page, title="Cockpit", icon="📊", section="Betrieb", url_path="cockpit", default=True),
        navigation.PageSpec(render=_page, title="Tarife", icon="💶", section="Konfiguration", url_path="tarife"),
    ]
    seen_keys: list[list[str]] = []

    def _specs(keys):
        seen_keys.append(keys)
        return specs

    monkeypatch.setattr(navigation, "build_page_specs", _specs)
    at = _run("navigation", cov_mode_keys=["sunset2sunset"])
    assert seen_keys == [["sunset2sunset"]]
    assert at.session_state["cov_nav_urls"] == ["cockpit", "tarife"]
