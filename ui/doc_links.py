"""GitHub deep-links from Streamlit chapters to docs/*.md sections.

Single source of truth for handbook / tech-doc URLs used in page titles
and captions. Keep in sync when nav labels or doc headings change
(see ``.cursor/skills/streamlit-doc-links``).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ui.truth_banner import OFFICIAL_REPO_URL

HANDBOOK_REL_PATH = "docs/user-manual/Benutzer-Handbuch-Earnie.md"
BLOB_PREFIX = f"{OFFICIAL_REPO_URL.rstrip('/')}/blob/main"

# Stable keys = st.Page ``url_path`` values from ``ui/navigation.py``.
NAV_DOC_PAGE_KEYS: frozenset[str] = frozenset(
    {
        "cockpit",
        "devices",
        "consumer-analysis",
        "price-forecast",
        "house-config",
        "scenario-editor",
        "scenario-explorer",
        "optimizer-daemon",
        "ehal-com",
    }
)


@dataclass(frozen=True)
class DocLink:
    """One clickable documentation target."""

    label: str
    path: str
    fragment: str | None = None

    @property
    def url(self) -> str:
        return docs_blob_url(self.path, self.fragment)


@dataclass(frozen=True)
class PageDocs:
    """Primary (book icon) + optional secondary links for a Streamlit page."""

    primary: DocLink
    secondaries: tuple[DocLink, ...] = field(default_factory=tuple)


def docs_blob_url(rel_path: str, fragment: str | None = None) -> str:
    """Build a GitHub ``blob/main`` URL for a repo-relative docs path."""
    path = (rel_path or "").strip().lstrip("/")
    if not path:
        raise ValueError("rel_path must be a non-empty docs path")
    url = f"{BLOB_PREFIX}/{path}"
    frag = (fragment or "").strip().lstrip("#")
    if frag:
        url = f"{url}#{frag}"
    return url


MANUAL_URL = docs_blob_url(HANDBOOK_REL_PATH)


def _handbook(label: str, fragment: str) -> DocLink:
    return DocLink(label=label, path=HANDBOOK_REL_PATH, fragment=fragment)


# Fragments match GitHub heading slugs (unicode kept; punctuation stripped).
PAGE_DOCS: dict[str, PageDocs] = {
    "cockpit": PageDocs(
        primary=_handbook("Monitor (Benutzer-Handbuch)", "monitor"),
        secondaries=(
            DocLink(
                "Betriebsmodi — Sunset-2-Sunset",
                "docs/ui/betriebsmodi.md",
                "sunset-2-sunset-seite-monitor",
            ),
            DocLink("Charts & Panels", "docs/ui/charts.md"),
        ),
    ),
    "devices": PageDocs(
        primary=_handbook("Manuelle Geräte (Benutzer-Handbuch)", "manuelle-geräte"),
    ),
    "consumer-analysis": PageDocs(
        primary=_handbook(
            "Analyse Verbrauch & Kosten (Benutzer-Handbuch)",
            "analyse-verbrauch--kosten",
        ),
    ),
    "house-config": PageDocs(
        primary=_handbook("Hauskonfigurator (Benutzer-Handbuch)", "hauskonfigurator"),
        secondaries=(
            DocLink(
                "Flexible Verbraucher",
                "docs/konfiguration/flexible-verbraucher.md",
            ),
            DocLink(
                "Historische Leistungsprofil-CSV",
                "docs/konfiguration/verbrauchs-csv.md",
            ),
        ),
    ),
    "scenario-editor": PageDocs(
        primary=_handbook("Szenarienkonfigurator (Benutzer-Handbuch)", "szenarien-editor"),
        secondaries=(
            DocLink(
                "Tarife und Preise nachrechnen",
                "docs/referenz/tarife-quellen.md",
            ),
            DocLink("Preise & aWATTar", "docs/konfiguration/preise.md"),
        ),
    ),
    "scenario-explorer": PageDocs(
        primary=_handbook(
            "Szenario-Explorer (Benutzer-Handbuch)",
            "szenario-explorer-was-wäre-wenn-analyse",
        ),
        secondaries=(
            DocLink(
                "Betriebsmodi — Szenario-Explorer",
                "docs/ui/betriebsmodi.md",
                "szenario-explorer",
            ),
            DocLink(
                "Jahres Verbrauch [kWh]",
                HANDBOOK_REL_PATH,
                "gesamtkosten-jahres-verbrauch-kwh",
            ),
            DocLink(
                "Tarife und Preise nachrechnen",
                "docs/referenz/tarife-quellen.md",
            ),
        ),
    ),
    "optimizer-daemon": PageDocs(
        primary=DocLink(
            "Betrieb (Optimierer-Dienst)",
            "docs/einrichtung/betrieb.md",
        ),
        secondaries=(
            _handbook(
                "Kurz-Checkliste Go-Live (Benutzer-Handbuch)",
                "kurz-checkliste-vom-initial-zustand-zum-go-live",
            ),
        ),
    ),
    "ehal-com": PageDocs(
        primary=_handbook(
            "EHAL-Com (Benutzer-Handbuch)",
            "ehal-com",
        ),
        secondaries=(
            DocLink(
                "EHAL-Com (UI)",
                "docs/ui/ehal-com.md",
            ),
            DocLink(
                "Loxone-Signale und Earnie-Library",
                "docs/referenz/loxone-signale.md",
            ),
            DocLink(
                "Home Assistant + evcc (A2/B)",
                "docs/einrichtung/ha-evcc.md",
            ),
            DocLink(
                "OpenEMS-Lab",
                "docs/einrichtung/openems-lab.md",
            ),
        ),
    ),
    "price-forecast": PageDocs(
        primary=DocLink(
            "Preisprognose (Spec)",
            "docs/spec/price-forecast-renewables.md",
        ),
    ),
}


def get_page_docs(page_key: str) -> PageDocs | None:
    """Return registered docs for a nav ``url_path``, or None if unknown."""
    key = (page_key or "").strip()
    return PAGE_DOCS.get(key)


def markdown_doc_link(link: DocLink) -> str:
    """Markdown ``[label](url)`` for captions / popovers."""
    return f"[{link.label}]({link.url})"
