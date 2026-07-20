"""Banner der Wahrheit — attribution (tamper-resistant, not tamper-proof)."""
from __future__ import annotations

import re
import subprocess
from typing import Literal
from urllib.parse import urlparse

import streamlit as st

from runtime_store.env_vars import read_env
from version import __version__

OFFICIAL_REPO_URL = "https://github.com/JochenTCC/Earnie"
REQUIRED_PHRASE_NONCOMMERCIAL = "nicht-kommerziell"
REQUIRED_PHRASE_PRODUCT = "Earnie"
BANNER_LABEL = "Banner der Wahrheit"


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


def render_truth_banner(*, where: Literal["sidebar", "main", "inline"]) -> None:
    """Render attribution in sidebar root, main area, or current container."""
    unofficial = is_unofficial_origin(resolve_build_origin())
    if where == "sidebar":
        target = st.sidebar
        if unofficial:
            target.warning(_unofficial_message())
        else:
            target.caption(_attribution_line())
        return
    # "main" and "inline" use the active Streamlit container (page or expander).
    if unofficial:
        st.warning(_unofficial_message())
    else:
        st.caption(_attribution_line())
