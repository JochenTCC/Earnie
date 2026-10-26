"""Which engine prices the slots (Edibert P3a; removed with P3b).

``EARNIE_PRICING_ENGINE`` = ``earnie`` (default) or ``edibert``. Dev / CI switch only: no
settings key, no UI. With ``edibert`` the slot prices come from ``data/edibert_slot_prices.py``
and Earnie's own pricing functions are not called; an Edibert error is never answered with
an Earnie price. An unknown value is an error.
"""
from __future__ import annotations

import os

PRICING_ENGINE_ENV = "EARNIE_PRICING_ENGINE"
ENGINE_EARNIE = "earnie"
ENGINE_EDIBERT = "edibert"
VALID_ENGINES = (ENGINE_EARNIE, ENGINE_EDIBERT)


def pricing_engine() -> str:
    """Current engine from the environment; unset or empty means ``earnie``."""
    raw = str(os.environ.get(PRICING_ENGINE_ENV, "") or "").strip().lower()
    if not raw:
        return ENGINE_EARNIE
    if raw not in VALID_ENGINES:
        raise ValueError(
            f"{PRICING_ENGINE_ENV}={raw!r} ist ungültig (erlaubt: {', '.join(VALID_ENGINES)})."
        )
    return raw


def uses_edibert_pricing() -> bool:
    return pricing_engine() == ENGINE_EDIBERT
