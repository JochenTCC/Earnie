"""Planungsfenster: Sunset-Horizont (Live) und UI sunrise→sunrise."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun

from optimizer.schedule import quarter_hour_slot_start


@dataclass(frozen=True)
class PlanningWindow:
    """MILP-Horizont: Jetzt → SA₂ (Sonnenaufgang, UI-konsistent)."""

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
class SunriseAnchors:
    """UI-Anker SA₀, SA₁, SA₂ (Sonnenaufgang, nicht Sonnenuntergang)."""

    sa0: datetime
    sa1: datetime
    sa2: datetime


@dataclass(frozen=True)
class UiChartWindow:
    """S-2-Chart-Segment: SA₀→SA₁ oder SA₁→SA₂."""

    start: datetime
    end: datetime
    sa0: datetime
    sa1: datetime
    sa2: datetime
    segment_index: int
    slot_datetimes: tuple[datetime, ...]

    @property
    def previous_sunrise(self) -> datetime:
        return self.sa0

    @property
    def next_sunrise(self) -> datetime:
        return self.sa1 if self.segment_index == 0 else self.sa2


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


def align_to_planning_timezone(moment: datetime, timezone_name: str) -> datetime:
    """Naive lokale Zeit → timezone-aware; aware → Planungszeitzone."""
    tz = _require_tz(timezone_name)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=tz)
    return moment.astimezone(tz)


def normalize_planning_hour_slot(moment: datetime, timezone_name: str) -> datetime:
    """Stunden-Slot in der Planungszeitzone (naive Einträge aus dem Log inkl.)."""
    return normalize_hour_slot(align_to_planning_timezone(moment, timezone_name))


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
    MILP-Fenster: Jetzt → SA₂ (übernächster Sonnenaufgang, UI-konsistent).

    SU₁/SU₂ = Sonnenuntergänge (Chart-Marker). SOC-Anker = erster Sonnenaufgang nach now.
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    sunset_1 = next_sunset_after(now, latitude, longitude, timezone_name)
    sunset_2 = next_sunset_after(sunset_1, latitude, longitude, timezone_name)
    sunrise_anchor = next_sunrise_after(now, latitude, longitude, timezone_name)
    anchors = compute_sunrise_anchors(now, latitude, longitude, timezone_name)
    horizon_end = anchors.sa2
    start = normalize_hour_slot(now)
    slots = hourly_slots_inclusive(start, horizon_end)
    return PlanningWindow(
        start=start,
        end=horizon_end,
        sunset_1=sunset_1,
        sunset_2=sunset_2,
        sunrise_anchor=sunrise_anchor,
        slot_datetimes=slots,
        timezone_name=timezone_name,
        latitude=latitude,
        longitude=longitude,
    )


def is_sunrise_hour(
    moment: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> bool:
    """True, wenn moment in der Stunde des heutigen Sonnenaufgangs liegt."""
    if moment.tzinfo is None:
        raise ValueError("moment muss timezone-aware sein.")
    sunrise, _ = official_sun_times(moment.date(), latitude, longitude, timezone_name)
    return normalize_hour_slot(sunrise) == normalize_hour_slot(moment)


def _shift_sunrise_anchors_back(
    anchors: SunriseAnchors,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> SunriseAnchors:
    """Verschiebt SA₀/SA₁/SA₂ um einen Sonnenaufgang-Zyklus zurück."""
    sa0_prev = previous_sunrise_before(
        anchors.sa0 - timedelta(seconds=1),
        latitude,
        longitude,
        timezone_name,
    )
    return SunriseAnchors(sa0=sa0_prev, sa1=anchors.sa0, sa2=anchors.sa1)


def compute_sunrise_anchors(
    now: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
    *,
    cycle_offset: int = 0,
) -> SunriseAnchors:
    """
    SA₀/SA₁/SA₂ für die S-2-UI.

    In der SA-Stunde: SA₀=jetzt, SA₁=morgen, SA₂=übermorgen.
    Sonst: SA₀=letzter SA, SA₁=nächster SA, SA₂=übernächster SA.
    cycle_offset verschiebt alle Anker um ganze SA-Zyklen zurück.
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    if cycle_offset < 0:
        raise ValueError(f"cycle_offset muss >= 0 sein, erhalten: {cycle_offset}.")
    anchors = _sunrise_anchors_at(now, latitude, longitude, timezone_name)
    for _ in range(cycle_offset):
        anchors = _shift_sunrise_anchors_back(
            anchors, latitude, longitude, timezone_name
        )
    return anchors


def _sunrise_anchors_at(
    moment: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
) -> SunriseAnchors:
    if is_sunrise_hour(moment, latitude, longitude, timezone_name):
        sa0 = moment
        today_sunrise, _ = official_sun_times(
            moment.date(), latitude, longitude, timezone_name
        )
        sa1 = next_sunrise_after(today_sunrise, latitude, longitude, timezone_name)
        sa2 = next_sunrise_after(sa1, latitude, longitude, timezone_name)
        return SunriseAnchors(sa0=sa0, sa1=sa1, sa2=sa2)
    sa0 = previous_sunrise_before(moment, latitude, longitude, timezone_name)
    sa1 = next_sunrise_after(moment, latitude, longitude, timezone_name)
    sa2 = next_sunrise_after(sa1, latitude, longitude, timezone_name)
    return SunriseAnchors(sa0=sa0, sa1=sa1, sa2=sa2)


def compute_ui_s2_chart_window(
    anchors: SunriseAnchors,
    segment_index: int,
) -> UiChartWindow:
    """Chart-Segment 0: SA₀→SA₁, Segment 1: SA₁→SA₂."""
    if segment_index not in (0, 1):
        raise ValueError(
            f"segment_index muss 0 oder 1 sein, erhalten: {segment_index}."
        )
    if segment_index == 0:
        start, end = anchors.sa0, anchors.sa1
    else:
        start, end = anchors.sa1, anchors.sa2
    slots = hourly_slots_inclusive(start, end)
    return UiChartWindow(
        start=start,
        end=end,
        sa0=anchors.sa0,
        sa1=anchors.sa1,
        sa2=anchors.sa2,
        segment_index=segment_index,
        slot_datetimes=slots,
    )


def compute_ui_chart_window(
    now: datetime,
    latitude: float,
    longitude: float,
    timezone_name: str,
    *,
    segment_index: int = 0,
    cycle_offset: int = 0,
) -> UiChartWindow:
    """S-2-Chart-Fenster um now (Standard: Segment SA₀→SA₁)."""
    anchors = compute_sunrise_anchors(
        now, latitude, longitude, timezone_name, cycle_offset=cycle_offset
    )
    return compute_ui_s2_chart_window(anchors, segment_index)


def compute_ui_chart_window_with_offset(
    now: datetime,
    offset_cycles: int,
    latitude: float,
    longitude: float,
    timezone_name: str,
    *,
    segment_index: int = 0,
) -> UiChartWindow:
    """Verschiebt SA-Anker um offset_cycles Zyklen zurück (Kompatibilität)."""
    return compute_ui_chart_window(
        now,
        latitude,
        longitude,
        timezone_name,
        segment_index=segment_index,
        cycle_offset=offset_cycles,
    )


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


def _row_slot_datetime(row: dict) -> datetime | None:
    slot = row.get("slot_datetime")
    if isinstance(slot, datetime):
        return normalize_hour_slot(slot)
    return None


def first_extrapolated_slot(
    slots: tuple[datetime, ...],
    sim_rows: list[dict] | None,
) -> datetime | None:
    """Erster Slot mit Preis extrapoliert == true."""
    if not sim_rows:
        return None
    by_slot = {
        slot: row
        for row in sim_rows
        if (slot := _row_slot_datetime(row)) is not None
    }
    for slot in slots:
        row = by_slot.get(slot)
        if row and bool(row.get("Preis extrapoliert")):
            return slot
    return None


def last_completed_hour_boundary(now: datetime) -> datetime:
    """Start der aktuellen vollen Stunde (= exklusives Ende des Log-Bereichs vor x:15)."""
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    return normalize_hour_slot(now)


def history_boundary_exclusive(now: datetime) -> datetime:
    """
    Exklusives Ende des Produktiv-Log-Bereichs (Spec ui-sunset2sunset v0.6 §6).

    x:00–x:14: letzte volle Stunde. Ab x:15: Beginn des laufenden Viertelstunden-Slots.
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    if now.minute < 15:
        return normalize_hour_slot(now)
    return quarter_hour_slot_start(now)


def _clip_zone_end(start: datetime, end: datetime, boundary: datetime) -> datetime:
    clipped = min(end, boundary)
    if clipped < start:
        return start
    return clipped


def ui_chart_zone_indices(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None = None,
) -> tuple[int, int, int]:
    """
    Grenz-Indizes (inkl.) für Plotly-vrect im Chart.

    Returns: (history_end, neutral_end, last_index)
    """
    zones = ui_chart_zones(now, chart, sim_rows=sim_rows)
    slots = chart.slot_datetimes
    history_end = slot_index_at_or_before(slots, zones.history.end)
    neutral_end = slot_index_at_or_before(slots, zones.live_plan.end)
    return history_end, neutral_end, len(slots) - 1


def _ui_chart_zones_sa0_sa1(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None,
    *,
    is_live_segment: bool,
    slot_datetimes: tuple[datetime, ...],
) -> UiChartZones:
    """Segment SA₀→SA₁: grau / neutral / grün (Vergangenheit ab SA₀)."""
    gray_color = "rgba(128, 128, 128, 0.18)"
    if is_live_segment:
        gray_end = history_boundary_exclusive(now)
    else:
        gray_end = chart.end + timedelta(hours=1)
    extrapolated = first_extrapolated_slot(slot_datetimes, sim_rows)
    green_color = "rgba(76, 175, 80, 0.15)"
    if is_live_segment and extrapolated is not None:
        green_start = extrapolated
    else:
        green_start = chart.end
        green_color = None
    neutral_end = _clip_zone_end(chart.start, chart.end, green_start)
    if is_live_segment:
        history_end = _clip_zone_end(chart.start, chart.end, gray_end)
        if history_end < chart.start:
            history_end = chart.start
    else:
        history_end = gray_end
    if neutral_end < history_end:
        neutral_end = history_end
    if green_start < neutral_end:
        green_start = neutral_end
    return UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=history_end,
            fill_color=gray_color if history_end > chart.start else None,
        ),
        live_plan=UiChartZone(
            label="Aktuell/Plan",
            start=history_end,
            end=neutral_end,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Vorausschau",
            start=green_start,
            end=chart.end,
            fill_color=green_color,
        ),
    )


def _ui_chart_zones_sa1_sa2(
    chart: UiChartWindow,
    sim_rows: list[dict] | None,
    *,
    slot_datetimes: tuple[datetime, ...],
) -> UiChartZones:
    """Segment SA₁→SA₂: nur neutral und grün (keine Vergangenheit)."""
    extrapolated = first_extrapolated_slot(slot_datetimes, sim_rows)
    green_color = "rgba(76, 175, 80, 0.15)"
    if extrapolated is not None:
        green_start = extrapolated
    else:
        green_start = chart.end
        green_color = None
    neutral_end = _clip_zone_end(chart.start, chart.end, green_start)
    if green_start < neutral_end:
        green_start = neutral_end
    return UiChartZones(
        history=UiChartZone(
            label="Vergangenheit",
            start=chart.start,
            end=chart.start,
            fill_color=None,
        ),
        live_plan=UiChartZone(
            label="Plan",
            start=chart.start,
            end=neutral_end,
            fill_color=None,
        ),
        forecast=UiChartZone(
            label="Vorausschau (gespiegelte Preise)",
            start=green_start,
            end=chart.end,
            fill_color=green_color,
        ),
    )


def ui_chart_zones(
    now: datetime,
    chart: UiChartWindow,
    sim_rows: list[dict] | None = None,
    *,
    is_live_segment: bool = True,
    slot_datetimes: tuple[datetime, ...] | None = None,
) -> UiChartZones:
    """
    Hintergrundzonen für den S-2-Chart.

    SA₀→SA₁: grau (Vergangenheit) · neutral · grün (extrapolierte Preise)
    SA₁→SA₂: neutral · grün (nur gespiegelte/extrapolierte Preise)

    ``slot_datetimes``: Display-Slots (15-min/1-h gemischt); Default ``chart.slot_datetimes``.
    ``is_live_segment``: False bei vergangenen SA-Zyklen (cycle_offset > 0) — volle Grauzone.
    """
    if now.tzinfo is None:
        raise ValueError("now muss timezone-aware sein.")
    slots = slot_datetimes if slot_datetimes is not None else chart.slot_datetimes
    if chart.segment_index == 1:
        return _ui_chart_zones_sa1_sa2(chart, sim_rows, slot_datetimes=slots)
    return _ui_chart_zones_sa0_sa1(
        now,
        chart,
        sim_rows,
        is_live_segment=is_live_segment,
        slot_datetimes=slots,
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
