"""House-profile section „Horizont“ (SUSI P3a): manual horizon in 16 directions with preview.

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
from ui.house_config_profile_session import _scoped_key
from ui.number_format import localized_figure

# Clockwise from north; azimuth 0° = south, east negative (as for the PV fields).
DIRECTION_LABELS: tuple[str, ...] = (
    "N", "NNO", "NO", "ONO", "O", "OSO", "SO", "SSO",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
)
DIRECTION_STEP_DEG = 360.0 / len(DIRECTION_LABELS)
DIRECTION_AZIMUTHS: tuple[float, ...] = tuple(
    -180.0 + index * DIRECTION_STEP_DEG for index in range(len(DIRECTION_LABELS))
)
_COLUMNS = 4
_SUN_DAYS: tuple[tuple[str, int, int, str], ...] = (
    ("21. Juni", 6, 21, "#E69F00"),
    ("Tagundnachtgleiche", 3, 20, "#009E73"),
    ("21. Dezember", 12, 21, "#0072B2"),
)


def horizon_enabled_key(session_scope: str) -> str:
    return _scoped_key(session_scope, "house_horizon_enabled")


def horizon_elevation_key(session_scope: str, index: int) -> str:
    return _scoped_key(session_scope, f"house_horizon_elevation_{index}")


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


def _render_elevation_inputs(stored: HorizonProfile | None, *, session_scope: str) -> list[float]:
    elevations = [0.0] * len(DIRECTION_LABELS)
    columns = st.columns(_COLUMNS)
    per_column = len(DIRECTION_LABELS) // _COLUMNS
    for index, (label, azimuth) in enumerate(zip(DIRECTION_LABELS, DIRECTION_AZIMUTHS)):
        seed = round(stored.elevation_at(azimuth), 1) if stored is not None else 0.0
        with columns[index // per_column]:
            elevations[index] = float(
                st.number_input(
                    f"{label} ({azimuth:+.1f}°)".replace(".", ","),
                    min_value=0.0,
                    max_value=MAX_ELEVATION_DEG,
                    value=float(seed),
                    step=1.0,
                    format="%.1f",
                    key=horizon_elevation_key(session_scope, index),
                )
            )
    return elevations


@st.cache_data(show_spinner=False, max_entries=16)
def _sun_paths(latitude: float, longitude: float, year: int) -> dict[str, list[tuple[float, float]]]:
    return {
        label: sun_path(latitude, longitude, date(year, month, day))
        for label, month, day, _color in _SUN_DAYS
    }


def horizon_preview_figure(elevations: list[float], *, latitude: float, longitude: float):
    """Horizon line (filled) and the sun's path on three days over the azimuth."""
    import plotly.graph_objects as go

    azimuths = [*DIRECTION_AZIMUTHS, 180.0]
    line = [*elevations, elevations[0]]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=azimuths,
            y=line,
            name="Horizont",
            mode="lines",
            fill="tozeroy",
            line={"color": "#555555"},
            fillcolor="rgba(85, 85, 85, 0.35)",
        )
    )
    paths = _sun_paths(round(float(latitude), 3), round(float(longitude), 3), date.today().year)
    for label, _month, _day, color in _SUN_DAYS:
        path = paths[label]
        fig.add_trace(
            go.Scatter(
                x=[azimuth for azimuth, _elevation in path],
                y=[elevation for _azimuth, elevation in path],
                name=f"Sonne {label}",
                mode="lines",
                line={"color": color},
            )
        )
    fig.update_layout(
        height=320,
        margin={"l": 40, "r": 10, "t": 10, "b": 40},
        legend={"orientation": "h", "y": -0.25},
        xaxis={
            "title": "Himmelsrichtung",
            "range": [-180, 180],
            "tickvals": [-180, -135, -90, -45, 0, 45, 90, 135, 180],
            "ticktext": ["N", "NO", "O", "SO", "S", "SW", "W", "NW", "N"],
        },
        yaxis={"title": "Höhenwinkel (°)", "range": [0, 90]},
    )
    return fig


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
                "Das ändert Jahresmodell, Szenarien-Explorer und die Open-Meteo-Prognosen. "
                "Die PV-Prognose von forecast.solar kennt das Gelände bereits selbst."
            ),
        )
    )
    if not enabled:
        if stored is None:
            return {}
        # Kept for the next time the switch is turned on.
        return {HORIZON_SOURCE_KEY: SOURCE_NONE, HORIZON_KEY: stored.as_list()}
    with st.expander("Horizont in 16 Richtungen", expanded=True):
        st.caption(
            "Höhenwinkel des Horizonts in Grad über der Waagrechten, je Himmelsrichtung "
            "(Azimut 0° = Süd, Ost negativ, West positiv). Messen: vom Dach oder von der "
            "PV-Anlage aus mit der Kompass- und der Neigungsmesser-App des Handys die "
            "Oberkante von Berg, Haus oder Baum anpeilen. Zwischen den Richtungen wird "
            "linear interpoliert; 0° heißt freier Horizont."
        )
        if stored is not None and not _on_grid(stored):
            st.info(
                "Der gespeicherte Horizont hat andere Richtungen als diese Tabelle. Die Werte "
                "sind auf die 16 Richtungen umgerechnet und werden beim Speichern so abgelegt."
            )
        elevations = _render_elevation_inputs(stored, session_scope=session_scope)
        st.plotly_chart(
            localized_figure(
                horizon_preview_figure(elevations, latitude=latitude, longitude=longitude)
            ),
            width="stretch",
            key=_scoped_key(session_scope, "house_horizon_chart"),
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
