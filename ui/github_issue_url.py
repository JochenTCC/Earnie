"""Build GitHub Issues /new URLs for Streamlit Kontakt (public intake)."""
from __future__ import annotations

from urllib.parse import quote

from ui.truth_banner import OFFICIAL_REPO_URL

# Streamlit select labels (German) → (label for GitHub, title prefix)
ISSUE_KINDS: dict[str, tuple[str, str]] = {
    "Bug": ("bug", "[Bug]"),
    "Änderungswunsch": ("change-request", "[Change]"),
    "Verbesserung": ("improvement", "[Improvement]"),
    "Frage": ("question", "[Question]"),
}

ISSUE_KIND_LABELS: tuple[str, ...] = tuple(ISSUE_KINDS.keys())

_PRIVACY_FOOTER = (
    "---\n"
    "Hinweis: GitHub Issues sind öffentlich. Keine Passwörter, Hostnamen, "
    "Kundennamen oder vollständigen Config-/Debug-Dumps hier einfügen. "
    "Sensibles Material: support@earnie-hems.com (ZIP lokal behalten)."
)


def build_github_issue_url(
    kind: str,
    topic: str,
    description: str,
    *,
    extra_labels: tuple[str, ...] = (),
    version: str | None = None,
) -> str:
    """Prefill Issues/new with title, body, and labels (no auto-upload)."""
    label, prefix = ISSUE_KINDS.get(kind, ("question", "[Question]"))
    topic_clean = (topic or "").strip() or "Earnie Feedback"
    title = f"{prefix} {topic_clean}"
    body_parts = [
        (description or "").strip() or "(Beschreibung hier ergänzen)",
        "",
    ]
    if version and str(version).strip():
        body_parts.extend([f"Earnie-Version: {str(version).strip()}", ""])
    body_parts.append(_PRIVACY_FOOTER)
    body = "\n".join(body_parts)
    labels = ["needs-triage", label, *[x for x in extra_labels if x]]
    label_q = ",".join(labels)
    return (
        f"{OFFICIAL_REPO_URL.rstrip('/')}/issues/new"
        f"?title={quote(title, safe='')}"
        f"&body={quote(body, safe='')}"
        f"&labels={quote(label_q, safe='')}"
    )
