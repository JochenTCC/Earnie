"""Mapping UI: which EHAL functions the current bindings enable (HA + Loxone)."""
from __future__ import annotations

from collections.abc import Iterable

import streamlit as st

from ehal.functions import function_statuses, incomplete_function_messages
from ehal.profiles import role_field_labels


def render_function_status(ehal_map: dict[str, str], fields: Iterable[str]) -> None:
    """Warn for partly mapped functions; they stay unavailable until completed."""
    field_list = list(fields)
    statuses = function_statuses(ehal_map, fields=field_list)
    if not statuses:
        return
    for message in incomplete_function_messages(
        ehal_map, fields=field_list, labels=role_field_labels()
    ):
        st.warning(message)
    available = [s.function.label for s in statuses if s.state == "available"]
    if available:
        st.caption("Verfügbare Funktionen: " + " · ".join(available))
