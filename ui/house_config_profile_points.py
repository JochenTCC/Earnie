"""Hausprofil-Formularfelder, die in die Earnie-Points einfließen (Wallbox bidirektional, Geräteart)."""
from __future__ import annotations

from house_config.consumer_points_fields import (
    APPLIANCE_KIND_AIR_CONDITIONER,
    APPLIANCE_KIND_CONSUMER_TYPES,
)
from ui.form_layout import labeled_checkbox, labeled_selectbox
from ui.house_config_profile_session import _scoped_key

_APPLIANCE_KIND_NONE = ""
_APPLIANCE_KIND_LABELS = {
    _APPLIANCE_KIND_NONE: "— keine Angabe —",
    APPLIANCE_KIND_AIR_CONDITIONER: "Klimaanlage",
}


def _render_bidirectional_field(consumer: dict, index: int, *, session_scope: str) -> dict:
    value = labeled_checkbox(
        "Wallbox bidirektional (V2G)",
        value=bool(consumer.get("bidirectional", False)),
        key=_scoped_key(session_scope, f"hc_ev_bidirectional_{index}"),
        help=(
            "Nur setzen, wenn die Wallbox das Fahrzeug auch entladen kann. "
            "Fließt in die Earnie-Points ein (Wallbox bidirektional)."
        ),
    )
    return {"bidirectional": bool(value)}


def _render_appliance_kind_field(consumer: dict, index: int, *, session_scope: str) -> dict:
    options = list(_APPLIANCE_KIND_LABELS)
    current = str(consumer.get("appliance_kind") or _APPLIANCE_KIND_NONE)
    selected = labeled_selectbox(
        "Geräteart",
        options=options,
        index=options.index(current) if current in options else 0,
        format_func=lambda value: _APPLIANCE_KIND_LABELS.get(value, value),
        key=_scoped_key(session_scope, f"hc_appliance_kind_{index}"),
        help="Klimaanlagen zählen in den Earnie-Points wie Wärmepumpen (1 Punkt).",
    )
    if selected == _APPLIANCE_KIND_NONE:
        return {}
    return {"appliance_kind": str(selected)}


def _render_points_fields(
    consumer: dict, index: int, c_type: str, *, session_scope: str
) -> dict:
    """Optional Earnie-Points-Felder je Verbrauchertyp (leeres Dict, wenn nicht zutreffend)."""
    if c_type == "ev":
        return _render_bidirectional_field(consumer, index, session_scope=session_scope)
    if c_type in APPLIANCE_KIND_CONSUMER_TYPES:
        return _render_appliance_kind_field(consumer, index, session_scope=session_scope)
    return {}
