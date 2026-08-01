"""Banner der Wahrheit — attribution (tamper-resistant, not tamper-proof)."""
from __future__ import annotations

import re
import subprocess
from typing import Literal
from urllib.parse import urlparse

import streamlit as st

from runtime_store.env_vars import read_env
from runtime_store.registry_entitlement import RegistryReport, registry_status
from version import __version__

OFFICIAL_REPO_URL = "https://github.com/JochenTCC/Earnie"
REQUIRED_PHRASE_NONCOMMERCIAL = "nicht-kommerziell"
REQUIRED_PHRASE_PRODUCT = "Earnie"
BANNER_LABEL = "Banner der Wahrheit"
SUPPORT_EMAIL = "mail@techcreacon.com"


def _normalize_repo_identity(raw: str) -> str:
    """Normalize git/HTTPS remote URLs to ``host/owner/repo`` (lowercase)."""
    text = raw.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    ssh = re.match(r"^git@([^:]+):(.+)$", text, flags=re.IGNORECASE)
    if ssh:
        host, path = ssh.group(1), ssh.group(2)
        return f"{host.lower()}/{path.strip('/').lower()}"
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").strip("/").lower()
    return f"{host}/{path}" if host and path else text.lower()


def resolve_build_origin() -> str | None:
    """Return build origin from env or ``git remote get-url origin``, else None."""
    from_env = read_env("BUILD_ORIGIN")
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    url = (result.stdout or "").strip()
    return url or None


def is_unofficial_origin(origin: str | None) -> bool:
    """True only when origin is present and clearly not the official repo."""
    if not origin or not str(origin).strip():
        return False
    official = _normalize_repo_identity(OFFICIAL_REPO_URL)
    actual = _normalize_repo_identity(origin)
    return actual != official


_BOUND_COLOR = "#008000"
_UNBOUND_COLOR = "#c62828"


def _attribution_line() -> str:
    return (
        f"**{REQUIRED_PHRASE_PRODUCT}** · privat, {REQUIRED_PHRASE_NONCOMMERCIAL} · "
        f"[{OFFICIAL_REPO_URL}]({OFFICIAL_REPO_URL}) · Version {__version__}"
    )


def _unofficial_message() -> str:
    return (
        f"**Inoffizieller / geänderter Build** ({BANNER_LABEL}). "
        f"Offizielles Projekt: [{OFFICIAL_REPO_URL}]({OFFICIAL_REPO_URL}). "
        f"Privat, {REQUIRED_PHRASE_NONCOMMERCIAL} — Version {__version__}."
    )


def registry_is_bound(report: RegistryReport) -> bool:
    """True only for a valid (bound) entitlement."""
    return report.status == "valid"


def attribution_registry_suffix(report: RegistryReport) -> str:
    """Short registry fragment for the attribution caption."""
    if report.status == "valid":
        return "· Registry: bound"
    if report.status == "unbound":
        return "· Registry: unbound"
    if report.status == "mismatch":
        return "· Registry: mismatch"
    return "· Registry: invalid_sig"


def _safe_registry_report() -> RegistryReport | None:
    try:
        return registry_status()
    except Exception:  # noqa: BLE001 — soft path
        return None


def colored_attribution_html(report: RegistryReport) -> str:
    """HTML for the colored attribution line including registry suffix."""
    color = _BOUND_COLOR if registry_is_bound(report) else _UNBOUND_COLOR
    suffix = attribution_registry_suffix(report)
    body = (
        f"<strong>{REQUIRED_PHRASE_PRODUCT}</strong> · privat, "
        f"{REQUIRED_PHRASE_NONCOMMERCIAL} · "
        f'<a href="{OFFICIAL_REPO_URL}">{OFFICIAL_REPO_URL}</a> · '
        f"Version {__version__} {suffix}"
    )
    return f'<p style="color:{color};font-size:0.875rem;margin:0;">{body}</p>'


def soft_registry_caption(report: RegistryReport | None = None) -> str | None:
    """
    Soft status caption for Info / About (never refuse-to-start).

    Short fingerprint for the caption; full FP is shown separately via
    ``render_registry_status_caption``.
    """
    try:
        status_report = report if report is not None else registry_status()
    except Exception:  # noqa: BLE001 — soft path
        return None
    short = status_report.fingerprint_display or (status_report.fingerprint or "")[:16]
    if status_report.status == "unbound":
        if short:
            return f"Registry: unbound (optional) · kurz `{short}`"
        return "Registry: unbound (optional)"
    if status_report.status == "valid":
        return f"Registry: bound (valid) · kurz `{short}`"
    if status_report.status == "mismatch":
        return (
            f"Registry: mismatch · kurz `{short}` "
            "(earnie_registry.json passt nicht zu diesem Host)"
        )
    return (
        f"Registry: invalid_sig · kurz `{short}` "
        f"({status_report.detail or 'signature'})"
    )


def registry_problem_note(report: RegistryReport) -> str | None:
    """Mild warning text for mismatch / invalid_sig; None otherwise."""
    if report.status == "mismatch":
        return (
            "Hardware-Registry: Fingerprint weicht von `earnie_registry.json` ab. "
            "Neuen Fingerprint senden und Datei erneut anfordern. "
            "Earnie startet trotzdem (soft check)."
        )
    if report.status == "invalid_sig":
        return (
            "Hardware-Registry: Signatur ungültig oder Datei beschädigt "
            f"({report.detail or 'invalid_sig'}). "
            "Datei neu anfordern. Earnie startet trotzdem (soft check)."
        )
    return None


REGISTRY_MAIL_GDPR_DISCLAIMER = (
    "Datenschutzhinweis (DSGVO):\n"
    "Ihre E-Mail-Adresse wird nur dann gespeichert, wenn Sie dem unten "
    "zustimmen — ausschließlich zum Zweck des Supports rund um die "
    "Registry-Ausstellung. Ohne Zustimmung wird die Adresse nach der "
    "Bearbeitung nicht gespeichert.\n"
    "Ich bin mit der Speicherung meiner E-Mail-Adresse für Supportzwecke "
    "einverstanden:\n"
    "[ ] Ja\n"
    "[x] Nein\n"
)


def build_registry_mailto_url(fingerprint: str) -> str:
    """Mailto to request an entitlement for the given full fingerprint."""
    from urllib.parse import quote

    fp = (fingerprint or "").strip().lower()
    subject = "Earnie Registry"
    body = (
        "Bitte stellen Sie eine earnie_registry.json für diese Installation aus.\n\n"
        f"Hardware-Fingerprint (vollständig, 64 Hex):\n{fp}\n\n"
        "Ablage nach Erhalt: earnie_env/runtime/earnie_registry.json "
        "(bzw. EARNIE_REGISTRY_PATH).\n\n"
        f"{REGISTRY_MAIL_GDPR_DISCLAIMER}"
    )
    return (
        f"mailto:{SUPPORT_EMAIL}"
        f"?subject={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def render_registry_status_caption() -> None:
    """Render fingerprint, status, registry mailto, mild problem note."""
    try:
        report = registry_status()
    except Exception:  # noqa: BLE001 — soft path
        return
    fp = (report.fingerprint or "").strip()
    st.markdown("**Hardware-Fingerprint** (vollständig, kopierbar)")
    if fp:
        st.code(fp, language=None)
    else:
        st.caption("Fingerprint nicht verfügbar.")
    line = soft_registry_caption(report)
    if report.status == "valid":
        st.success(line or "Registry: bound (valid)")
    elif line:
        st.caption(line)
    note = registry_problem_note(report)
    if note:
        st.warning(note)
    if bool(fp) and report.status != "valid":
        st.link_button(
            "Registry per E-Mail anfordern",
            build_registry_mailto_url(fp),
            width="stretch",
        )


def _registry_status_line_html(report: RegistryReport) -> str:
    """Colored HTML line with only the registry suffix (for unofficial builds)."""
    color = _BOUND_COLOR if registry_is_bound(report) else _UNBOUND_COLOR
    suffix = attribution_registry_suffix(report).lstrip("· ").strip()
    return (
        f'<p style="color:{color};font-size:0.875rem;margin:0;">{suffix}</p>'
    )


def _render_attribution_to(target) -> None:
    """Render colored attribution (+ registry) into ``target`` or active container."""
    unofficial = is_unofficial_origin(resolve_build_origin())
    report = _safe_registry_report()
    if unofficial:
        target.warning(_unofficial_message())
        if report is not None:
            target.markdown(
                _registry_status_line_html(report),
                unsafe_allow_html=True,
            )
        return
    if report is None:
        target.caption(_attribution_line())
        return
    target.markdown(colored_attribution_html(report), unsafe_allow_html=True)


def render_truth_banner(*, where: Literal["sidebar", "main", "inline"]) -> None:
    """Render attribution in sidebar root, main area, or current container."""
    if where == "sidebar":
        _render_attribution_to(st.sidebar)
        return
    # "main" and "inline" use the active Streamlit container (page or expander).
    _render_attribution_to(st)