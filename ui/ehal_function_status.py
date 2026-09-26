"""Mapping UI: which EHAL functions the current bindings enable (HA + Loxone)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import streamlit as st

from ehal.functions import function_statuses, incomplete_function_messages
from ehal.profiles import role_field_labels
from house_config.control_capability import control_capability_warnings


def render_function_status(
    ehal_map: dict[str, str],
    fields: Iterable[str],
    *,
    vendor_ess_active: bool = False,
) -> None:
    """Warn for partly mapped functions; they stay unavailable until completed."""
    field_list = list(fields)
    statuses = function_statuses(
        ehal_map, fields=field_list, vendor_ess_active=vendor_ess_active
    )
    if not statuses:
        return
    for message in incomplete_function_messages(
        ehal_map,
        fields=field_list,
        labels=role_field_labels(),
        vendor_ess_active=vendor_ess_active,
    ):
        st.warning(message)
    available = [s.function.label for s in statuses if s.state == "available"]
    if available:
        st.caption("Verfügbare Funktionen: " + " · ".join(available))


def render_control_capability_warnings(
    *,
    control: str | None,
    ehal_map: Mapping[str, object],
    ha_ess_force: dict[str, Any] | None = None,
) -> None:
    for message in control_capability_warnings(
        control=control, ehal_map=ehal_map, ha_ess_force=ha_ess_force
    ):
        st.warning(message)