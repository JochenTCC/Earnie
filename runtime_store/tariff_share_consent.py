"""Earnie's own consent for the Edibert tariff database (Edibert share consent).

State lives in ``runtime/tariff_share.json`` (``consent``: ``unset`` / ``on`` / ``off``, plus the
date of the last answer). Separate from the UsagePing consent: sharing a tariff carries no
installation ID. Only with consent ``on`` does Earnie build the Edibert exchange client and the
contribution transport for the embedded editor; ``EARNIE_OFFLINE=1`` and Edibert's own switch
``EDIBERT_EXCHANGE_OFF=1`` keep both off even then.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal

from runtime_store.env_vars import is_explicit_offline
from runtime_store.migration.io_util import write_json_atomic
from runtime_store.persist_paths import tariff_share_state_file

Consent = Literal["unset", "on", "off"]
_CONSENTS = ("unset", "on", "off")

# Why the exchange is off although the user agreed (shown on the Tarife page).
OFF_NO_CONSENT = "no_consent"
OFF_EARNIE_OFFLINE = "earnie_offline"
OFF_EDIBERT_SWITCH = "edibert_exchange_off"


def load_consent() -> Consent:
    """Stored answer; a missing file is ``unset``, an unreadable or unknown state is an error."""
    path = tariff_share_state_file()
    if not os.path.isfile(path):
        return "unset"
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    consent = raw.get("consent") if isinstance(raw, dict) else None
    if consent not in _CONSENTS:
        raise ValueError(f"{path}: ungültiger Zustand consent={consent!r}")
    return consent


def set_consent(value: Literal["on", "off"], *, today: date | None = None) -> None:
    """Store the user's answer (``off`` revokes an earlier ``on``)."""
    if value not in ("on", "off"):
        raise ValueError(f"invalid consent: {value!r}")
    state: dict[str, Any] = {
        "consent": value,
        "answered_at": (today or date.today()).isoformat(),
    }
    write_json_atomic(Path(tariff_share_state_file()), state)


@dataclass(frozen=True)
class Exchange:
    """What the Tarife page hands to the editor: both set, or both ``None`` with the reason."""

    client: Any | None
    transport: Any | None
    off_reason: str | None


def exchange_for_editor() -> Exchange:
    """Edibert exchange client and share transport, only with consent and no off switch."""
    from edibert.exchange import ExchangeClient, ServerTransport, exchange_config_from_env

    if load_consent() != "on":
        return Exchange(None, None, OFF_NO_CONSENT)
    if is_explicit_offline():
        return Exchange(None, None, OFF_EARNIE_OFFLINE)
    config = exchange_config_from_env()
    if config is None:
        return Exchange(None, None, OFF_EDIBERT_SWITCH)
    client = ExchangeClient(config)
    return Exchange(client, ServerTransport(client), None)
