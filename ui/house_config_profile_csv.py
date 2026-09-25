"""Per-consumer and house Jahres-CSV UI for Hausprofil form."""
from __future__ import annotations

from ui.house_config_profile_session import _SESSION_SELECTED_ID_KEY, _scoped_key

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
from house_config.id_slug import slug_id
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
from ui.auto_persist import auto_persist
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
)




def _digital_csv_decision_key(session_scope: str, index: int, path: str) -> str:
    return _scoped_key(session_scope, f"hc_digital_csv_decision_{index}_{path}")

def _ensure_consumer_csv_normalized(
    path: str,
    *,
    digital_scale_kw: float | None = None,
) -> None:
    from house_config.consumption_csv import load_hourly_profile_csv, normalize_profile_csv_file

    if digital_scale_kw is not None:
        normalize_profile_csv_file(path, digital_scale_kw=digital_scale_kw)
        return
    try:
        load_hourly_profile_csv(path)
    except ValueError:
        normalize_profile_csv_file(path)

def _render_digital_csv_scale_prompt(
    path: str,
    *,
    index: int,
    session_scope: str,
    nominal_power_kw: float,
) -> None:
    """Ask once whether to multiply a digital 0/1 CSV by nominal power."""
    from house_config.consumption_csv import profile_csv_looks_digital

    decision_key = _digital_csv_decision_key(session_scope, index, path)
    decision = st.session_state.get(decision_key)
    if decision == "yes":
        return
    if decision == "no":
        try:
            _ensure_consumer_csv_normalized(path)
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    try:
        looks_digital = profile_csv_looks_digital(path)
    except (ValueError, OSError, FileNotFoundError) as exc:
        st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    if not looks_digital:
        try:
            _ensure_consumer_csv_normalized(path)
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.warning(f"CSV noch nicht normalisierbar: {exc}")
        return
    st.info(
        f"Digitales Ein/Aus-Signal (0/1) erkannt. "
        f"Mit Nennleistung **{nominal_power_kw:.3f} kW** multiplizieren?"
    )
    col_yes, col_no = st.columns(2)
    with col_yes:
        if st.button(
            "Ja, mit Nennleistung multiplizieren",
            key=_scoped_key(session_scope, f"hc_digital_yes_{index}"),
        ):
            if nominal_power_kw <= 0.0:
                st.error("Nennleistung muss > 0 kW sein, um zu skalieren.")
            else:
                try:
                    _ensure_consumer_csv_normalized(
                        path, digital_scale_kw=nominal_power_kw
                    )
                    st.session_state[decision_key] = "yes"
                    st.success(
                        f"CSV mit {nominal_power_kw:.3f} kW skaliert und gespeichert."
                    )
                    st.rerun()
                except (ValueError, OSError, FileNotFoundError) as exc:
                    st.error(f"Skalierung fehlgeschlagen: {exc}")
    with col_no:
        if st.button(
            "Nein, Werte unverändert lassen",
            key=_scoped_key(session_scope, f"hc_digital_no_{index}"),
        ):
            try:
                _ensure_consumer_csv_normalized(path)
                st.session_state[decision_key] = "no"
                st.rerun()
            except (ValueError, OSError, FileNotFoundError) as exc:
                st.error(f"Normalisierung fehlgeschlagen: {exc}")

def _consumer_csv_keys(session_scope: str, index: int) -> dict[str, str]:
    """Session/widget keys for one consumer CSV block (stable naming)."""
    return {
        "path": _scoped_key(session_scope, f"hc_profile_csv_path_{index}"),
        "input": _scoped_key(session_scope, f"hc_profile_csv_input_{index}"),
        "use": _scoped_key(session_scope, f"hc_use_profile_csv_{index}"),
        "pending": _scoped_key(session_scope, f"hc_profile_csv_pending_{index}"),
        "upload_base": _scoped_key(session_scope, f"hc_profile_csv_upload_{index}"),
        "upload_nonce": _scoped_key(session_scope, f"hc_profile_csv_upload_nonce_{index}"),
        "flash": _scoped_key(session_scope, f"hc_profile_csv_flash_{index}"),
    }

def _render_consumer_csv_intro() -> None:
    st.markdown("**Historisches Leistungsprofil [kW] (CSV)**")
    st.caption(
        "Gleiches Format wie Jahres-CSV (`timestamp;power_kw`). "
        "Wenn aktiv („Von Basis-Last abziehen“): CSV-Last statt Synthese; "
        "Abzug von der Basislast (HK und SE). "
        "Bekannt → feste Last; Gesteuert/Manual → SE nutzt CSV-Energie als Ziel; "
        "Live Gesteuert ignoriert CSV. "
        "Digitale 0/1-Signale: beim Import optional × Nennleistung."
    )

def _seed_consumer_csv_session(consumer: dict, keys: dict[str, str]) -> None:
    if keys["path"] not in st.session_state:
        st.session_state[keys["path"]] = str(consumer.get("profile_csv", "") or "").strip()
    if keys["input"] not in st.session_state:
        st.session_state[keys["input"]] = st.session_state[keys["path"]]

def _render_consumer_csv_inputs(
    index: int,
    *,
    session_scope: str,
    keys: dict[str, str],
) -> tuple[object | None, bool]:
    """Path text input plus upload/clear row; returns (upload, clear_clicked)."""
    csv_path = labeled_text_input(
        "CSV-Pfad (Verbraucher)",
        value=st.session_state[keys["path"]],
        key=keys["input"],
    )
    st.session_state[keys["path"]] = csv_path.strip()
    up_col, clear_col = st.columns([4, 1], vertical_alignment="bottom")
    with up_col:
        upload = single_csv_upload(
            "Verbraucher-CSV hochladen",
            key=csv_upload_widget_key(keys["upload_base"], keys["upload_nonce"]),
            help="Nur eine CSV-Datei je Verbraucher.",
        )
    with clear_col:
        clear = st.button(
            "Verbraucher-CSV entfernen",
            key=_scoped_key(session_scope, f"hc_profile_csv_clear_{index}"),
        )
    return upload, clear

def _store_uploaded_consumer_csv(
    upload,
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    keys: dict[str, str],
) -> None:
    consumer_slug = slug_id(str(consumer.get("id") or consumer.get("label") or f"c{index}"))
    profile_slug = slug_id(
        str(
            st.session_state.get(_SESSION_SELECTED_ID_KEY)
            or st.session_state.get("house_profile_select")
            or "profile"
        )
    )
    try:
        saved = save_profile_consumption_csv(
            profile_slug,
            upload.getvalue(),
            upload.name,
            consumer_id=consumer_slug or f"c{index}",
        )
        decision_key = _digital_csv_decision_key(session_scope, index, saved)
        st.session_state.pop(decision_key, None)
        queue_csv_path_update(
            keys["pending"],
            saved,
            upload_nonce_key=keys["upload_nonce"],
            flash_key=keys["flash"],
            flash_message=f"CSV gespeichert: `{saved}`",
        )
        st.rerun()
    except (ValueError, OSError, FileNotFoundError) as exc:
        st.error(f"CSV ungültig: {exc}")

def _maybe_prompt_digital_scale(
    active: str,
    *,
    index: int,
    session_scope: str,
    nominal_power_kw: float,
) -> None:
    if not active:
        return
    from pathlib import Path

    from runtime_store.persist_paths import resolve_config_prefixed_path

    if not Path(resolve_config_prefixed_path(active)).is_file():
        return
    _render_digital_csv_scale_prompt(
        active,
        index=index,
        session_scope=session_scope,
        nominal_power_kw=nominal_power_kw,
    )

def _render_consumer_csv_use_flag(consumer: dict, *, active: str, use_key: str) -> bool:
    if not active:
        st.session_state[use_key] = False
        return False
    return bool(
        labeled_checkbox(
            "Von Basis-Last abziehen",
            value=bool(consumer.get("use_profile_csv", False)),
            key=use_key,
            help=(
                "Aktiv: CSV-Last nutzen und von der Basislast abziehen. "
                "HK/SE: Residual bzw. Overlay je Rolle; "
                "Live Gesteuert: Schedule; Live Manual: nur Nutzer-Tagesplan."
            ),
        )
    )

def _render_consumer_profile_csv_fields(
    consumer: dict,
    index: int,
    *,
    session_scope: str,
    nominal_power_kw: float,
) -> dict:
    """Historisches Verbraucher-CSV + use_profile_csv-Flag."""
    keys = _consumer_csv_keys(session_scope, index)
    _render_consumer_csv_intro()

    apply_csv_path_pending(
        keys["pending"], keys["path"], keys["input"], use_key=keys["use"]
    )
    _seed_consumer_csv_session(consumer, keys)

    flash = st.session_state.pop(keys["flash"], None)
    if flash:
        st.success(flash)

    upload, clear = _render_consumer_csv_inputs(
        index, session_scope=session_scope, keys=keys
    )
    if upload is not None:
        _store_uploaded_consumer_csv(
            upload, consumer, index, session_scope=session_scope, keys=keys
        )
    if clear:
        queue_csv_path_update(
            keys["pending"],
            "",
            upload_nonce_key=keys["upload_nonce"],
        )
        st.rerun()
    active = st.session_state[keys["path"]]
    _maybe_prompt_digital_scale(
        active,
        index=index,
        session_scope=session_scope,
        nominal_power_kw=nominal_power_kw,
    )
    use_csv = _render_consumer_csv_use_flag(
        consumer, active=active, use_key=keys["use"]
    )
    return {
        "profile_csv": active,
        "use_profile_csv": bool(use_csv),
    }

def _render_consumption_csv_section(
    *,
    existing: dict,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
) -> None:
    from ui.house_config_historical_csv import render_historical_csv_section
    from house_config.consumption_csv import consumer_uses_profile_csv
    from house_config.profile_csv_policy import (
        controllable_generics,
        se_uses_meter_residual_baseload,
        se_uses_monthly_baseload,
    )

    render_historical_csv_section(
        existing=existing,
        preview_id=preview_id,
        annual_kwh=annual_kwh,
        resolved=resolved,
        preview=preview,
    )
    probe = {
        **existing,
        "total_profile_csv": st.session_state.get(
            f"house_profile_csv_path_{preview_id}",
            existing.get("total_profile_csv", ""),
        ),
        "baseload_distribution": st.session_state.get(
            f"house_profile_baseload_dist_{preview_id}",
            existing.get("baseload_distribution", "equal"),
        ),
        "consumers": resolved,
    }
    if str(probe.get("total_profile_csv", "") or "").strip():
        if se_uses_meter_residual_baseload(probe):
            st.caption(
                "SE-Basislast: **Pfad B** (stündlicher Meter-Rest aus Gesamt-CSV "
                "nach Abzug instrumentierter Verbraucher-CSVs)."
            )
        elif se_uses_monthly_baseload(probe):
            st.caption(
                "SE-Basislast: **Pfad A / Monats-Rest** (pro Monat Ist − Modellverbraucher; "
                "plus Rollen-Overlays). Pfad B nur wenn alle Gesteuert/Manual ein aktives CSV haben."
            )
        else:
            missing = [
                str(c.get("label") or c.get("id") or "?")
                for c in controllable_generics(probe)
                if not consumer_uses_profile_csv(c)
            ]
            if missing:
                st.caption(
                    "SE-Basislast: **Pfad A** (flache `baseload_kwh`). "
                    "Für Meter-Rest (Pfad B) brauchen alle Gesteuert/Manual "
                    f"ein aktives CSV: {', '.join(missing)}. "
                    "Oder **Monats-Rest** wählen, wenn die Monatsform besser passt."
                )
            else:
                st.caption(
                    "SE-Basislast: **Pfad A** (flache `baseload_kwh`). "
                    "Optional **Monats-Rest** für monatsweise Anpassung an die Gesamt-CSV."
                )
