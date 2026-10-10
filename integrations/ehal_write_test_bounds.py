"""Clamp / bounds helpers for EHAL-Com Schreibtest probes."""
from __future__ import annotations

from typing import Any

from ehal.field_registry import require_loxone_write
from integrations.loxone_adapter import EVCS_MODE_VALUES
from optimizer.export_power_limit import EXPORT_LIMIT_UNCONSTRAINED_W

SAFE_PROBE_FIELDS: tuple[str, ...] = (
    "set_ess_mode",
    "set_ess_charge_power_limit",
    "set_ess_discharge_power_limit",
    "set_ess_source_select",
    "set_grid_export_power_limit",
    "set_evcs_max_current",
    "set_evcs_mode",
)

FORCE_ESS_ACTIVE_POWER = "set_ess_active_power"
ACTIVE_POWER_MAX_ABS_W = 200.0
DEFAULT_EVCS_PROBE_CAP_A = 6.0
DEFAULT_ROUNDTRIP_WAIT_S = 1.5

LIMIT_FIELDS = frozenset(
    {"set_ess_charge_power_limit", "set_ess_discharge_power_limit"}
)
EXPORT_LIMIT_FIELD = "set_grid_export_power_limit"
SOURCE_SELECT_FIELD = "set_ess_source_select"
FLEX_SET_ENABLE_KIND = "set_enable"
LOXONE_KW_WRITE_FIELDS = frozenset(
    {
        "set_ess_active_power",
        "set_ess_charge_power_limit",
        "set_ess_discharge_power_limit",
        EXPORT_LIMIT_FIELD,
    }
)


class WriteTestClampError(ValueError):
    """Raised when a probe value is outside allowed bounds or force is required."""


def canonical_probe_field(field: str) -> str:
    """Strip consumer prefix (``{id}:set_…`` → ``set_…``); keep Pattern B."""
    name = str(field or "").strip()
    if ":" in name:
        name = name.split(":", 1)[1]
    return name


def probe_kind(field: str) -> str:
    """Wire kind for clamp/bounds (Pattern B / flex → kind; else canonical)."""
    from ehal.ess_fields import ess_field_kind
    from ehal.flex_fields import flex_field_kind

    name = canonical_probe_field(field)
    kind = ess_field_kind(name)
    if kind:
        return kind
    flex_kind = flex_field_kind(name)
    if flex_kind:
        return flex_kind
    return name


def clamp_probe_value(
    field: str,
    value: Any,
    *,
    max_power_kw: float,
    ev_nominal_a: float | None = None,
    force_ess_active: bool = False,
) -> float | int | str:
    """Clamp/validate a probe value; raise WriteTestClampError on illegal force use."""
    kind = probe_kind(field)
    if kind == FORCE_ESS_ACTIVE_POWER:
        if not force_ess_active:
            raise WriteTestClampError(
                "set_ess_active_power erfordert die Force-Freigabe "
                f"(max ±{ACTIVE_POWER_MAX_ABS_W:g} W)."
            )
        raw = float(value)
        if abs(raw) > ACTIVE_POWER_MAX_ABS_W + 1e-9:
            raise WriteTestClampError(
                f"set_ess_active_power außerhalb ±{ACTIVE_POWER_MAX_ABS_W:g} W "
                f"(angegeben {raw:g})."
            )
        return max(-ACTIVE_POWER_MAX_ABS_W, min(ACTIVE_POWER_MAX_ABS_W, raw))

    if kind == "set_ess_mode":
        return _clamp_ess_mode(value)

    if kind in LIMIT_FIELDS:
        max_w = max(0.0, abs(float(max_power_kw)) * 1000.0)
        raw = float(value)
        if raw < 0 or raw > max_w + 1e-9:
            raise WriteTestClampError(
                f"{kind} muss in 0…{max_w:g} W liegen (angegeben {raw:g})."
            )
        return max(0.0, min(max_w, raw))

    if kind == EXPORT_LIMIT_FIELD:
        max_w = float(EXPORT_LIMIT_UNCONSTRAINED_W)
        raw = float(value)
        if raw < 0 or raw > max_w + 1e-9:
            raise WriteTestClampError(
                f"{kind} muss in 0…{max_w:g} W liegen (angegeben {raw:g})."
            )
        return max(0.0, min(max_w, raw))

    if kind == "set_evcs_max_current":
        cap = DEFAULT_EVCS_PROBE_CAP_A
        if ev_nominal_a is not None and float(ev_nominal_a) > 0:
            cap = min(float(ev_nominal_a), DEFAULT_EVCS_PROBE_CAP_A)
        raw = float(value)
        if raw < 0 or raw > cap + 1e-9:
            raise WriteTestClampError(
                f"set_evcs_max_current muss in 0…{cap:g} A liegen (angegeben {raw:g})."
            )
        return max(0.0, min(cap, raw))

    if kind == "set_evcs_mode":
        mode = str(value or "").strip().lower()
        if mode not in EVCS_MODE_VALUES:
            raise WriteTestClampError(
                f"set_evcs_mode muss off|pv|now sein (angegeben {value!r})."
            )
        return mode

    if kind in (SOURCE_SELECT_FIELD, FLEX_SET_ENABLE_KIND):
        return _clamp_binary_select(value, kind)

    raise WriteTestClampError(f"Feld nicht als Schreibtest-Probe erlaubt: {kind}")


def _clamp_binary_select(value: Any, kind: str) -> float:
    try:
        raw = float(value)
    except (TypeError, ValueError) as exc:
        raise WriteTestClampError(f"{kind} ungültig: {value!r}") from exc
    if raw not in (0.0, 1.0):
        raise WriteTestClampError(f"{kind} muss 0 oder 1 sein (angegeben {value!r}).")
    return raw


def _clamp_ess_mode(value: Any) -> int:
    if isinstance(value, str) and value.strip().lower() in ("automatik", "auto", "0"):
        return 0
    try:
        mode = int(float(value))
    except (TypeError, ValueError) as exc:
        raise WriteTestClampError(f"set_ess_mode ungültig: {value!r}") from exc
    if mode not in (0, 1, 2):
        raise WriteTestClampError(
            f"set_ess_mode muss 0|1|2 sein (angegeben {mode})."
        )
    return mode


def values_match(written: Any, read_back: Any, *, abs_tol: float = 1.0) -> bool:
    """Numeric abs≤1 or relative≤1%; modes compared as int/str."""
    if read_back is None:
        return False
    if isinstance(written, str) or isinstance(read_back, str):
        return str(written).strip().lower() == str(read_back).strip().lower()
    try:
        a = float(written)
        b = float(read_back)
    except (TypeError, ValueError):
        return written == read_back
    if abs(a - b) <= abs_tol:
        return True
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / scale <= 0.01


def expected_loxone_wire_value(field: str, ehal_value: Any) -> Any:
    """Value as stored on Loxone Merker (for unit-aware compare helpers/tests)."""
    kind = probe_kind(field)
    if kind == "set_ess_active_power":
        return require_loxone_write("set_ess_active_power", float(ehal_value))
    if kind in LIMIT_FIELDS or kind == EXPORT_LIMIT_FIELD:
        return require_loxone_write(kind, float(ehal_value))
    return ehal_value


def probe_value_bounds(
    field: str,
    *,
    max_power_kw: float,
    ev_nominal_a: float | None = None,
    force_ess_active: bool = False,
) -> tuple[float | None, float | None, str]:
    """Return (min, max, unit_hint) for UI number inputs; modes return (None, None, …)."""
    kind = probe_kind(field)
    if kind == FORCE_ESS_ACTIVE_POWER and force_ess_active:
        return -ACTIVE_POWER_MAX_ABS_W, ACTIVE_POWER_MAX_ABS_W, "W"
    if kind in LIMIT_FIELDS:
        max_w = max(0.0, abs(float(max_power_kw)) * 1000.0)
        return 0.0, max_w, "W"
    if kind == EXPORT_LIMIT_FIELD:
        return 0.0, float(EXPORT_LIMIT_UNCONSTRAINED_W), "W"
    if kind == "set_evcs_max_current":
        cap = DEFAULT_EVCS_PROBE_CAP_A
        if ev_nominal_a is not None and float(ev_nominal_a) > 0:
            cap = min(float(ev_nominal_a), DEFAULT_EVCS_PROBE_CAP_A)
        return 0.0, cap, "A"
    if kind == "set_ess_mode":
        return None, None, "0=Automatik / 1=Laden / 2=Entladen"
    if kind == SOURCE_SELECT_FIELD:
        return None, None, "0=Netz / 1=Batterie"
    if kind == FLEX_SET_ENABLE_KIND:
        return None, None, "0=Aus / 1=Ein"
    if kind == "set_evcs_mode":
        return None, None, "off|pv|now"
    return None, None, ""
