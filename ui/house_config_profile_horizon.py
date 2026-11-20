"""House-profile section „Horizont“ (SUSI P3a): manual horizon as 16 draggable bars, north to north.

The values belong to the house profile (``horizon_source``, ``horizon``). Switch off: the
list stays stored with ``horizon_source: none`` and is not applied. A profile that never had
a horizon gets no field at all.
"""
from __future__ import annotations

from datetime import date

import streamlit as st

from data.solar_horizon import (
    HORIZON_KEY,
    HORIZON_SOURCE_KEY,
    MAX_ELEVATION_DEG,
    SOURCE_MANUAL,
    SOURCE_NONE,
    HorizonProfile,
    sun_path,
    wrap_azimuth,
)
from ui.form_layout import labeled_checkbox
from ui.horizon_bars_component import horizon_bars
from ui.house_config_profile_session import _scoped_key

# Clockwise from north; azimuth 0° = south, east negative (as for the PV fields).
DIRECTION_LABELS: tuple[str, ...] = (
    "N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)
DIRECTION_STEP_DEG = 360.0 / len(DIRECTION_LABELS)
DIRECTION_AZIMUTHS: tuple[float, ...] = tuple(
    -180.0 + index * DIRECTION_STEP_DEG for index in range(len(DIRECTION_LABELS))
)
_SUN_DAYS: tuple[tuple[str, int, int, str], ...] = (
    ("21. Juni", 6, 21, "#E69F00"),
    ("Tagundnachtgleiche", 3, 20, "#009E73"),
    ("21. Dezember", 12, 21, "#0072B2"),
)


def horizon_enabled_key(session_scope: str) -> str:
    return _scoped_key(session_scope, "house_horizon_enabled")


def horizon_bars_key(session_scope: str) -> str:
    """Key of the bar editor. Streamlit forbids ``__`` in a component key, so not ``_scoped_key``."""
    return f"house-horizon-bars-{session_scope}".replace("__", "_-")


def _stored_profile(existing: dict) -> HorizonProfile | None:
    points = existing.get(HORIZON_KEY) if isinstance(existing, dict) else None
    if not points:
        return None
    return HorizonProfile(
        points=tuple(
            sorted((wrap_azimuth(p["azimuth_deg"]), float(p["elevation_deg"])) for p in points)
        )
    )


def _on_grid(stored: HorizonProfile) -> bool:
    return tuple(azimuth for azimuth, _elevation in stored.points) == DIRECTION_AZIMUTHS


@st.cache_data(show_spinner=False, max_entries=16)
def _sun_paths(latitude: float, longitude: float, year: int) -> dict[str, list[tuple[float, float]]]:
    return {
        label: sun_path(latitude, longitude, date(year, month, day))
        for label, month, day, _color in _SUN_DAYS
    }


def compass_deg(azimuth_deg: float) -> float:
    """Position on the chart axis (0° = north, clockwise) of a stored azimuth (0° = south)."""
    return (float(azimuth_deg) + 180.0) % 360.0


def azimuth_label(azimuth_deg: float) -> str:
    """Azimuth as for the PV fields (0° = south, east negative); north is both ends."""
    if abs(azimuth_deg) == 180.0:
        return "±180°"
    return f"{azimuth_deg:g}°".replace(".", ",")


def active_directions(paths: dict[str, list[tuple[float, float]]]) -> list[bool]:
    """Directions the sun can reach: within one step of a sun azimuth on one of the days.

    The neighbour outside the sun's range is needed for the interpolation up to sunrise and
    sunset. The days hold both solstices, so the widest range of either hemisphere is covered.
    """
    sun_azimuths = [azimuth for path in paths.values() for azimuth, _elevation in path]

    def _near(direction: float) -> bool:
        return any(
            abs((azimuth - direction + 180.0) % 360.0 - 180.0) < DIRECTION_STEP_DEG
            for azimuth in sun_azimuths
        )

    return [_near(direction) for direction in DIRECTION_AZIMUTHS]


def seed_elevations(stored: HorizonProfile | None, active: list[bool]) -> list[float]:
    """Start values of the 16 bars: the stored horizon on the grid, 0° where the sun never is."""
    if stored is None:
        return [0.0] * len(DIRECTION_AZIMUTHS)
    return [
        round(stored.elevation_at(azimuth), 1) if on else 0.0
        for azimuth, on in zip(DIRECTION_AZIMUTHS, active)
    ]


def dropped_directions(stored: HorizonProfile | None, active: list[bool]) -> list[str]:
    """Labels of the directions with a stored elevation that the sun never reaches."""
    if stored is None:
        return []
    return [
        label
        for label, azimuth, on in zip(DIRECTION_LABELS, DIRECTION_AZIMUTHS, active)
        if not on and stored.elevation_at(azimuth) > 0.0
    ]


def checked_elevations(raw: list[float], active: list[bool]) -> list[float]:
    """The editor's values as stored: one per direction, 0–90°, 0° outside the sun's range."""
    if len(raw) != len(DIRECTION_AZIMUTHS):
        raise ValueError(
            f"Horizon editor returned {len(raw)} values, expected {len(DIRECTION_AZIMUTHS)}."
        )
    for value in raw:
        if not 0.0 <= float(value) <= MAX_ELEVATION_DEG:
            raise ValueError(f"Horizon editor returned an elevation out of range: {value!r}.")
    return [float(value) if on else 0.0 for value, on in zip(raw, active)]


def _chart_paths(paths: dict[str, list[tuple[float, float]]]) -> list[dict]:
    return [
        {
            "label": f"Sonne {label}",
            "color": color,
            "points": sorted(
                (round(compass_deg(azimuth), 2), round(elevation, 2))
                for azimuth, elevation in paths[label]
            ),
        }
        for label, _month, _day, color in _SUN_DAYS
    ]


def render_horizon_section(
    existing: dict, *, session_scope: str, latitude: float, longitude: float
) -> dict:
    """The profile's horizon fields from the form (empty dict: the profile has no horizon)."""
    stored = _stored_profile(existing)
    stored_on = bool(existing.get(HORIZON_SOURCE_KEY) == SOURCE_MANUAL) if existing else False
    enabled = bool(
        labeled_checkbox(
            "Horizont berücksichtigen",
            value=stored_on,
            key=horizon_enabled_key(session_scope),
            help=(
                "Ein: Steht die Sonne hinter Bergen, Nachbarhäusern oder Bäumen, entfällt die "
                "direkte Einstrahlung auf PV, Kollektor und Fenster; das diffuse Licht bleibt. "
                "Das ändert Jahresmodell, Szenarien-Explorer und die PV-Prognose. "
                "forecast.solar ersetzt damit sein eigenes Gelände: auch entfernte Berge "
                "eintragen."
            ),
        )
    )
    if not enabled:
        if stored is None:
            return {}
        # Kept for the next time the switch is turned on.
        return {HORIZON_SOURCE_KEY: SOURCE_NONE, HORIZON_KEY: stored.as_list()}
    paths = _sun_paths(round(float(latitude), 3), round(float(longitude), 3), date.today().year)
    active = active_directions(paths)
    with st.expander("Horizont in 16 Richtungen", expanded=True):
        st.caption(
            "Höhenwinkel des Horizonts in Grad über der Waagrechten, je Himmelsrichtung "
            "(Azimut wie bei den PV-Feldern: Süd 0°, Ost -90°, West 90°). Balken mit der Maus ziehen oder mit "
            "▲ / ▼ in 1°-Schritten ändern. Messen: vom Dach oder von der PV-Anlage aus mit "
            "der Kompass- und der Neigungsmesser-App des Handys die Oberkante von Berg, Haus "
            "oder Baum anpeilen. Zwischen den Richtungen wird linear interpoliert; 0° heißt "
            "freier Horizont. Graue Richtungen erreicht die Sonne an diesem Standort nie."
        )
        if stored is not None and not _on_grid(stored):
            st.info(
                "Der gespeicherte Horizont hat andere Richtungen als dieses Diagramm. Die Werte "
                "sind auf die 16 Richtungen umgerechnet und werden beim Speichern so abgelegt."
            )
        dropped = dropped_directions(stored, active)
        if dropped:
            st.info(
                f"Gespeicherte Werte für {', '.join(dropped)} entfallen: Diese Richtungen "
                "erreicht die Sonne an diesem Standort nie. Sie werden mit 0° gespeichert."
            )
        elevations = checked_elevations(
            horizon_bars(
                key=horizon_bars_key(session_scope),
                labels=list(DIRECTION_LABELS),
                degrees=[azimuth_label(azimuth) for azimuth in DIRECTION_AZIMUTHS],
                active=active,
                seed=seed_elevations(stored, active),
                paths=_chart_paths(paths),
                max_elevation=MAX_ELEVATION_DEG,
            ),
            active,
        )
        st.caption(
            "Wo eine Sonnenbahn unter der grauen Fläche liegt, erreicht die Sonne das Haus "
            "an diesem Tag nicht direkt."
        )
    return {
        HORIZON_SOURCE_KEY: SOURCE_MANUAL,
        HORIZON_KEY: [
            {"azimuth_deg": azimuth, "elevation_deg": elevation}
            for azimuth, elevation in zip(DIRECTION_AZIMUTHS, elevations)
        ],
    }
