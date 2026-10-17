"""Write-side rows of the Loxone debug view (split from loxone_debug_rows)."""
from __future__ import annotations

from ui.loxone_debug_rows_ref import live

from typing import Any
from integrations import ehal_live
from ui.loxone_debug import (
    _network_write_mapping,
)
from integrations.ehal_debug_mapping import expected_live_write_fields, is_live_write_field, mapping_or_dash, ordered_union, resolve_loxone_write_field
from ui.ehal_unit_display import live_write_pair


_DASH = "—"


def _live_backend() -> str:
    if ehal_live.is_ha_backend():
        return "ha"
    if ehal_live.is_ehal_network_backend():
        return "openems"
    return "loxone"


def _network_display_backend(backend: str | None = None) -> str:
    """HA/OpenEMS conversion rules for telemetry / ehal_writes tables."""
    hub = backend or _live_backend()
    return "ha" if hub == "loxone" else hub


def _enrich_write_row(
    row: dict[str, str],
    *,
    backend: str,
    value_space: str,
    hub_unit_hint: str | None = None,
) -> dict[str, str]:
    """Normalize Wert to EHAL; add Wert (Hub)."""
    raw = row.get("Wert", "")
    if not str(raw).strip():
        return {
            "EHAL-Feld": row.get("EHAL-Feld", ""),
            "Mapping": row.get("Mapping", ""),
            "Wert": "",
            "Wert (Hub)": "",
            "Erfolg": row.get("Erfolg", ""),
            "Gesendet um": row.get("Gesendet um", ""),
            "Meldung": row.get("Meldung", ""),
        }
    ehal, hub = live_write_pair(
        row.get("EHAL-Feld", ""),
        backend,  # type: ignore[arg-type]
        raw,
        value_space=value_space,  # type: ignore[arg-type]
        hub_unit_hint=hub_unit_hint,
    )
    return {
        "EHAL-Feld": row.get("EHAL-Feld", ""),
        "Mapping": row.get("Mapping", ""),
        "Wert": ehal,
        "Wert (Hub)": hub,
        "Erfolg": row.get("Erfolg", ""),
        "Gesendet um": row.get("Gesendet um", ""),
        "Meldung": row.get("Meldung", ""),
    }


def _write_row(
    *,
    field: str,
    mapping: str,
    value: str,
    success: str,
    written_at: str,
    message: str,
    backend: str = "loxone",
    value_space: str = "hub",
    hub_unit_hint: str | None = None,
) -> dict[str, str]:
    return _enrich_write_row(
        {
            "EHAL-Feld": field,
            "Mapping": mapping,
            "Wert": value,
            "Erfolg": success,
            "Gesendet um": written_at,
            "Meldung": message,
        },
        backend=backend,
        value_space=value_space,
        hub_unit_hint=hub_unit_hint,
    )


def build_write_rows_from_trace(
    writes: list[dict[str, Any]],
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    index = live.build_loxone_setpoint_io_index()
    field_to_io = live.loxone_write_field_to_io()
    by_field: dict[str, dict[str, Any]] = {}
    for entry in writes:
        io_name = str(entry.get("io_name") or "").strip()
        field = resolve_loxone_write_field(io_name, index)
        if not is_live_write_field(field):
            continue
        by_field[field] = entry
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=False),
        list(by_field),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        entry = by_field.get(field)
        configured = str(field_to_io.get(field) or "").strip()
        if entry is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=configured,
                    value="",
                    success="",
                    written_at="",
                    message="" if not configured else "Nicht im letzten Lauf",
                    backend="loxone",
                    value_space="hub",
                )
            )
            continue
        io_name = str(entry.get("io_name") or "").strip() or configured
        rows.append(
            _write_row(
                field=field,
                mapping=configured or io_name,
                value=str(entry.get("value", "")),
                success=_success_label(entry),
                written_at=str(entry.get("written_at") or ""),
                message="",
                backend="loxone",
                value_space="hub",
            )
        )
    return rows


def _success_label(entry: dict[str, Any]) -> str:
    if entry.get("skipped"):
        return "Übersprungen"
    return "Ja" if entry.get("success") else "Nein"


def build_ehal_write_rows(
    writes: list[dict[str, Any]],
    *,
    mapping: dict[str, str] | None = None,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    source = mapping if mapping is not None else _network_write_mapping()
    write_entries = list(writes)
    if expected_fields is None and ehal_live.is_ha_backend():
        from integrations.ehal_debug_mapping import (
            expand_ha_writes_for_live,
            expected_live_write_fields,
        )
        from ui.house_config_io import load_house_profiles

        house = load_house_profiles()
        write_entries = expand_ha_writes_for_live(write_entries, house)
        expected_fields = expected_live_write_fields(network_backend=False)
    by_field: dict[str, dict[str, Any]] = {}
    for entry in write_entries:
        field = str(entry.get("field") or "").strip()
        if not is_live_write_field(field):
            continue
        by_field[field] = entry
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=True),
        list(by_field),
    )
    hub = _network_display_backend()
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        mapped = mapping_or_dash(source, field)
        entry = by_field.get(field)
        if entry is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=mapped,
                    value="",
                    success="",
                    written_at="",
                    message="" if not mapped else "Nicht im letzten Lauf",
                    backend=hub,
                    value_space="ehal",
                )
            )
            continue
        rows.append(
            _write_row(
                field=field,
                mapping=mapped,
                value=str(entry.get("value", "")),
                success=_success_label(entry),
                written_at=str(entry.get("written_at") or ""),
                message=str(entry.get("message") or ""),
                backend=hub,
                value_space="ehal",
            )
        )
    return rows


def build_intended_write_rows(
    loxone_sent: dict[str, float],
    completed_at: str,
    *,
    expected_fields: list[str] | None = None,
) -> list[dict[str, str]]:
    index = live.build_loxone_setpoint_io_index()
    field_to_io = live.loxone_write_field_to_io()
    by_field: dict[str, tuple[str, float]] = {}
    for io_name, value in loxone_sent.items():
        field = resolve_loxone_write_field(str(io_name), index)
        if not is_live_write_field(field):
            continue
        by_field[field] = (str(io_name), value)
    ordered = ordered_union(
        expected_fields
        if expected_fields is not None
        else expected_live_write_fields(network_backend=False),
        list(by_field),
    )
    rows: list[dict[str, str]] = []
    for field in ordered:
        if not is_live_write_field(field):
            continue
        configured = str(field_to_io.get(field) or "").strip()
        found = by_field.get(field)
        if found is None:
            rows.append(
                _write_row(
                    field=field,
                    mapping=configured,
                    value="",
                    success="",
                    written_at="",
                    message="" if not configured else "Nicht im letzten Lauf",
                    backend="loxone",
                    value_space="hub",
                )
            )
            continue
        io_name, value = found
        rows.append(
            _write_row(
                field=field,
                mapping=configured or io_name,
                value=str(value),
                success="Nein",
                written_at=completed_at,
                message="Nicht gesendet (Silent-Modus)",
                backend="loxone",
                value_space="hub",
            )
        )
    return rows


def write_summary_from_rows(rows: list[dict[str, str]]) -> str:
    """Summary for Live-Schreiben: count only rows shown with a write attempt."""
    attempted = [row for row in rows if row.get("Erfolg") in ("Ja", "Nein")]
    if not attempted:
        return "Keine Schreibvorgänge erfasst."
    ok = sum(1 for row in attempted if row.get("Erfolg") == "Ja")
    return f"{ok}/{len(attempted)} Schreibvorgänge erfolgreich"
