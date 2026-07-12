"""Lesen und Schreiben der Loxone-Zugangsdaten in config/.env."""
from __future__ import annotations

import os
import re

from runtime_store.env_vars import is_truthy
from runtime_store.persist_paths import resolve_dotenv_path

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)

_PLACEHOLDER_USERS = frozenset({"name-des-benutzers-in-der-loxone"})
_PLACEHOLDER_PASSES = frozenset({"passwort-des-benutzers-in-der-loxone"})

_LOXONE_KEYS = ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")


def _normalized_env_value(key: str) -> str:
    return str(os.getenv(key, "")).strip().strip('"')


def _is_placeholder_credential(key: str, value: str) -> bool:
    lowered = value.lower()
    if key == "LOXONE_USER":
        return lowered in _PLACEHOLDER_USERS
    if key == "LOXONE_PASS":
        return lowered in _PLACEHOLDER_PASSES
    return False


def loxone_credentials_configured() -> bool:
    """True wenn alle Loxone-Zugangsdaten gesetzt und keine Vorlagen-Platzhalter."""
    for key in _LOXONE_KEYS:
        value = _normalized_env_value(key)
        if not value or _is_placeholder_credential(key, value):
            return False
    return True


def loxone_setup_deferred() -> bool:
    """
    True wenn Loxone-.env bewusst zurückgestellt ist (Greenfield-Planungsphase).

    Zugangsdaten werden erst bei Live-/Silent-Betrieb oder Merker-Test benötigt.
    """
    if is_truthy("OFFLINE"):
        return False
    if loxone_credentials_configured():
        return False
    from ui.setup_readiness import (
        _loxone_markers_complete,
        is_planning_ready,
        needs_planning_onboarding,
    )

    if needs_planning_onboarding():
        return True
    if is_planning_ready() and not _loxone_markers_complete():
        return True
    return False


def needs_loxone_setup() -> bool:
    """True wenn die App auf der Loxone-Setup-Seite blockieren soll."""
    if is_truthy("OFFLINE"):
        return False
    if loxone_setup_deferred():
        return False
    return not loxone_credentials_configured()


def require_loxone_credentials_for_config() -> bool:
    """Ob config.Config Loxone-Variablen zwingend laden soll."""
    if is_truthy("OFFLINE"):
        return False
    if loxone_setup_deferred():
        return False
    return True


def validate_loxone_ip(ip: str) -> str | None:
    """Liefert Fehlermeldung oder None wenn die IPv4-Adresse gültig ist."""
    cleaned = ip.strip()
    if not cleaned:
        return "IP-Adresse ist erforderlich."
    if not _IPV4_RE.match(cleaned):
        return "Bitte eine gültige IPv4-Adresse eingeben (z. B. 192.168.178.1)."
    return None


def validate_loxone_credentials(ip: str, user: str, password: str) -> str | None:
    """Liefert Fehlermeldung oder None wenn alle Felder ausgefüllt sind."""
    ip_error = validate_loxone_ip(ip)
    if ip_error:
        return ip_error
    if not user.strip():
        return "Benutzername ist erforderlich."
    if not password:
        return "Passwort ist erforderlich."
    return None


def format_loxone_dotenv(ip: str, user: str, password: str) -> str:
    """Erzeugt den Inhalt von config/.env (ohne optionale Kommentarzeilen)."""
    escaped_user = user.strip().replace("\\", "\\\\").replace('"', '\\"')
    escaped_pass = password.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'LOXONE_USER="{escaped_user}"\n'
        f'LOXONE_PASS="{escaped_pass}"\n'
        f"LOXONE_IP={ip.strip()}\n"
    )


def write_loxone_dotenv(ip: str, user: str, password: str) -> str:
    """
    Schreibt Loxone-Zugangsdaten atomar nach config/.env.

    Returns:
        Pfad der geschriebenen Datei.
    """
    error = validate_loxone_credentials(ip, user, password)
    if error:
        raise ValueError(error)

    path = resolve_dotenv_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    content = format_loxone_dotenv(ip, user, password)
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    os.replace(tmp_path, path)
    if hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path
