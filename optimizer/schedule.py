"""Viertelstunden-Takt für Live-Optimierung (main.py / app.py)."""
from __future__ import annotations

from datetime import datetime, timedelta

QUARTER_HOUR_MINUTES = 15
QUARTER_HOUR_SECONDS = QUARTER_HOUR_MINUTES * 60
# Wartezeit app.py auf main.py pro Viertelstunden-Slot: 15 s, dann ggf. 15 s Grace, danach Fallback.
APP_MAIN_SYNC_INITIAL_WAIT_SECONDS = 15
APP_MAIN_SYNC_EXTRA_GRACE_SECONDS = 15
APP_MAIN_SYNC_MAX_WAIT_SECONDS = (
    APP_MAIN_SYNC_INITIAL_WAIT_SECONDS + APP_MAIN_SYNC_EXTRA_GRACE_SECONDS
)
# Persistierter Cockpit-Snapshot: Anzeige ohne main.py bis zu dieser Altersschwelle.
PERSISTED_DISPLAY_MAX_AGE_SECONDS = 3600
# Legacy-Namen (Doku/Kompatibilität)
APP_REFRESH_DELAY_SECONDS = APP_MAIN_SYNC_INITIAL_WAIT_SECONDS
APP_MAIN_SYNC_GRACE_SECONDS = APP_MAIN_SYNC_EXTRA_GRACE_SECONDS


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


def seconds_until_main_py_sync_ready(
    main_completed_at: str | None,
    now: datetime | None = None,
) -> float:
    """Sekunden bis app.py auf main.py wartet (0 = bereit oder Fallback-Zeit abgelaufen)."""
    if completed_at_in_current_slot(main_completed_at, now):
        return 0.0
    since_start = seconds_since_slot_start(now)
    if since_start >= APP_MAIN_SYNC_MAX_WAIT_SECONDS:
        return 0.0
    return max(0.0, APP_MAIN_SYNC_MAX_WAIT_SECONDS - since_start)


def seconds_until_app_refresh_ready(now: datetime | None = None) -> float:
    """Alias für Countdown: verbleibende Sync-Wartezeit ohne run_state (Legacy-Name)."""
    return seconds_until_main_py_sync_ready(None, now)


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


def sync_ui_countdown_seconds(
    main_completed_at: str | None,
    poll_sec: int,
    now: datetime | None = None,
) -> int:
    """Sekunden bis zum nächsten erwarteten UI-Abgleich (Anzeige, nicht Fallback-Obergrenze)."""
    if completed_at_in_current_slot(main_completed_at, now):
        return 0
    fallback_remaining = int(seconds_until_main_py_sync_ready(main_completed_at, now))
    if fallback_remaining <= 0:
        return 0
    return max(1, min(int(poll_sec), fallback_remaining))


def is_persisted_display_fresh(
    completed_at: str | None,
    now: datetime | None = None,
    *,
    max_age_sec: int = PERSISTED_DISPLAY_MAX_AGE_SECONDS,
) -> bool:
    """True, wenn ein persistierter Anzeige-Snapshot noch nutzbar ist."""
    if not completed_at:
        return False
    try:
        completed = datetime.fromisoformat(str(completed_at))
    except ValueError:
        return False
    dt = _normalize_now(now)
    age = (dt - completed).total_seconds()
    return 0 <= age <= max_age_sec


def snapshot_age_seconds(
    completed_at: str | None,
    now: datetime | None = None,
) -> float | None:
    """Alter eines Snapshots in Sekunden; None wenn Zeitstempel fehlt/ungültig."""
    if not completed_at:
        return None
    try:
        completed = datetime.fromisoformat(str(completed_at))
    except ValueError:
        return None
    return max(0.0, (_normalize_now(now) - completed).total_seconds())


def live_simulation_readiness(
    main_completed_at: str | None,
    now: datetime | None = None,
    *,
    poll_sec: int = 15,
    persisted_completed_at: str | None = None,
) -> tuple[bool, str, int, int, bool]:
    """
    Steuert, wann app.py den Cockpit-Snapshot anzeigen darf.

    Rückgabe: (bereit, grund, ui_retry_sekunden, sync_warte_sekunden, persisted_fresh)
    grund: main_synced | wait_main | main_down — kein automatischer UI-MILP-Fallback mehr.
    """
    display_ts = persisted_completed_at or main_completed_at
    persisted_fresh = is_persisted_display_fresh(display_ts, now)

    if completed_at_in_current_slot(main_completed_at, now):
        return True, "main_synced", 0, 0, True

    sync_wait_sec = int(seconds_until_main_py_sync_ready(main_completed_at, now))
    if sync_wait_sec > 0:
        ui_retry = sync_ui_countdown_seconds(main_completed_at, poll_sec, now)
        return False, "wait_main", ui_retry, sync_wait_sec, persisted_fresh

    return True, "main_down", 0, 0, persisted_fresh


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
