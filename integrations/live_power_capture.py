"""Debug-dump snapshot of the Live power read (same path as the Live Sankey).

The dump stores ``live_power`` exactly as ``ehal_live.read_live_power_kw`` returns
it (kW; grid ``+`` = import, battery ``+`` = discharge) and, next to it, why the
read failed and the push-inbox state of every power-flow signal at capture time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ehal.qualified_ids import field_kind

# Signals that feed the Live power dict (plant grid, ESS, inverter / PV production).
POWER_FLOW_KINDS: frozenset[str] = frozenset(
    {
        "sens_grid_power_active",
        "sens_ess_power",
        "sens_inv_power_pv",
        "sens_pv_production_active",
        "sens_power_consumers",
    }
)

PUSH_BACKENDS: frozenset[str] = frozenset({"loxone", "ha"})


def _bound_power_flow_ids() -> set[str]:
    from ehal.loxone_push_source import get_ehal_index

    return {eid for eid in get_ehal_index() if field_kind(eid) in POWER_FLOW_KINDS}


def push_signal_status(*, now: datetime | None = None) -> list[dict[str, Any]]:
    """Push-inbox state per power-flow signal (bound or received), without side effects.

    Uses ``derive_state`` (pure) instead of ``read_push_value`` so the capture does
    not touch the last-known hold or the replay recorder.
    """
    from runtime_store import ehal_push_inbox as inbox

    ref = now if now is not None else datetime.now(timezone.utc)
    signals = inbox.memory_snapshot()
    link = inbox.link_alive(signals, now=ref)
    ids = _bound_power_flow_ids() | {
        eid for eid in signals if field_kind(eid) in POWER_FLOW_KINDS
    }
    rows: list[dict[str, Any]] = []
    for eid in sorted(ids):
        row = signals.get(eid)
        state, value = inbox.derive_state(eid, row, link=link, now=ref)
        rows.append(
            {
                "ehal_id": eid,
                "state": state,
                "value": value,
                "raw_value": row.get("value") if isinstance(row, dict) else None,
                "last_ts": row.get("last_ts") if isinstance(row, dict) else None,
                "age_s": inbox.age_seconds(row, now=ref) if isinstance(row, dict) else None,
            }
        )
    return rows


def capture_live_power(*, now: datetime | None = None) -> dict[str, Any]:
    """``{"live_power", "live_power_capture"}`` for ``manifest.chart``.

    ``live_power`` is ``None`` only when the EHAL read failed; the error text is
    then in ``live_power_capture.error``.
    """
    from integrations import ehal_live
    from runtime_store.ehal_setup import active_ehal_backend

    ref = now if now is not None else datetime.now(timezone.utc)
    backend = active_ehal_backend()
    power: dict[str, float] | None = None
    error: str | None = None
    try:
        power = ehal_live.read_live_power_kw_strict()
    except ehal_live.LIVE_POWER_READ_ERRORS as exc:
        error = f"{type(exc).__name__}: {exc}"
    push_signals: list[dict[str, Any]] | None = None
    push_error: str | None = None
    if backend in PUSH_BACKENDS:
        try:
            push_signals = push_signal_status(now=ref)
        except (OSError, ValueError) as exc:
            push_error = f"{type(exc).__name__}: {exc}"
    meta: dict[str, Any] = {
        "source": "ehal_live.read_live_power_kw",
        "read_at": ref.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backend": backend,
        "error": error,
        # None for pull backends (OpenEMS) or when push_signals_error is set.
        "push_signals": push_signals,
        "push_signals_error": push_error,
    }
    return {"live_power": power, "live_power_capture": meta}
