"""Lesen und Schreiben der Zugangsdaten (Loxone / HA) in config/.env."""
from __future__ import annotations

import os
import re

from runtime_store.env_vars import is_effective_offline, is_explicit_offline
from runtime_store.persist_paths import resolve_dotenv_path

_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)$"
)
_ENV_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")

_PLACEHOLDER_USERS = frozenset({"name-des-benutzers-in-der-loxone"})
_PLACEHOLDER_PASSES = frozenset({"passwort-des-benutzers-in-der-loxone"})

_LOXONE_KEYS = ("LOXONE_IP", "LOXONE_USER", "LOXONE_PASS")
_HA_KEYS = ("EHAL_HA_BASE_URL", "EHAL_HA_TOKEN")
_QUOTED_KEYS = frozenset({"LOXONE_USER", "LOXONE_PASS", "EHAL_HA_TOKEN"})


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


def read_ha_credentials() -> tuple[str, str]:
    """Return ``(base_url, token)`` from the process environment (normalized)."""
    return (
        _normalized_env_value("EHAL_HA_BASE_URL"),
        _normalized_env_value("EHAL_HA_TOKEN"),
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


def deferred_loxone_blocks_live() -> bool:
    """True when main must wait for LOXONE_* before entering the live loop.

    Greenfield may defer Loxone credentials during planning. That wait must
    not apply when the active EHAL hub is HA/OpenEMS (network backends).
    """
    if not loxone_setup_deferred():
        return False
    if loxone_credentials_configured():
        return False
    from runtime_store.ehal_setup import is_network_backend

    return not is_network_backend()


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
    """Liefert Fehlermeldung oder None wenn IPv4 bzw. IPv4:port gültig ist."""
    cleaned = ip.strip()
    if not cleaned:
        return "IP-Adresse ist erforderlich."
    host, sep, port_text = cleaned.partition(":")
    if sep:
        if not host or not port_text or ":" in port_text:
            return (
                "Bitte eine gültige IPv4-Adresse eingeben "
                "(z. B. 192.168.178.1 oder 192.168.178.1:85)."
            )
        if not port_text.isdigit():
            return (
                "Bitte eine gültige IPv4-Adresse eingeben "
                "(z. B. 192.168.178.1 oder 192.168.178.1:85)."
            )
        port = int(port_text)
        if port < 1 or port > 65535:
            return "Port muss zwischen 1 und 65535 liegen."
    if not _IPV4_RE.match(host if sep else cleaned):
        return (
            "Bitte eine gültige IPv4-Adresse eingeben "
            "(z. B. 192.168.178.1 oder 192.168.178.1:85)."
        )
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


def read_ha_dotenv_file(path: str) -> tuple[str, str]:
    """Return ``(base_url, token)`` from a specific .env file."""
    from dotenv import dotenv_values

    vals = dotenv_values(path)
    return (
        str(vals.get("EHAL_HA_BASE_URL") or "").strip().strip('"'),
        str(vals.get("EHAL_HA_TOKEN") or "").strip().strip('"'),
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


def _escape_dotenv_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _format_env_assignment(key: str, value: str) -> str:
    if key in _QUOTED_KEYS:
        return f'{key}="{_escape_dotenv_value(value)}"\n'
    return f"{key}={value}\n"


def format_loxone_dotenv(ip: str, user: str, password: str) -> str:
    """Erzeugt nur die Loxone-Zeilen (ohne Merge; Tests / Vorlagen)."""
    return (
        _format_env_assignment("LOXONE_USER", user.strip())
        + _format_env_assignment("LOXONE_PASS", password)
        + _format_env_assignment("LOXONE_IP", ip.strip())
    )


def _merge_dotenv_content(existing: str | None, updates: dict[str, str]) -> str:
    """Replace or append KEY=value lines; preserve other lines and comments."""
    pending = dict(updates)
    lines_out: list[str] = []
    source = existing or ""
    for raw_line in source.splitlines(keepends=True):
        stripped = raw_line.rstrip("\r\n")
        match = _ENV_ASSIGN_RE.match(stripped)
        if match and match.group(1) in pending:
            key = match.group(1)
            lines_out.append(_format_env_assignment(key, pending.pop(key)))
            continue
        lines_out.append(raw_line if raw_line.endswith("\n") else raw_line + "\n")
    if lines_out and not lines_out[-1].endswith("\n"):
        lines_out[-1] = lines_out[-1] + "\n"
    for key, value in pending.items():
        lines_out.append(_format_env_assignment(key, value))
    return "".join(lines_out)


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


def _atomic_write_dotenv(content: str) -> str:
    """Atomically write full .env content; returns path."""
    path = resolve_dotenv_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    _assert_dotenv_target_usable(path)

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


def upsert_dotenv_keys(updates: dict[str, str]) -> str:
    """Merge KEY=value updates into the active .env; preserve other keys/lines."""
    if not updates:
        return resolve_dotenv_path()
    path = resolve_dotenv_path()
    existing = _read_text_file(path) if os.path.isfile(path) else None
    content = _merge_dotenv_content(existing, updates)
    return _atomic_write_dotenv(content)


def write_loxone_dotenv(ip: str, user: str, password: str) -> str:
    """
    Schreibt Loxone-Zugangsdaten atomar nach config/.env (merge-upsert).

    Returns:
        Pfad der geschriebenen Datei.
    """
    error = validate_loxone_credentials(ip, user, password)
    if error:
        raise ValueError(error)
    return upsert_dotenv_keys(
        {
            "LOXONE_USER": user.strip(),
            "LOXONE_PASS": password,
            "LOXONE_IP": ip.strip(),
        }
    )


def write_ha_dotenv(base_url: str, token: str) -> str:
    """
    Schreibt HA base_url/token atomar nach config/.env (merge-upsert).

    Empty token is allowed (Supervisor add-on resolves SUPERVISOR_TOKEN at runtime).
    Never persist SUPERVISOR_TOKEN itself.
    """
    return upsert_dotenv_keys(
        {
            "EHAL_HA_BASE_URL": str(base_url or "").strip(),
            "EHAL_HA_TOKEN": str(token or "").strip(),
        }
    )
