"""EHAL-Com download helper for the HA push carrier YAML package (Binding P5c)."""
from __future__ import annotations

import os

import streamlit as st

from ehal.signal_export import normalize_export_host
from house_config.ha_fail_safe import (
    FAIL_SAFE_VALUES_KEY,
    house_with_fail_safe_values,
    is_signed_fail_safe,
)
from integrations.ha_carrier_yaml import (
    DEFAULT_WATCHDOG_TIMEOUT_S,
    build_carrier_yaml,
    ehal_base_unit,
    fail_safe_signals_from_docs,
)
from runtime_store.shadow.errors import ConfigReadOnlyError
from runtime_store.shadow.mode import is_shadow_config_readonly
from scripts.pilot_vo_template_gen import TOKEN_PLACEHOLDER
from ui.auto_persist import SHADOW_READONLY_CAPTION


def render_ha_carrier_yaml_download() -> None:
    """Host / port / token form and download button for the HA YAML package."""
    st.subheader("HA YAML-Paket")
    st.caption(
        "Push-Transport: rest_command + periodische Automationen, status.json-Sensor, "
        "Sollwert-Automationen. ENTITY_*-Platzhalter in Home Assistant ersetzen — "
        "Earnie speichert keine entity_ids."
    )
    _render_fail_safe_values(*_load_docs())
    # After the form: a save above belongs in the package below.
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
        export_host = normalize_export_host(host)
    except ValueError as exc:
        st.error(str(exc))
        return
    if export_host != str(host).strip():
        st.caption(f"Adresse ohne Schema übernommen: `{export_host}`")
    try:
        text = build_carrier_yaml(
            house,
            components,
            earnie_host=export_host,
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


def _render_fail_safe_values(house: dict, components: dict) -> None:
    """One optional value per written number; saving replaces all of them."""
    st.markdown("##### Fail-safe-Werte")
    st.caption(
        f"Ist Earnie {DEFAULT_WATCHDOG_TIMEOUT_S / 60:g} Minuten nicht erreichbar, schreibt "
        "Home Assistant diese Werte, bis Earnie "
        "wieder antwortet. Was sicher ist, hängt vom Gerät ab, z. B. Entladegrenze = maximale "
        "Entladeleistung. Ohne Wert bleibt das Signal, wie es ist. Danach das YAML-Paket neu "
        "herunterladen und in Home Assistant importieren."
    )
    try:
        signals = fail_safe_signals_from_docs(house, components)
    except ValueError as exc:
        st.error(str(exc))
        return
    if not signals:
        st.caption("Kein aktiviertes Signal, das einen Fail-safe-Wert annehmen kann.")
        return
    readonly = is_shadow_config_readonly()
    if readonly:
        st.caption(SHADOW_READONLY_CAPTION)
    saved = (house.get("plant") or {}).get(FAIL_SAFE_VALUES_KEY) or {}
    with st.form("ha_fail_safe__form"):
        entered = {
            sig.ehal_id: st.number_input(
                f"{sig.ehal_id} ({ehal_base_unit(sig.ehal_id)})",
                value=saved.get(sig.ehal_id),
                min_value=None if is_signed_fail_safe(sig.ehal_id) else 0.0,
                step=1.0,
                format="%g",
                placeholder="kein Wert",
                key=f"ha_fail_safe__{sig.ehal_id}",
                disabled=readonly,
            )
            for sig in signals
        }
        submitted = st.form_submit_button("Fail-safe-Werte speichern", disabled=readonly)
    if submitted:
        _save_fail_safe_values(entered)


def _save_fail_safe_values(entered: dict[str, float | None]) -> None:
    from ui.house_config_io import load_house_profiles, save_house_profiles

    try:
        save_house_profiles(house_with_fail_safe_values(load_house_profiles(), entered))
    except ConfigReadOnlyError:
        st.caption(SHADOW_READONLY_CAPTION)
    except ValueError as exc:
        st.error(str(exc))
    else:
        st.success("Fail-safe-Werte gespeichert. YAML-Paket neu herunterladen und importieren.")


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
