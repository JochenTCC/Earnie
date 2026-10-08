"""Bounded EHAL write-test helpers (EHAL-Com Schreibtest).

Safe probes and optional tiny ``set_ess_active_power`` with clamps, silent gate,
read-after-write roundtrip, and restore to Automatik / EVCS 0 A.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import config
from ehal import EHAL_SCHEMA_VERSION, EhalWriteError
from integrations import ehal_live
from integrations.ehal_debug_mapping import (
    PLANT_LIVE_WRITE_FIELDS,
    ha_setpoint_mapping,
    loxone_write_field_to_io,
)
from integrations.ehal_write_test_bounds import (
    ACTIVE_POWER_MAX_ABS_W,
    DEFAULT_EVCS_PROBE_CAP_A,
    DEFAULT_ROUNDTRIP_WAIT_S,
    FORCE_ESS_ACTIVE_POWER,
    LOXONE_KW_WRITE_FIELDS,
    SAFE_PROBE_FIELDS,
    WriteTestClampError,
    canonical_probe_field,
    clamp_probe_value,
    expected_loxone_wire_value,
    probe_kind,
    probe_value_bounds,
    values_match,
)
from integrations.ha_adapter import parse_ha_field_value
from integrations.loxone_adapter import EVCS_MODE_VALUES

logger = logging.getLogger(__name__)

# Re-export bounds API for callers / tests.
__all__ = [
    "ACTIVE_POWER_MAX_ABS_W",
    "DEFAULT_EVCS_PROBE_CAP_A",
    "DEFAULT_ROUNDTRIP_WAIT_S",
    "FORCE_ESS_ACTIVE_POWER",
    "SAFE_PROBE_FIELDS",
    "BatchRoundtripResult",
    "RoundtripResult",
    "RoundtripStatus",
    "WriteTestClampError",
    "WriteTestSilentError",
    "allowed_probe_fields",
    "assert_writes_allowed",
    "build_probe_setpoint",
    "build_probes_setpoint",
    "canonical_probe_field",
    "clamp_probe_value",
    "default_ev_nominal_a",
    "expected_loxone_wire_value",
    "looks_like_housesim",
    "mapped_write_targets",
    "probe_kind",
    "probe_value_bounds",
    "read_back",
    "restore_safe_setpoints",
    "roundtrip",
    "roundtrip_batch",
    "values_match",
    "write_probe",
    "write_probes",
    "writes_allowed",
]


class RoundtripStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    WRITE_ERROR = "write_error"
    SILENT = "silent"


@dataclass(frozen=True)
class RoundtripResult:
    status: RoundtripStatus
    field: str
    written: Any
    read_back: Any | None
    message: str
    write_error: EhalWriteError | None = None


@dataclass(frozen=True)
class BatchRoundtripResult:
    status: RoundtripStatus
    written: dict[str, Any]
    echoes: dict[str, Any | None]
    message: str
    field_results: tuple[RoundtripResult, ...]
    write_error: EhalWriteError | None = None


class WriteTestSilentError(RuntimeError):
    """Raised when Silent mode blocks a write-test."""


def writes_allowed() -> bool:
    """True when Silent mode is off (same gate as daemon southbound writes)."""
    return not bool(config.is_silent_mode())


def assert_writes_allowed() -> None:
    if not writes_allowed():
        raise WriteTestSilentError(
            "Silent-Modus aktiv — Schreibtest blockiert. "
            "Silent auf Optimierer-Dienst / Statusleiste ausschalten."
        )


def mapped_write_targets() -> dict[str, str]:
    """Live-write field id → backend address (entity / Merker / channel label)."""
    if ehal_live.is_ha_backend():
        return _ha_mapped_targets()
    if ehal_live.is_openems_backend():
        return _openems_mapped_targets()
    return _loxone_mapped_targets()


def _openems_mapped_targets() -> dict[str, str]:
    adapter = ehal_live.get_openems_adapter()
    caps = adapter.capabilities()
    out: dict[str, str] = {}
    if caps.get("supports_ess_write"):
        for field in PLANT_LIVE_WRITE_FIELDS:
            out[field] = f"openems:{field}"
    if caps.get("supports_evcs_current"):
        out["set_evcs_max_current"] = "openems:set_evcs_max_current"
    return out


def _ha_mapped_targets() -> dict[str, str]:
    from integrations.ehal_debug_mapping import expected_live_write_fields

    adapter = ehal_live.get_ha_adapter()
    entities = dict(adapter.cfg.entities)
    flat = ha_setpoint_mapping(entities)
    out: dict[str, str] = dict(flat)
    for field in expected_live_write_fields(network_backend=False):
        addr = str(entities.get(field) or "").strip()
        if addr:
            out[field] = addr
    return out


def _loxone_mapped_targets() -> dict[str, str]:
    raw = loxone_write_field_to_io()
    out: dict[str, str] = {}
    for field, io_name in raw.items():
        name = str(field or "").strip()
        marker = str(io_name or "").strip()
        if name and marker and name not in out:
            out[name] = marker
    return out


def allowed_probe_fields(*, force_ess_active: bool = False) -> list[str]:
    """All mapped Live-Schreiben fields (incl. ``set_ess_active_power``).

    ``force_ess_active`` is kept for callers; listing no longer hides active power —
    Schreibtest still requires Force to *send* those rows (clamp + UI).
    """
    del force_ess_active  # listing is independent of Force unlock
    from integrations.ehal_debug_mapping import expected_live_write_fields

    mapped = mapped_write_targets()
    network = bool(ehal_live.is_ehal_network_backend())
    ordered = expected_live_write_fields(network_backend=network)
    fields: list[str] = []
    seen: set[str] = set()
    for field in ordered:
        if field not in mapped or field in seen:
            continue
        seen.add(field)
        fields.append(field)
    for field in sorted(mapped):
        if field in seen:
            continue
        kind = probe_kind(field)
        if kind.startswith("set_") or kind in SAFE_PROBE_FIELDS or kind == "set_enable":
            seen.add(field)
            fields.append(field)
    return fields


def default_ev_nominal_a() -> float | None:
    """Best-effort EV nominal current (A) from first EV consumer, else None."""
    from integrations.ehal_debug_mapping import _all_live_consumers, _consumer_is_ev
    from settings.ev_power import ev_nominal_power_conversion, kw_to_ampere

    for consumer in _all_live_consumers():
        if not _consumer_is_ev(consumer):
            continue
        try:
            voltage_v, phases = ev_nominal_power_conversion(consumer)
            nom_kw = float(consumer.get("nominal_power_kw") or 0.0)
            if nom_kw <= 0:
                continue
            return float(kw_to_ampere(nom_kw, voltage_v=voltage_v, phases=phases))
        except (TypeError, ValueError, KeyError):
            continue
    return None


def build_probe_setpoint(field: str, value: Any, *, adapter_id: str) -> dict[str, Any]:
    return build_probes_setpoint({field: value}, adapter_id=adapter_id)


def build_probes_setpoint(
    values: dict[str, Any], *, adapter_id: str
) -> dict[str, Any]:
    """Plant-flat / EV setpoint document (no Pattern B / flex keys)."""
    from ehal.ess_fields import is_ess_pattern_b_field
    from ehal.flex_fields import flex_field_kind

    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter_id,
    }
    for field, value in values.items():
        name = canonical_probe_field(field)
        if is_ess_pattern_b_field(name) or flex_field_kind(name):
            continue
        doc[probe_kind(field)] = value
    return doc


def clamp_probe_values(
    values: dict[str, Any],
    *,
    max_power_kw: float,
    ev_nominal_a: float | None = None,
    force_ess_active: bool = False,
) -> dict[str, Any]:
    """Clamp a batch of probe fields; empty input raises WriteTestClampError."""
    if not values:
        raise WriteTestClampError("Keine Sollwerte zum Schreiben ausgewählt.")
    out: dict[str, Any] = {}
    for field, value in values.items():
        key = str(field or "").strip()
        out[key] = clamp_probe_value(
            key,
            value,
            max_power_kw=max_power_kw,
            ev_nominal_a=ev_nominal_a,
            force_ess_active=force_ess_active,
        )
    return out


def write_probes(
    values: dict[str, Any],
    *,
    force_ess_active: bool = False,
    max_power_kw: float | None = None,
    ev_nominal_a: float | None = None,
) -> tuple[EhalWriteError | None, dict[str, Any]]:
    """Write clamped probes (adapter + Pattern B / flex Merker paths)."""
    assert_writes_allowed()
    if max_power_kw is None:
        max_power_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    if ev_nominal_a is None:
        ev_nominal_a = default_ev_nominal_a()
    clamped = clamp_probe_values(
        values,
        max_power_kw=float(max_power_kw),
        ev_nominal_a=ev_nominal_a,
        force_ess_active=force_ess_active,
    )
    error = _dispatch_probe_writes(clamped)
    if error is not None:
        ehal_live.persist_write_error(error)
    else:
        ehal_live.clear_write_error()
    return error, clamped


def _dispatch_probe_writes(clamped: dict[str, Any]) -> EhalWriteError | None:
    from ehal.ess_fields import is_ess_pattern_b_field
    from ehal.flex_fields import flex_field_kind

    pattern_b: dict[str, float] = {}
    flex_fields: dict[str, float] = {}
    adapter_values: dict[str, Any] = {}
    for field, value in clamped.items():
        name = canonical_probe_field(field)
        if is_ess_pattern_b_field(name):
            pattern_b[name] = float(value)
            continue
        if flex_field_kind(name):
            flex_fields[name] = float(value)
            continue
        adapter_values[field] = value

    error: EhalWriteError | None = None
    if adapter_values:
        adapter = ehal_live.get_adapter()
        setpoint = build_probes_setpoint(
            adapter_values, adapter_id=str(adapter.cfg.adapter_id)
        )
        payload = {
            k: v
            for k, v in setpoint.items()
            if k not in ("schema_version", "ts", "adapter_id")
        }
        if payload:
            error = adapter.write_setpoints(setpoint)
    if error is None and pattern_b:
        error = _write_pattern_b_probes(pattern_b)
    if error is None and flex_fields:
        error = _write_flex_enable_probes(flex_fields)
    return error


def _write_pattern_b_probes(fields: dict[str, float]) -> EhalWriteError | None:
    if ehal_live.is_ha_backend():
        adapter = ehal_live.get_ha_adapter()
        writer = getattr(adapter, "write_mapped_fields", None)
        if callable(writer):
            return writer(fields)
        return adapter.write_setpoints(
            build_probes_setpoint(fields, adapter_id=str(adapter.cfg.adapter_id))
        )
    if ehal_live.is_openems_backend():
        return None
    return _write_loxone_mapped_probes(fields)


def _write_flex_enable_probes(fields: dict[str, float]) -> EhalWriteError | None:
    if ehal_live.is_ehal_network_backend():
        return None
    return _write_loxone_mapped_probes(fields)


def _marker_for_probe_field(field: str, targets: dict[str, str]) -> str:
    direct = str(targets.get(field) or "").strip()
    if direct:
        return direct
    canon = canonical_probe_field(field)
    for key, marker in targets.items():
        if canonical_probe_field(key) == canon and str(marker or "").strip():
            return str(marker).strip()
    return ""


def _loxone_probe_wire_value(field: str, value: Any) -> float:
    from integrations.loxone_adapter import (
        ehal_active_power_w_to_loxone_kw,
        ehal_limit_w_to_loxone_kw,
    )

    kind = probe_kind(field)
    if kind == FORCE_ESS_ACTIVE_POWER:
        return float(ehal_active_power_w_to_loxone_kw(float(value)))
    if kind in LOXONE_KW_WRITE_FIELDS:
        return float(ehal_limit_w_to_loxone_kw(float(value)))
    return float(value)


def _publish_id_for_probe(field: str) -> str:
    """Qualified EHAL ID for a Schreibtest probe field (plant / Pattern B / consumer)."""
    from ehal.ess_fields import parse_ess_pattern_b
    from ehal.qualified_ids import NAMESPACES, field_kind, qualified_consumer_id
    from integrations.ehal_debug_mapping import (
        PLANT_LIVE_WRITE_FIELDS,
        _consumer_type_for_qualified_id,
        _all_live_consumers,
        _consumer_is_ev,
    )

    raw = str(field or "").strip()
    if not raw:
        return ""
    if parse_ess_pattern_b(raw) or raw in PLANT_LIVE_WRITE_FIELDS:
        return raw
    ns = raw.split(".", 1)[0]
    if ns in NAMESPACES and raw.count(".") >= 2:
        return raw
    if ":" not in raw:
        return canonical_probe_field(raw)
    cid, rest = raw.split(":", 1)
    cid = cid.strip()
    kind = field_kind(rest)
    consumer: dict | None = None
    for item in _all_live_consumers():
        if str(item.get("id") or "").strip() == cid:
            consumer = item
            break
    if consumer is None:
        ctype = "ev" if kind.startswith("set_evcs_") else ""
        return qualified_consumer_id(cid, ctype, kind) if cid and kind else raw
    ctype = _consumer_type_for_qualified_id(consumer)
    if _consumer_is_ev(consumer) or kind.startswith("set_evcs_"):
        ctype = "ev"
    return qualified_consumer_id(cid, ctype, kind)


def _write_loxone_mapped_probes(fields: dict[str, Any]) -> EhalWriteError | None:
    from integrations.loxone_writes import _publish_setpoint_traced

    targets = mapped_write_targets()
    for field, value in fields.items():
        marker = _marker_for_probe_field(field, targets)
        if not marker:
            continue
        wire = _loxone_probe_wire_value(field, value)
        qid = _publish_id_for_probe(str(field))
        if not qid:
            continue
        _publish_setpoint_traced(qid, wire, io_name=marker)
    return None


def write_probe(
    field: str,
    value: Any,
    *,
    force_ess_active: bool = False,
    max_power_kw: float | None = None,
    ev_nominal_a: float | None = None,
) -> EhalWriteError | None:
    """Write one clamped probe field via the active EHAL adapter."""
    error, _clamped = write_probes(
        {field: value},
        force_ess_active=force_ess_active,
        max_power_kw=max_power_kw,
        ev_nominal_a=ev_nominal_a,
    )
    return error


def read_back(field: str) -> Any | None:
    """Best-effort echo of the written setpoint; None when no readable echo."""
    if ehal_live.is_ha_backend():
        return _read_back_ha(field)
    if ehal_live.is_openems_backend():
        return None
    return _read_back_loxone(field)


def _read_back_ha(field: str) -> Any | None:
    adapter = ehal_live.get_ha_adapter()
    targets = mapped_write_targets()
    entity_id = _marker_for_probe_field(field, targets) or str(
        adapter.cfg.entities.get(field) or ""
    ).strip()
    if not entity_id:
        return None
    payload = adapter.read_state(entity_id)
    state = payload.get("state")
    kind = probe_kind(field)
    if kind == "set_ess_mode":
        return _coerce_ess_mode_echo(state)
    if kind == "set_evcs_mode":
        return str(state or "").strip().lower() or None
    attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    unit = attrs.get("unit_of_measurement")
    try:
        return parse_ha_field_value(kind, str(state), unit=unit)
    except (TypeError, ValueError):
        try:
            return float(state)
        except (TypeError, ValueError):
            return state


def _read_back_loxone(field: str) -> Any | None:
    from integrations import loxone_client

    marker = _marker_for_probe_field(field, mapped_write_targets())
    if not marker:
        return None
    raw = loxone_client.fetch_loxone_generic_value(marker)
    if raw is None:
        return None
    kind = probe_kind(field)
    if kind == "set_ess_mode":
        return _coerce_ess_mode_echo(raw)
    if kind == "set_evcs_mode":
        try:
            code = int(float(raw))
        except (TypeError, ValueError):
            return None
        for name, val in EVCS_MODE_VALUES.items():
            if int(val) == code:
                return name
        return None
    numeric = float(raw)
    if kind in LOXONE_KW_WRITE_FIELDS:
        return numeric * 1000.0
    return numeric


def _coerce_ess_mode_echo(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        text = str(raw or "").strip().lower()
        if text in ("automatik", "auto", "0"):
            return 0
        return None


def roundtrip(
    field: str,
    value: Any,
    *,
    force_ess_active: bool = False,
    wait_s: float = DEFAULT_ROUNDTRIP_WAIT_S,
    restore: bool = True,
    max_power_kw: float | None = None,
    ev_nominal_a: float | None = None,
) -> RoundtripResult:
    """Write → wait → read-back → optional restore (single field)."""
    batch = roundtrip_batch(
        {field: value},
        force_ess_active=force_ess_active,
        wait_s=wait_s,
        restore=restore,
        max_power_kw=max_power_kw,
        ev_nominal_a=ev_nominal_a,
    )
    if batch.field_results:
        return batch.field_results[0]
    return RoundtripResult(
        status=batch.status,
        field=canonical_probe_field(field),
        written=value,
        read_back=None,
        message=batch.message,
        write_error=batch.write_error,
    )


def _batch_write_phase(
    values: dict[str, Any],
    *,
    force_ess_active: bool,
    restore: bool,
    max_power_kw: float | None,
    ev_nominal_a: float | None,
) -> dict[str, Any] | BatchRoundtripResult:
    """Silent-Gate plus Setpoint-Schreiben.

    Rückgabe: geklammerte Schreibwerte, oder ein Abbruch-``BatchRoundtripResult``
    (Silent, Clamp-Fehler, Schreibfehler).
    """
    if not writes_allowed():
        return BatchRoundtripResult(
            status=RoundtripStatus.SILENT,
            written=dict(values),
            echoes={},
            message="Silent-Modus aktiv — kein Schreibtest.",
            field_results=(),
        )
    if max_power_kw is None:
        max_power_kw = float(config.get_battery_params().get("max_power_kw") or 0.0)
    if ev_nominal_a is None:
        ev_nominal_a = default_ev_nominal_a()
    try:
        error, clamped = write_probes(
            values,
            force_ess_active=force_ess_active,
            max_power_kw=float(max_power_kw),
            ev_nominal_a=ev_nominal_a,
        )
    except WriteTestClampError as exc:
        return BatchRoundtripResult(
            status=RoundtripStatus.FAIL,
            written=dict(values),
            echoes={},
            message=str(exc),
            field_results=(),
        )

    if error is not None:
        if restore:
            restore_safe_setpoints()
        return BatchRoundtripResult(
            status=RoundtripStatus.WRITE_ERROR,
            written=clamped,
            echoes={},
            message=str(error.get("message") or error),
            field_results=(),
            write_error=error,
        )
    return clamped


def _roundtrip_read_back(field: str, written: Any) -> tuple[Any | None, RoundtripResult]:
    """Ein Feld zurücklesen und als (Echo, RoundtripResult) bewerten."""
    echo: Any | None = None
    try:
        echo = read_back(field)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Write-test read-back failed for %s: %s", field, exc)
        echo = None
    if echo is None:
        return echo, RoundtripResult(
            status=RoundtripStatus.PARTIAL,
            field=field,
            written=written,
            read_back=None,
            message=(
                f"{field}: Schreiben OK, aber kein lesbares Echo."
            ),
        )
    if values_match(written, echo):
        return echo, RoundtripResult(
            status=RoundtripStatus.PASS,
            field=field,
            written=written,
            read_back=echo,
            message=f"{field}: Roundtrip OK.",
        )
    return echo, RoundtripResult(
        status=RoundtripStatus.FAIL,
        field=field,
        written=written,
        read_back=echo,
        message=(
            f"{field}: Mismatch — geschrieben {written!r}, "
            f"gelesen {echo!r}."
        ),
    )


def _batch_overall_status(field_results: list[RoundtripResult]) -> RoundtripStatus:
    """Gesamtstatus in Vorrangfolge FAIL → PARTIAL → PASS."""
    statuses = {row.status for row in field_results}
    if RoundtripStatus.FAIL in statuses:
        return RoundtripStatus.FAIL
    if RoundtripStatus.PARTIAL in statuses:
        return RoundtripStatus.PARTIAL
    return RoundtripStatus.PASS


def roundtrip_batch(
    values: dict[str, Any],
    *,
    force_ess_active: bool = False,
    wait_s: float = DEFAULT_ROUNDTRIP_WAIT_S,
    restore: bool = True,
    max_power_kw: float | None = None,
    ev_nominal_a: float | None = None,
) -> BatchRoundtripResult:
    """Write many fields in one setpoint → wait → per-field read-back → optional restore."""
    written_or_result = _batch_write_phase(
        values,
        force_ess_active=force_ess_active,
        restore=restore,
        max_power_kw=max_power_kw,
        ev_nominal_a=ev_nominal_a,
    )
    if isinstance(written_or_result, BatchRoundtripResult):
        return written_or_result
    clamped = written_or_result

    if wait_s > 0:
        time.sleep(float(wait_s))

    field_results: list[RoundtripResult] = []
    echoes: dict[str, Any | None] = {}
    for field, written in clamped.items():
        echo, result = _roundtrip_read_back(field, written)
        echoes[field] = echo
        field_results.append(result)

    if restore:
        restore_safe_setpoints()

    parts = [row.message for row in field_results]
    return BatchRoundtripResult(
        status=_batch_overall_status(field_results),
        written=clamped,
        echoes=echoes,
        message=" · ".join(parts) if parts else "Roundtrip ohne Felder.",
        field_results=tuple(field_results),
    )


def restore_safe_setpoints() -> None:
    """Push Automatik + EVCS 0 A without re-checking Silent (caller already gated)."""
    if ehal_live.is_ehal_network_backend():
        ehal_live._push_safe_setpoints_network()
    else:
        ehal_live._push_safe_setpoints_loxone()


def looks_like_housesim() -> bool:
    """Soft hint for UI caption (no hard block)."""
    try:
        adapter_id = str(getattr(ehal_live.get_adapter().cfg, "adapter_id", "") or "")
    except (ValueError, OSError, AttributeError):
        adapter_id = str(config.get("EHAL_ADAPTER_ID") or "")
    lowered = adapter_id.lower()
    if "house_sim" in lowered or "housesim" in lowered:
        return True
    base = str(config.get("EHAL_HA_BASE_URL") or "").lower()
    return "house_sim" in base or "housesim" in base
