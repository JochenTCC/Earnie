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
    probe_value_bounds,
    values_match,
)
from integrations.ha_adapter import parse_ha_field_value
from integrations.loxone_adapter import EVCS_MODE_VALUES
from integrations.loxone_ehal_mapping import SETPOINT_FIELDS

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
    """Canonical setpoint field → backend address (entity / Merker / channel label)."""
    if ehal_live.is_ha_backend():
        adapter = ehal_live.get_ha_adapter()
        return ha_setpoint_mapping(dict(adapter.cfg.entities))
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


def _loxone_mapped_targets() -> dict[str, str]:
    raw = loxone_write_field_to_io()
    out: dict[str, str] = {}
    for field, io_name in raw.items():
        canon = canonical_probe_field(field)
        if canon not in SETPOINT_FIELDS:
            continue
        if canon not in out and str(io_name or "").strip():
            out[canon] = str(io_name).strip()
    return out


def allowed_probe_fields(*, force_ess_active: bool = False) -> list[str]:
    """Mapped safe-probe fields; include active power only when force unlocked."""
    mapped = mapped_write_targets()
    fields: list[str] = []
    if force_ess_active and FORCE_ESS_ACTIVE_POWER in mapped:
        fields.append(FORCE_ESS_ACTIVE_POWER)
    for field in SAFE_PROBE_FIELDS:
        if field in mapped:
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
    ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    doc: dict[str, Any] = {
        "schema_version": EHAL_SCHEMA_VERSION,
        "ts": ts,
        "adapter_id": adapter_id,
    }
    for field, value in values.items():
        doc[canonical_probe_field(field)] = value
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
        canon = canonical_probe_field(field)
        out[canon] = clamp_probe_value(
            canon,
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
    """Write multiple clamped probe fields in one setpoint document."""
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
    adapter = ehal_live.get_adapter()
    setpoint = build_probes_setpoint(
        clamped, adapter_id=str(adapter.cfg.adapter_id)
    )
    error = adapter.write_setpoints(setpoint)
    if error is not None:
        ehal_live.persist_write_error(error)
    else:
        ehal_live.clear_write_error()
    return error, clamped


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
    canon = canonical_probe_field(field)
    if ehal_live.is_ha_backend():
        return _read_back_ha(canon)
    if ehal_live.is_openems_backend():
        return None
    return _read_back_loxone(canon)


def _read_back_ha(field: str) -> Any | None:
    adapter = ehal_live.get_ha_adapter()
    entity_id = str(adapter.cfg.entities.get(field) or "").strip()
    if not entity_id:
        return None
    payload = adapter.read_state(entity_id)
    state = payload.get("state")
    if field == "set_ess_mode":
        return _coerce_ess_mode_echo(state)
    if field == "set_evcs_mode":
        return str(state or "").strip().lower() or None
    attrs = payload.get("attributes") if isinstance(payload.get("attributes"), dict) else {}
    unit = attrs.get("unit_of_measurement")
    try:
        return parse_ha_field_value(field, str(state), unit=unit)
    except (TypeError, ValueError):
        try:
            return float(state)
        except (TypeError, ValueError):
            return state


def _read_back_loxone(field: str) -> Any | None:
    from integrations import loxone_client

    targets = mapped_write_targets()
    marker = str(targets.get(field) or "").strip()
    if not marker:
        return None
    raw = loxone_client.fetch_loxone_generic_value(marker)
    if raw is None:
        return None
    if field == "set_ess_mode":
        return _coerce_ess_mode_echo(raw)
    if field == "set_evcs_mode":
        try:
            code = int(float(raw))
        except (TypeError, ValueError):
            return None
        for name, val in EVCS_MODE_VALUES.items():
            if int(val) == code:
                return name
        return None
    numeric = float(raw)
    if field in LOXONE_KW_WRITE_FIELDS:
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
