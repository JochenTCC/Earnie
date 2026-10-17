"""EHAL push ID validation and value parsing (split from loxone_push_inbox)."""
from __future__ import annotations

import math
import re
from ehal.qualified_ids import (
    id_namespace_alternation,
)

HEARTBEAT_ID = "heartbeat"  # constant non-zero push that proves the Miniserver link


# Control receipt (POST /ehal/loxone/request_optimize) — not a telemetry field kind.
REQUEST_OPTIMIZE_ID = "request_optimize"


# Rows built from Shadow feed already passed lookup_record freshness (vs cycle_ts).
# Do not re-apply the live VO silence window (3×repeat) on those timestamps.
SHADOW_FEED_SOURCE = "shadow_feed"


# Loxone pushes measurements (sens_*) and inputs (get_*) only; never setpoints.
# Plus synthetic control IDs (heartbeat, request_optimize).
_ID_PATTERN = re.compile(
    r"^(?:"
    + HEARTBEAT_ID
    + r"|"
    + REQUEST_OPTIMIZE_ID
    + r"|(?:(?:"
    + id_namespace_alternation()
    + r")\.[a-z0-9_]{1,64}\.)?(?:sens|get)_[a-z0-9_]{1,64})$"
)


_UNIT_SUFFIXES = ("kWh", "kW", "W", "%", "°C", "A", "h")


# Plant-flat SoC retired (schema_version 4); push only ess.{id}.sens_ess_soc.
_RETIRED_PLANT_FLAT_PUSH_IDS: frozenset[str] = frozenset({"sens_ess_soc"})


def is_valid_ehal_id(ehal_id: object) -> bool:
    text = str(ehal_id or "")
    if text in _RETIRED_PLANT_FLAT_PUSH_IDS:
        return False
    return bool(_ID_PATTERN.match(text))


def parse_push_value(raw: object) -> float | None:
    """Parse a pushed value; ``None`` when empty, too long or not finite."""
    text = str(raw if raw is not None else "").strip().replace(",", ".")
    if not text or len(text) > MAX_RAW_LEN:
        return None
    for suffix in _UNIT_SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
            break
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


MAX_RAW_LEN = 32
