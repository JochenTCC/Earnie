"""Viertelstunden-Takt für Live-Optimierung (main.py / app.py)."""
from __future__ import annotations

from datetime import datetime, timedelta

QUARTER_HOUR_MINUTES = 15
QUARTER_HOUR_SECONDS = QUARTER_HOUR_MINUTES * 60
# app.py wartet nach Slot-Start, damit main.py run_state schreiben kann
APP_REFRESH_DELAY_SECONDS = 60
# Zusätzliche Wartezeit, falls main.py etwas länger braucht
APP_MAIN_SYNC_GRACE_SECONDS = 120


def _normalize_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now()
    return now


def optimization_interval_seconds() -> int:
    """Dauer eines Optimierungsintervalls in Sekunden (fest 15 Minuten)."""
    return QUARTER_HOUR_SECONDS


def optimization_interval_hours() -> float:
    """Dauer eines Optimierungsintervalls in Stunden (fest 0,25 h)."""
    return QUARTER_HOUR_SECONDS / 3600.0


def quarter_hour_slot_start(now: datetime | None = None) -> datetime:
    """Beginn des aktuellen 15-Minuten-Slots."""
    dt = _normalize_now(now)
    quarter_minute = (dt.minute // QUARTER_HOUR_MINUTES) * QUARTER_HOUR_MINUTES
    return dt.replace(minute=quarter_minute, second=0, microsecond=0)


def quarter_hour_slot_key(now: datetime | None = None) -> str:
    """Eindeutiger Schlüssel für den aktuellen 15-Minuten-Slot (z. B. '2026-06-21T10:15')."""
    return quarter_hour_slot_start(now).strftime("%Y-%m-%dT%H:%M")


def seconds_since_slot_start(now: datetime | None = None) -> float:
    """Sekunden seit Beginn des aktuellen Viertelstunden-Slots."""
    dt = _normalize_now(now)
    return (dt - quarter_hour_slot_start(dt)).total_seconds()


def seconds_until_app_refresh_ready(now: datetime | None = None) -> float:
    """Sekunden bis app.py nach Slot-Wechsel aktualisieren soll (Abstand zu main.py)."""
    return max(0.0, APP_REFRESH_DELAY_SECONDS - seconds_since_slot_start(now))


def completed_at_in_current_slot(completed_at: str | None, now: datetime | None = None) -> bool:
    """True, wenn main.py den aktuellen Viertelstunden-Slot abgeschlossen hat."""
    if not completed_at:
        return False
    try:
        completed = datetime.fromisoformat(str(completed_at))
    except ValueError:
        return False
    slot_start = quarter_hour_slot_start(now)
    slot_end = slot_start + timedelta(seconds=QUARTER_HOUR_SECONDS)
    return slot_start <= completed < slot_end


def live_simulation_readiness(
    main_completed_at: str | None,
    now: datetime | None = None,
) -> tuple[bool, str, int]:
    """
    Steuert, wann app.py die Live-Simulation neu berechnet.

    Rückgabe: (bereit, grund, warte_sekunden)
    """
    wait_delay = int(seconds_until_app_refresh_ready(now))
    if wait_delay > 0:
        return False, "delay", wait_delay

    if completed_at_in_current_slot(main_completed_at, now):
        return True, "main_synced", 0

    since_start = seconds_since_slot_start(now)
    if since_start < APP_REFRESH_DELAY_SECONDS + APP_MAIN_SYNC_GRACE_SECONDS:
        return False, "wait_main", max(1, int(
            APP_REFRESH_DELAY_SECONDS + APP_MAIN_SYNC_GRACE_SECONDS - since_start
        ))

    return True, "fallback", 0


def seconds_until_next_quarter_hour(now: datetime | None = None) -> float:
    """Sekunden bis zur nächsten Viertelstunde (…:00, :15, :30, :45)."""
    dt = _normalize_now(now)
    minute_in_quarter = dt.minute % QUARTER_HOUR_MINUTES
    seconds_into_quarter = (
        minute_in_quarter * 60 + dt.second + dt.microsecond / 1_000_000
    )
    return QUARTER_HOUR_SECONDS - seconds_into_quarter


def next_quarter_hour_datetime(now: datetime | None = None) -> datetime:
    """Zeitpunkt der nächsten Viertelstunde."""
    dt = _normalize_now(now)
    return dt + timedelta(seconds=seconds_until_next_quarter_hour(dt))
