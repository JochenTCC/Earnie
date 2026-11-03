"""Hausprofil-Formularfelder, die in die Earnie-Points einfließen (Wallbox bidirektional).

Die Klimaanlage ist kein Verbraucherfeld mehr: sie steht im Abschnitt „Kühlung“ beim
Haus-Wärme-Verbraucher (``ui.house_config_profile_cooling``).
"""
from __future__ import annotations

from ui.form_layout import labeled_checkbox
from ui.house_config_profile_session import _scoped_key


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


def _render_points_fields(
    consumer: dict, index: int, c_type: str, *, session_scope: str
) -> dict:
    """Optional Earnie-Points-Felder je Verbrauchertyp (leeres Dict, wenn nicht zutreffend)."""
    if c_type == "ev":
        return _render_bidirectional_field(consumer, index, session_scope=session_scope)
    return {}
