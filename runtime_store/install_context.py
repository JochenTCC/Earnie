"""Install-context detection — narrows the Smarthome-Backend discovery scan.

Set by packaging, not guessed from the filesystem: the LoxBerry plugin compose
(``packaging/loxberry/data/docker/docker-compose.yml``) and the Home-Assistant
add-on entrypoint (``packaging/homeassistant-addon/earnie/run.sh``) both export
``EARNIE_INSTALL_CONTEXT``. Any other deployment (plain docker-compose, bare
metal, dev checkout) leaves it unset — "manual", no narrowing possible.

See docs/spec/smarthome-backend-page.md (M2) and backlog/SB-Identification-Draft.md.
"""
from __future__ import annotations

from typing import Literal

from runtime_store.env_vars import read_env

InstallContext = Literal["loxberry", "homeassistant_addon", "manual"]

_VALID_CONTEXTS = ("loxberry", "homeassistant_addon")


def detect_install_context() -> InstallContext:
    """``EARNIE_INSTALL_CONTEXT`` from the environment, normalized to a known value."""
    raw = read_env("INSTALL_CONTEXT").strip().lower()
    if raw in _VALID_CONTEXTS:
        return raw  # type: ignore[return-value]
    return "manual"


def install_context_target_kinds(
    context: InstallContext | None = None,
) -> list[str] | None:
    """Backend kind(s) implied by the install context, for a ``targeted`` SB scan.

    ``None`` means no narrowing — run a full passive scan (manual/unknown install,
    per SB-Identification-Draft.md's "In other cases make a full scan" fallback).
    """
    resolved = context if context is not None else detect_install_context()
    if resolved == "loxberry":
        return ["loxone"]
    if resolved == "homeassistant_addon":
        return ["home_assistant"]
    return None
