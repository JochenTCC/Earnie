"""EHAL-Com download helper for the HA push carrier YAML package (Binding P5c)."""
from __future__ import annotations

import os

import streamlit as st

from integrations.ha_carrier_yaml import build_carrier_yaml
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER


def render_ha_carrier_yaml_download() -> None:
    """Host / port / token form and download button for the HA YAML package."""
    st.subheader("HA YAML-Paket")
    st.caption(
        "Push-Transport: rest_command + periodische Automationen, status.json-Sensor, "
        "Sollwert-Automationen. ENTITY_*-Platzhalter in Home Assistant ersetzen — "
        "Earnie speichert keine entity_ids."
    )
    house, components = _load_docs()
    host = st.text_input(
        "Earnie-Host (für HA erreichbar)",
        value=_default_host(),
        key="ha_carrier_export_host",
    )
    port = st.number_input(
        "HTTP-Port",
        min_value=1,
        max_value=65535,
        value=_default_port(),
        key="ha_carrier_export_port",
    )
    token = st.text_input(
        "Push-Token",
        value=_default_token(),
        key="ha_carrier_export_token",
        help="EARNIE_PUSH_TOKEN — Platzhalter lassen und in HA ersetzen, wenn leer.",
    )
    if not str(host or "").strip():
        st.caption("Host eingeben, um den YAML-Download freizuschalten.")
        return
    try:
        text = build_carrier_yaml(
            house,
            components,
            earnie_host=str(host).strip(),
            earnie_port=int(port),
            token=str(token or "").strip() or TOKEN_PLACEHOLDER,
        )
    except Exception as exc:  # noqa: BLE001 — show in UI
        st.error(f"YAML-Export fehlgeschlagen: {exc}")
        return
    st.download_button(
        "YAML-Paket herunterladen",
        data=text.encode("utf-8"),
        file_name="earnie_ha_carrier.yaml",
        mime="text/yaml",
        key="ha_carrier_export_yaml",
    )


def _load_docs() -> tuple[dict, dict]:
    from ui.house_config_io import _load_components_document, load_house_profiles

    house = load_house_profiles()
    try:
        components = _load_components_document()
    except Exception:  # noqa: BLE001
        components = {"batteries": [], "pv_systems": []}
    if not isinstance(components, dict):
        components = {"batteries": [], "pv_systems": []}
    return house if isinstance(house, dict) else {}, components


def _default_host() -> str:
    return str(os.environ.get("EARNIE_LAN_IP") or os.environ.get("EARNIE_HOST") or "").strip()


def _default_port() -> int:
    try:
        import config

        cfg = getattr(config, "CONFIG", None)
        if cfg is not None and hasattr(cfg, "get_ehal_http_port"):
            return int(cfg.get_ehal_http_port())
        raw = getattr(cfg, "ehal_http_port", None) if cfg else None
        if raw is None and cfg is not None:
            raw = getattr(cfg, "ehal_loxone_http_port", None)
        if raw is None and cfg is not None:
            system = getattr(cfg, "system", None) or {}
            if isinstance(system, dict):
                raw = system.get("ehal_http_port", system.get("ehal_loxone_http_port"))
        return int(raw or 8541)
    except Exception:  # noqa: BLE001
        return 8541


def _default_token() -> str:
    from integrations.ehal_request_http import push_token

    return str(push_token() or TOKEN_PLACEHOLDER).strip()
