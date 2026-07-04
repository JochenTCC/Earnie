"""Planungsfenster: Sunset-Horizont (Live) und UI sunrise→sunrise."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun


@dataclass(frozen=True)
class PlanningWindow:
    """MILP-Horizont: Jetzt → SA₁ → SA₂."""

    start: datetime
    end: datetime
    sunset_1: datetime
    sunset_2: datetime
    sunrise_anchor: datetime
    slot_datetimes: tuple[datetime, ...]
    timezone_name: str
    latitude: float
    longitude: float

    @property
    def horizon_hours(self) -> int:
        return len(self.slot_datetimes)


@dataclass(frozen=True)
class UiChartWindow:
    """Live-Chart: letzter Sonnenaufgang → nächster Sonnenaufgang."""

    start: datetime
    end: datetime
    previous_sunrise: datetime
    next_sunrise: datetime
    slot_datetimes: tuple[datetime, ...]


@dataclass(frozen=True)
class UiChartZone:
    """Eine Hintergrundzone für den Live-Chart."""

    label: str
    start: datetime
    end: datetime
    fill_color: str | None


@dataclass(frozen=True)
class UiChartZones:
    history: UiChartZone
    live_plan: UiChartZone
    forecast: UiChartZone


def normalize_hour_slot(moment: datetime) -> datetime:
    """Stunden-Slot (lokale Zeit, Minuten/Sekunden = 0)."""
    return moment.replace(minute=0, second=0, microsecond=0)


def _require_tz(timezone_name: str) -> ZoneInfo:
    if not timezone_name or not str(timezone_name).strip():
        raise ValueError(
            "timezone_name fehlt — für official Sonnenzeiten z. B. 'Europe/Vienna' angeben."
        )
    return ZoneInfo(timezone_name)


def _observer(latitude: float, longitude: float) -> Observer:
    if not (-90.0 <= latitude <= 90.0):
        raise ValueError(f"latitude muss zwischen -90 und 90 liegen, erhalten: {latitude}")
    if not (-180.0 <= longitude <= 180.0):
        raise ValueError(f"longitude muss zwischen -180 und 180 liegen, erhalten: {longitude}")
    return Observer(latitude=latitude, longitude=longitude)


def official_sun_times(
    day: date,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    """Liefert (Sonnenaufgang, Sonnenuntergang) official für den Kalendertag."""
    tz = _require_tz(timezone_name)
    observer = _observer(latitude, longitude)
    events = sun(observer, date=day, tzinfo=tz)
    return events["sunrise"], events["sunset"]


def next_sunset_after(
    moment: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> datetime:
    """Erster Sonnenuntergang strikt nach moment."""
    if moment.tzinfo is None:
        raise ValueError("moment muss timezone-aware sein.")
    day = moment.date()
    while True:
        _, sunset = official_sun_times(day, latitude, longitude, timezone_name)
        if sunset > moment:
            return sunset
        day += timedelta(days=1)


def next_sunrise_after(
    moment: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> datetime:
    """Erster Sonnenaufgang strikt nach moment."""
    if moment.tzinfo is None:
        raise ValueError("moment muss timezone-aware sein.")
    day = moment.date()
    while True:
        sunrise, _ = official_sun_times(day, latitude, longitude, timezone_name)
        if sunrise > moment:
            return sunrise
        day += timedelta(days=1)


def previous_sunrise_before(
    moment: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> datetime:
    """Letzter Sonnenaufgang am oder vor moment (exakt am SA: dieser SA)."""
    if moment.tzinfo is None:
        raise ValueError("moment muss timezone-aware sein.")
    day = moment.date()
    while True:
        sunrise, _ = official_sun_times(day, latitude, longitude, timezone_name)
        if sunrise <= moment:
            return sunrise
        day -= timedelta(days=1)


def hourly_slots_inclusive(start: datetime, end: datetime) -> tuple[datetime, ...]:
    """Stündliche Slots von floor(start) bis floor(end) einschließlich."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start und end müssen timezone-aware sein.")
    if end < start:
        raise ValueError(f"end ({end}) liegt vor start ({start}).")
    slot = normalize_hour_slot(start)
    end_slot = normalize_hour_slot(end)
    slots: list[datetime] = []
    while slot <= end_slot:
        slots.append(slot)
        slot += timedelta(hours=1)
    if not slots:
        raise ValueError(f"Keine Stunden-Slots zwischen {start} und {end}.")
    return tuple(slots)


def compute_planning_window(
    now: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> PlanningWindow:
    """
    MILP-Fenster: Jetzt → SA₁ + SA₁ → SA₂.

    SA₁ = erster kommender Sonnenuntergang; SA₂ = nächster Sonnenuntergang danach.
    sunrise_anchor = erster Sonnenaufgang nach now (SOC_min-Randbedingung).
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    sunset_1 = next_sunset_after(now, latitude, longitude, timezone_name)
    sunset_2 = next_sunset_after(sunset_1, latitude, longitude, timezone_name)
    sunrise_anchor = next_sunrise_after(now, latitude, longitude, timezone_name)
    start = normalize_hour_slot(now)
    slots = hourly_slots_inclusive(start, sunset_2)
    return PlanningWindow(
        start=start,
        end=sunset_2,
        sunset_1=sunset_1,
        sunset_2=sunset_2,
        sunrise_anchor=sunrise_anchor,
        slot_datetimes=slots,
        timezone_name=timezone_name,
        latitude=latitude,
        longitude=longitude,
    )


def compute_ui_chart_window(
    now: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> UiChartWindow:
    """Chart-Fenster sunrise→sunrise um now."""
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    prev_sunrise = previous_sunrise_before(now, latitude, longitude, timezone_name)
    next_sunrise = next_sunrise_after(now, latitude, longitude, timezone_name)
    slots = hourly_slots_inclusive(prev_sunrise, next_sunrise)
    return UiChartWindow(
        start=prev_sunrise,
        end=next_sunrise,
        previous_sunrise=prev_sunrise,
        next_sunrise=next_sunrise,
        slot_datetimes=slots,
    )


def compute_ui_chart_window_with_offset(
    now: datetime,
    offset_cycles: int,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> UiChartWindow:
    """Verschiebt das UI-Fenster um offset_cycles Sonnenaufgang→Sonnenaufgang-Zyklen zurück."""
    if offset_cycles < 0:
        raise ValueError(f"offset_cycles muss >= 0 sein, erhalten: {offset_cycles}.")
    moment = now
    for _ in range(offset_cycles):
        prev_sunrise = previous_sunrise_before(moment, latitude, longitude, timezone_name)
        moment = prev_sunrise - timedelta(seconds=1)
    return compute_ui_chart_window(moment, latitude, longitude, timezone_name)


def slot_index_at_or_before(slots: tuple[datetime, ...], moment: datetime) -> int:
    """Index des letzten Slots mit slot <= moment (normalisiert auf volle Stunde)."""
    if not slots:
        raise ValueError("slots darf nicht leer sein.")
    target = normalize_hour_slot(moment)
    if target in slots:
        return slots.index(target)
    for index in range(len(slots) - 1, -1, -1):
        if slots[index] <= target:
            return index
    return 0


def ui_chart_zone_indices(
    now: datetime,
    chart: UiChartWindow,
) -> tuple[int, int, int]:
    """
    Grenz-Indizes (inkl.) für Plotly-vrect im Chart.

    Returns: (history_end, live_plan_end, last_index)
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    slots = chart.slot_datetimes
    now_idx = slot_index_at_or_before(slots, now)
    sunrise_idx = slot_index_at_or_before(slots, chart.next_sunrise)
    return now_idx, sunrise_idx, len(slots) - 1


def ui_chart_zones(
    now: datetime,
    chart: UiChartWindow,
) -> UiChartZones:
    """
    Hintergrundzonen für den Live-Chart.

    - Vergangenheit (grau): letzter SA → jetzt
    - Live/Plan (neutral): jetzt → nächster SA (SOC-Anker)
    - Vorausschau (grün): nächster SA → Chart-Ende
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    sunrise_anchor = chart.next_sunrise
    if now < chart.start or now > chart.end:
        raise ValueError(
            f"now ({now}) liegt außerhalb des Chart-Fensters "
            f"[{chart.start}, {chart.end}]."
        )
    return UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=now,
            fill_color="rgba(128, 128, 128, 0.18)",
        ),
        live_plan=UiChartZone(
            label="Live/Plan",
            start=now,
            end=sunrise_anchor,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Vorausschau",
            start=sunrise_anchor,
            end=chart.end,
            fill_color="rgba(76, 175, 80, 0.15)",
        ),
    )


def sunrise_anchor_slot_index(window: PlanningWindow) -> int:
    """Index des SOC-Anker-Sonnenaufgangs in slot_datetimes."""
    anchor_slot = normalize_hour_slot(window.sunrise_anchor)
    try:
        return window.slot_datetimes.index(anchor_slot)
    except ValueError as exc:
        raise ValueError(
            f"Sonnenaufgang-Slot {anchor_slot!r} fehlt in der Planungsmatrix "
            f"({window.start} .. {window.end})."
        ) from exc
