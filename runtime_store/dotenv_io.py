"""Lesen und Schreiben der Loxone-Zugangsdaten in config/.env."""
from __future__ import annotations

import os
import re

from runtime_store.env_vars import is_effective_offline, is_explicit_offline
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


def read_loxone_credentials() -> tuple[str, str, str]:
    """Return ``(ip, user, password)`` from the process environment (normalized)."""
    return (
        _normalized_env_value("LOXONE_IP"),
        _normalized_env_value("LOXONE_USER"),
        _normalized_env_value("LOXONE_PASS"),
    )


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
    if is_explicit_offline():
        return False
    if loxone_credentials_configured():
        return False
    from ui.setup_readiness import (
        _loxone_markers_complete,
        needs_planning_onboarding,
    )

    if needs_planning_onboarding():
        return True
    return not _loxone_markers_complete()


def needs_loxone_setup() -> bool:
    """True wenn die App auf der Hub-Setup-Seite blockieren soll."""
    if is_effective_offline():
        return False
    if loxone_setup_deferred():
        return False
    from runtime_store.ehal_setup import hub_credentials_configured

    return not hub_credentials_configured()


def require_loxone_credentials_for_config() -> bool:
    """Ob config.Config Loxone-Variablen zwingend laden soll."""
    if is_effective_offline():
        return False
    if loxone_setup_deferred():
        return False
    from runtime_store.ehal_setup import is_network_backend

    if is_network_backend():
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


def read_loxone_dotenv_file(path: str) -> tuple[str, str, str]:
    """Return ``(ip, user, password)`` from a specific .env file."""
    from dotenv import dotenv_values

    vals = dotenv_values(path)
    return (
        str(vals.get("LOXONE_IP") or "").strip(),
        str(vals.get("LOXONE_USER") or "").strip().strip('"'),
        str(vals.get("LOXONE_PASS") or ""),
    )


def _loxone_credentials_fingerprint(ip: str, user: str, password: str) -> str:
    import hashlib

    payload = f"{ip.strip()}|{user}|{password}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def loxone_dotenv_conflict() -> dict | None:
    """When another .env exists with different Loxone credentials than the active file."""
    canonical = resolve_dotenv_path()
    if not os.path.isfile(canonical):
        return None
    canon_ip, canon_user, canon_pass = read_loxone_dotenv_file(canonical)
    if not all([canon_ip, canon_user, canon_pass]):
        return None
    canon_fp = _loxone_credentials_fingerprint(canon_ip, canon_user, canon_pass)
    alternate_paths = (
        ("root", ".env"),
        ("legacy_config", os.path.join("config", ".env")),
    )
    conflicts: list[dict[str, str]] = []
    for label, path in alternate_paths:
        norm_canonical = os.path.normcase(os.path.abspath(canonical))
        norm_path = os.path.normcase(os.path.abspath(path))
        if norm_path == norm_canonical or not os.path.isfile(path):
            continue
        alt_ip, alt_user, alt_pass = read_loxone_dotenv_file(path)
        if not all([alt_ip, alt_user, alt_pass]):
            continue
        alt_fp = _loxone_credentials_fingerprint(alt_ip, alt_user, alt_pass)
        if alt_fp != canon_fp:
            conflicts.append({"label": label, "path": path})
    if not conflicts:
        return None
    return {"canonical_path": canonical, "conflicts": conflicts}


def import_loxone_dotenv_from(source_path: str) -> str:
    """Copy Loxone credentials from ``source_path`` into the active .env file."""
    ip, user, password = read_loxone_dotenv_file(source_path)
    error = validate_loxone_credentials(ip, user, password)
    if error:
        raise ValueError(error)
    return write_loxone_dotenv(ip, user, password)


def format_loxone_dotenv(ip: str, user: str, password: str) -> str:
    """Erzeugt den Inhalt von config/.env (ohne optionale Kommentarzeilen)."""
    escaped_user = user.strip().replace("\\", "\\\\").replace('"', '\\"')
    escaped_pass = password.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'LOXONE_USER="{escaped_user}"\n'
        f'LOXONE_PASS="{escaped_pass}"\n'
        f"LOXONE_IP={ip.strip()}\n"
    )


def _read_text_file(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def _assert_dotenv_target_usable(path: str) -> None:
    if os.path.isdir(path):
        raise OSError(
            f"'{path}' ist ein Verzeichnis (typisch fehlgeschlagener Docker-Bind-Mount). "
            "Bitte auf dem Host löschen und neu anlegen."
        )
    parent = os.path.dirname(path) or "."
    if not os.access(parent, os.W_OK):
        raise PermissionError(
            f"Keine Schreibrechte für das Config-Verzeichnis '{parent}'. "
            "Die .env-Datei wurde nicht geändert."
        )


def _write_tmp_file(tmp_path: str, content: str) -> None:
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def _restore_dotenv_content(path: str, backup: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(backup)
        handle.flush()
        try:
            os.fsync(handle.fileno())
        except OSError:
            pass


def _cleanup_tmp_file(tmp_path: str) -> None:
    if os.path.isfile(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass


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
    _assert_dotenv_target_usable(path)

    content = format_loxone_dotenv(ip, user, password)
    backup = _read_text_file(path) if os.path.isfile(path) else None
    tmp_path = f"{path}.tmp"
    try:
        _write_tmp_file(tmp_path, content)
        if _read_text_file(tmp_path) != content:
            raise OSError(
                "Temporäre .env-Datei unvollständig. Die bestehende .env wurde nicht geändert."
            )
        os.replace(tmp_path, path)
        if _read_text_file(path) != content:
            if backup is not None:
                _restore_dotenv_content(path, backup)
                raise OSError(
                    "Die .env-Datei konnte nicht zuverlässig geschrieben werden. "
                    "Der vorherige Inhalt wurde wiederhergestellt."
                )
            raise OSError(
                "Die .env-Datei konnte nicht zuverlässig geschrieben werden."
            )
    except OSError as exc:
        if backup is not None and _read_text_file(path) != backup:
            try:
                _restore_dotenv_content(path, backup)
            except OSError:
                pass
        raise OSError(str(exc)) from exc
    finally:
        _cleanup_tmp_file(tmp_path)
    if hasattr(os, "chmod"):
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path
