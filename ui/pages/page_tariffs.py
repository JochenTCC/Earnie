"""Tarife: Benutzertarife mit dem eingebetteten Edibert-Editor (epic Edibert P7).

The editor writes ``user_tariffs.json`` next to ``tariffs.json``; the house context (land,
region, time zone, grid area) comes from a house profile and is shown read-only. Deleting a
user tariff that a scenario uses asks first and names the scenarios; after every write the
tariff plausibility check runs once (P7 D7).
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.help_hint import render_page_title_with_help
from ui.label_select import label_select_choices, resolve_label_select

_HELP = (
    "Eigene Tarife (Benutzertarife) anlegen, bearbeiten, aus dem Katalog kopieren oder als "
    "JSON importieren. Gespeichert wird in `user_tariffs.json` neben `tariffs.json`. "
    "Vorschau und Prüfungen rechnen mit Land, Region und Netzbereich des gewählten Hausprofils; "
    "diese Werte änderst du im Hauskonfigurator. Welcher Tarif in einem Szenario gilt, wählst du "
    "im Szenarienkonfigurator."
)

KEY_PREFIX = "earnie.tariffs."
_PROFILE_SELECT_KEY = "tariffs_page_profile"
# Set by other pages (Szenarienkonfigurator, P7 S3) before ``st.switch_page``:
# {"profile_id": str, "open": (direction, tariff_id) | None}.
REQUEST_KEY = "tariffs_page_request"
# Set by the editor's on_change; the next render runs the plausibility check once.
_CHECK_KEY = "tariffs_page_check_pending"
_SIDE_LABELS = {"import": "Bezugstarif", "export": "Einspeisetarif"}


def request_tariff_page(profile_id: str, open_tariff: tuple[str, str] | None = None) -> None:
    """Ask the Tarife page to show ``profile_id`` and open ``open_tariff`` (call before switch_page)."""
    st.session_state[REQUEST_KEY] = {"profile_id": profile_id, "open": open_tariff}


def _select_profile(profiles: dict[str, dict], request: dict | None) -> str:
    from ui.ehal_loxone_mapping import resolve_live_profile_id

    ids = list(profiles)
    displays, id_by_display = label_select_choices(profiles, ids, new_option=None)
    display_by_id = {entity_id: display for display, entity_id in id_by_display.items()}
    wanted = (request or {}).get("profile_id")
    if wanted in profiles:
        st.session_state[_PROFILE_SELECT_KEY] = display_by_id[wanted]
    elif st.session_state.get(_PROFILE_SELECT_KEY) not in displays:
        st.session_state[_PROFILE_SELECT_KEY] = display_by_id[
            resolve_live_profile_id({"profiles": profiles})
        ]
    picked = st.selectbox(
        "Hausprofil",
        displays,
        key=_PROFILE_SELECT_KEY,
        help="Liefert Land, Region, Zeitzone und Netzbereich für Vorschau und Prüfungen.",
    )
    return resolve_label_select(picked, id_by_display)


def _delete_guard(direction: str, tariff_id: str) -> str | None:
    """Warning for the editor's delete confirmation: the scenarios that use the tariff."""
    from house_config.tariff_plausibility import scenarios_using_tariff
    from runtime_store.persist_paths import resolve_backtesting_scenarios_json_path

    users = scenarios_using_tariff(
        resolve_backtesting_scenarios_json_path(), direction, tariff_id
    )
    if not users:
        return None
    return (
        f"„{tariff_id}“ ist {_SIDE_LABELS[direction]} in "
        f"{'Szenario' if len(users) == 1 else 'den Szenarien'} {', '.join(users)}. "
        "Nach dem Löschen meldet die Tarif-Prüfung diese Szenarien, bis du dort im "
        "Szenarienkonfigurator einen anderen Tarif wählst."
    )


def _on_change(_action: str, _direction: str, _tariff_id: str) -> None:
    st.session_state[_CHECK_KEY] = True


def _render_pending_check() -> None:
    """Tariff plausibility (with Edibert) once after the editor wrote ``user_tariffs.json``."""
    from house_config.tariff_plausibility import (
        collect_tariff_plausibility_errors,
        format_tariff_plausibility_errors,
    )
    from runtime_store.persist_paths import (
        resolve_backtesting_scenarios_json_path,
        resolve_grid_fees_json_path,
        resolve_house_profiles_json_path,
        resolve_tariffs_json_path,
    )

    if not st.session_state.pop(_CHECK_KEY, False):
        return
    errors = collect_tariff_plausibility_errors(
        tariffs_path=resolve_tariffs_json_path(),
        scenarios_path=resolve_backtesting_scenarios_json_path(),
        with_edibert=True,
        grid_fees_path=resolve_grid_fees_json_path(),
        house_profiles_path=resolve_house_profiles_json_path(),
    )
    if errors:
        st.error(format_tariff_plausibility_errors(errors))


def render() -> None:
    from edibert.ui.config import UiConfig
    from edibert.ui.embed import render_editor

    from house_config.edibert_tariffs import host_house_for_profile
    from runtime_store.persist_paths import (
        resolve_grid_fees_json_path,
        resolve_tariffs_json_path,
        user_tariffs_path_for,
    )
    from runtime_store.shadow.mode import is_shadow_config_readonly
    from ui.house_config_io import load_house_profiles

    render_page_title_with_help("💶 Tarife", _HELP, key="tariffs_page_help")
    if is_shadow_config_readonly():
        st.info(
            "Shadow-Modus: Konfiguration schreibgeschützt — Benutzertarife können hier "
            "nicht bearbeitet werden."
        )
        return
    profiles = load_house_profiles().get("profiles") or {}
    if not profiles:
        st.warning("Noch kein Hausprofil vorhanden. Bitte zuerst im Hauskonfigurator anlegen.")
        return
    # Kept across reruns: the editor opens a requested tariff only once per distinct request.
    request = st.session_state.get(REQUEST_KEY)
    profile_id = _select_profile(profiles, request)
    if request is not None and request.get("profile_id") is not None:
        st.session_state[REQUEST_KEY] = {**request, "profile_id": None}
    try:
        host = host_house_for_profile(
            profile_id, profiles[profile_id], resolve_grid_fees_json_path()
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    _render_pending_check()
    tariffs_path = Path(resolve_tariffs_json_path())
    data_dir = Path(user_tariffs_path_for(str(tariffs_path))).parent
    render_editor(
        UiConfig(
            data_dir=data_dir,
            catalog=tariffs_path,
            language="de",
            key_prefix=KEY_PREFIX,
            host_house=host,
            delete_guard=_delete_guard,
            on_change=_on_change,
        ),
        open_tariff=(request or {}).get("open"),
    )
