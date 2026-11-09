"""Passthrough merge and save UI for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import (
    _SESSION_CONSUMERS_KEY,
    _SESSION_FILE_STAMP_KEY,
    _SESSION_SELECT_PENDING_KEY,
    _SESSION_SYNC_KEY,
    _NEW_PROFILE_BASELINE_PREFIX,
    _consumers_from_existing,
    _house_profiles_file_stamp,
    _resolve_profile_id,
)
from ui.house_config_profile_house_thermal import house_heating_payload

import os

import streamlit as st

from house_config.earnie_role import (
    DEFAULT_MANUAL_HORIZON_H,
    EARNIE_ROLE_FLEX,
    EARNIE_ROLE_KNOWN,
    EARNIE_ROLE_MANUAL,
    resolve_earnie_role,
)
from house_config.generic_schedule import (
    DEFAULT_START_HOUR,
    MAX_START_SHIFT_H,
    format_start_window_caption,
    generic_annual_kwh,
    reject_legacy_start_flexibility,
)
from house_config.entity_id_lock import (
    FORCE_ID_FROM_LABEL_KEY,
    ID_LOCKED_KEY,
    ID_PROVISIONAL_LABEL_KEY,
    resolve_id_on_save,
    rewrite_consumer_bindings_slug,
)
from house_config.thermal_labels import (
    CONSUMER_TYPE_LABELS,
    building_class_option_label,
)
from runtime_store.persist_paths import resolve_house_profiles_json_path
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    load_house_profiles,
    preview_baseload,
    queue_csv_path_update,
    save_profile_consumption_csv,
    single_csv_upload,
    upsert_house_profile,
)
from ui.auto_persist import auto_persist, payload_fingerprint
from ui.flash import flash
from ui.form_layout import (
    WIDE_LABEL_RATIOS,
    labeled_checkbox,
    labeled_number_input,
    labeled_selectbox,
    labeled_text_input,
)






_PASSTHROUGH_CONSUMER_KEYS = (
    "loxone_inputs",
    "loxone_outputs",
    "optimizer_flex",
    "thermal_flex_window",
    "max_on_quarterhours",
    "max_pulses_per_day",
    "min_on_quarterhours",
    "heating_power_threshold_kw",
    "actual_temp_step_c",
    "thermal_control",
    "filter_schedule",
    "daily_target_source",
    "daily_target_kwh",
    "profile_csv",
    "use_profile_csv",
    "ehal_bindings",
    ID_LOCKED_KEY,
    ID_PROVISIONAL_LABEL_KEY,
)

def _drop_view_charger_bindings(item: dict) -> None:
    """The form's EV carries the charger bindings of the loaded pair view (passthrough).

    They belong to the wallbox and are edited there (EHAL-Com); with a changed wallbox
    choice they would land on the new wallbox, so the form never hands them back.
    """
    from house_config.wallboxes import is_charger_binding_key

    bindings = item.get("ehal_bindings")
    if not isinstance(bindings, dict):
        return
    kept = {k: v for k, v in bindings.items() if not is_charger_binding_key(k)}
    if kept:
        item["ehal_bindings"] = kept
    else:
        item.pop("ehal_bindings", None)


def _merge_passthrough_consumer_fields(original: dict, edited: dict) -> dict:
    merged = dict(edited)
    for key in _PASSTHROUGH_CONSUMER_KEYS:
        if key not in original or key in merged:
            continue
        # „Haus Wärme“ renders its min-on time for electric heat sources only; a fuel
        # source has none (heating-system catalog), so the old value must not come back.
        if key == "min_on_quarterhours" and edited.get("type") == "thermal_annual":
            continue
        value = original[key]
        merged[key] = dict(value) if isinstance(value, dict) else value
    orig_sched = original.get("charging_schedule")
    if isinstance(orig_sched, dict):
        sched = dict(merged.get("charging_schedule") or {})
        sched_updated = False
        loxone = orig_sched.get("loxone")
        if isinstance(loxone, dict) and "loxone" not in sched:
            sched["loxone"] = dict(loxone)
            sched_updated = True
        milp = orig_sched.get("milp")
        if isinstance(milp, dict) and milp and "milp" not in sched:
            sched["milp"] = dict(milp)
            sched_updated = True
        if sched_updated:
            merged["charging_schedule"] = sched
    return merged

def _resolve_consumer_ids(consumers: list[dict], edited: list[dict]) -> list[dict]:
    taken: set[str] = set()
    resolved: list[dict] = []
    for index, raw_item in enumerate(edited):
        item = dict(raw_item)
        force = bool(item.pop(FORCE_ID_FROM_LABEL_KEY, False))
        label = str(item.get("label", "")).strip()
        original = consumers[index] if index < len(consumers) else {}
        stable_id = str(original.get("id", "")).strip()
        provisional_ui = str(
            item.get(ID_PROVISIONAL_LABEL_KEY)
            or original.get(ID_PROVISIONAL_LABEL_KEY)
            or ""
        ).strip()
        consumer_id, id_locked, provisional = resolve_id_on_save(
            label=label or "verbraucher",
            stable_id=stable_id,
            existing=original if isinstance(original, dict) else None,
            taken=taken,
            provisional_from_ui=provisional_ui,
            force_from_label=force,
        )
        item = _merge_passthrough_consumer_fields(original, item)
        if stable_id and stable_id != consumer_id:
            bindings = item.get("ehal_bindings")
            item["ehal_bindings"] = rewrite_consumer_bindings_slug(
                bindings if isinstance(bindings, dict) else {},
                old_id=stable_id,
                new_id=consumer_id,
                consumer_type=str(item.get("type") or "").strip(),
            )
            from house_config.heating_rod_bindings import (
                ROD_BINDINGS_KEY,
                rewrite_rod_bindings_slug,
            )

            if item.get(ROD_BINDINGS_KEY):
                item[ROD_BINDINGS_KEY] = rewrite_rod_bindings_slug(
                    item[ROD_BINDINGS_KEY], new_consumer_id=consumer_id
                )
        item["id"] = consumer_id
        item["label"] = label or consumer_id
        if str(item.get("type") or "") == "ev":
            _drop_view_charger_bindings(item)
        # Avoid dirty-writing id_locked onto legacy rows (missing flag ⇒ locked)
        # so Hausprofil auto_persist does not rewrite every open.
        if not id_locked:
            item[ID_LOCKED_KEY] = False
            if provisional:
                item[ID_PROVISIONAL_LABEL_KEY] = provisional
            else:
                item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        elif (
            ID_LOCKED_KEY in original
            or force
            or (stable_id and stable_id != consumer_id)
        ):
            item[ID_LOCKED_KEY] = True
            item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        else:
            item.pop(ID_LOCKED_KEY, None)
            item.pop(ID_PROVISIONAL_LABEL_KEY, None)
        taken.add(consumer_id)
        from house_config.required_signal_activation import activate_consumer_required

        resolved.append(activate_consumer_required(item))
    return resolved

def _vat_payload(existing: dict) -> dict:
    """D3a ``vat_deductible``: not edited in the form yet, the stored value passes through."""
    from house_config.profile_schema_defaults import profile_default
    from house_config.profiles_store import VAT_DEDUCTIBLE_KEY

    value = existing.get(VAT_DEDUCTIBLE_KEY, profile_default(VAT_DEDUCTIBLE_KEY))
    return {VAT_DEDUCTIBLE_KEY: bool(value)}

def _perform_house_profile_save(
    *,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
    heating: dict,
    absent_mode: bool = False,
    from_auto: bool = False,
) -> str | None:
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    try:
        from ui.house_config_historical_csv import historical_csv_save_fields

        from house_config.own_grid_fee import persist_own_grid_fee

        hist = historical_csv_save_fields(preview_id, existing)
        netznutzung = persist_own_grid_fee(
            location["netznutzung"],
            profile_id=profile_id,
            profile_label=label.strip() or profile_id,
            land=location.get("land"),
        )
        upsert_house_profile(
            {
                "id": profile_id,
                "label": label.strip() or profile_id,
                "annual_kwh": float(annual_kwh),
                "absent_mode": bool(absent_mode),
                "land": location.get("land", "AT"),
                "region": location.get("region", ""),
                "latitude": location["latitude"],
                "longitude": location["longitude"],
                "default_pv_tilt": location["default_pv_tilt"],
                "default_pv_azimuth": location["default_pv_azimuth"],
                "netznutzung": netznutzung,
                "consumers": resolved,
                "total_profile_csv": hist["total_profile_csv"],
                "pv_profile_csv": hist["pv_profile_csv"],
                "battery_profile_csv": hist.get("battery_profile_csv", ""),
                "grid_profile_csv": hist.get("grid_profile_csv", ""),
                "historical_csv_source": hist["historical_csv_source"],
                "baseload_distribution": hist.get(
                    "baseload_distribution", "equal"
                ),
                **house_heating_payload(heating),
                **_vat_payload(existing),
            }
        )
    except ValueError as exc:
        st.error(str(exc))
        return None
    st.session_state[_SESSION_FILE_STAMP_KEY] = _house_profiles_file_stamp()
    if is_new:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        st.rerun()
    elif not from_auto:
        saved_profile = load_house_profiles().get("profiles", {}).get(profile_id, {})
        st.session_state[_SESSION_SELECT_PENDING_KEY] = profile_id
        st.session_state[_SESSION_SYNC_KEY] = None
        st.session_state[_SESSION_CONSUMERS_KEY] = _consumers_from_existing(saved_profile)
        flash("success", "Profil gespeichert.")
        st.rerun()
    return profile_id

def _render_house_profile_save(
    *,
    session_scope: str,
    is_new: bool,
    stable_profile_id: str,
    label: str,
    profile_ids: list[str],
    annual_kwh: float,
    location: dict,
    resolved: list[dict],
    existing: dict,
    preview_id: str,
    heating: dict,
    absent_mode: bool = False,
    held: bool = False,
) -> None:
    """Auto-save of the house profile; ``held`` while a heating-system change awaits a choice."""
    from ui.auto_persist import (
        auto_persist,
        persisted_state_known,
        require_saved,
        seed_persisted,
    )
    from ui.house_config_io import house_profile_write_pending
    from ui.house_config_historical_csv import historical_csv_save_fields

    ready = bool(str(label or "").strip()) and location.get("latitude") is not None
    if not ready or held:
        return
    hist = historical_csv_save_fields(preview_id, existing)
    profile_id = _resolve_profile_id(
        is_new=is_new,
        existing_id=stable_profile_id,
        label=label,
        profile_ids=set(profile_ids),
    )
    payload = {
        "id": profile_id,
        "label": label.strip() or profile_id,
        "annual_kwh": float(annual_kwh),
        "absent_mode": bool(absent_mode),
        "land": location.get("land", "AT"),
        "region": location.get("region", ""),
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "default_pv_tilt": location["default_pv_tilt"],
        "default_pv_azimuth": location["default_pv_azimuth"],
        "netznutzung": location["netznutzung"],
        "consumers": resolved,
        "total_profile_csv": hist["total_profile_csv"],
        "pv_profile_csv": hist["pv_profile_csv"],
        "battery_profile_csv": hist.get("battery_profile_csv", ""),
        "grid_profile_csv": hist.get("grid_profile_csv", ""),
        "historical_csv_source": hist["historical_csv_source"],
        "baseload_distribution": hist.get("baseload_distribution", "equal"),
        **house_heating_payload(heating),
        **_vat_payload(existing),
    }

    if is_new:
        # "— neu —" shows editable defaults; do not create a profile until the user
        # changed something relative to them.
        baseline = st.session_state.setdefault(
            _NEW_PROFILE_BASELINE_PREFIX + session_scope, payload_fingerprint(payload)
        )
        if baseline == payload_fingerprint(payload):
            return
    if not (location.get("netznutzung") or {}).get("area_id"):
        # Data model 5: no implicit "no grid fee" — the form shows a warning until chosen.
        return

    def _save() -> None:
        saved_id = _perform_house_profile_save(
            is_new=is_new,
            stable_profile_id=stable_profile_id,
            label=label,
            profile_ids=profile_ids,
            annual_kwh=annual_kwh,
            absent_mode=absent_mode,
            location=location,
            resolved=resolved,
            existing=existing,
            preview_id=preview_id,
            heating=heating,
            from_auto=True,
        )
        require_saved(saved_id)

    state_key = f"house_profile::{session_scope}::{profile_id}"
    success_caption = "Gespeichert"
    if not is_new and not persisted_state_known(state_key):
        # First render of this profile in the session: opening the page must not
        # rewrite the file. Only a file that does not yet hold the normalised form
        # is written, and that write is named. A dry run that fails leaves the
        # error to the save below (same message, same place).
        from house_config.own_grid_fee import stored_own_grid_fee

        try:
            pending = house_profile_write_pending(
                {
                    **payload,
                    "netznutzung": stored_own_grid_fee(
                        payload["netznutzung"], profile_id=profile_id
                    ),
                }
            )
        except ValueError:
            pending = True
        if not pending:
            seed_persisted(state_key, payload)
            return
        success_caption = "Gespeichert – Datei auf das aktuelle Format gebracht"
    # The Profil dropdown lists labels from disk: rerun only when the label changed
    # (every other auto-save already rendered the new values in this run).
    label_changed = _label_changed(label, existing)
    wrote = auto_persist(
        state_key=state_key,
        payload=payload,
        save=_save,
        ready=ready,
        success_caption=success_caption,
        rerun_follows=label_changed,
    )
    if wrote and label_changed:
        st.rerun()


def _label_changed(label: str, existing: dict) -> bool:
    return str(label or "").strip() != str(existing.get("label") or "").strip()
