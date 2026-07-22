"""Hauskonfigurator: historische Jahresprofile (Verbrauch / PV / Energiemonitor)."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.form_layout import labeled_text_input
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    queue_csv_path_update,
    save_energiemonitor_profile_csvs,
    save_profile_consumption_csv,
    single_csv_upload,
)

_SOURCE_SEPARATE = "separate"
_SOURCE_ENERGIEMONITOR = "energiemonitor"
_SOURCE_LABELS = {
    _SOURCE_SEPARATE: "Getrennte CSVs (Verbrauch + optional PV-Ertrag)",
    _SOURCE_ENERGIEMONITOR: "Loxone Energiemonitor (eine Datei)",
}


def session_keys(preview_id: str) -> dict[str, str]:
    return {
        "source": f"house_profile_hist_source_{preview_id}",
        "verbrauch": f"house_profile_csv_path_{preview_id}",
        "pv": f"house_profile_pv_csv_path_{preview_id}",
    }


def init_historical_csv_session(preview_id: str, existing: dict) -> None:
    keys = session_keys(preview_id)
    if keys["source"] not in st.session_state:
        raw = str(existing.get("historical_csv_source", "") or "").strip().lower()
        st.session_state[keys["source"]] = (
            raw if raw in (_SOURCE_SEPARATE, _SOURCE_ENERGIEMONITOR) else _SOURCE_SEPARATE
        )
    if keys["verbrauch"] not in st.session_state:
        st.session_state[keys["verbrauch"]] = str(
            existing.get("total_profile_csv", "") or ""
        ).strip()
    if keys["pv"] not in st.session_state:
        st.session_state[keys["pv"]] = str(existing.get("pv_profile_csv", "") or "").strip()


def historical_csv_save_fields(preview_id: str, existing: dict) -> dict[str, str]:
    """Fields to persist on house-profile save."""
    keys = session_keys(preview_id)
    return {
        "total_profile_csv": st.session_state.get(
            keys["verbrauch"], existing.get("total_profile_csv", "")
        ),
        "pv_profile_csv": st.session_state.get(
            keys["pv"], existing.get("pv_profile_csv", "")
        ),
        "historical_csv_source": st.session_state.get(
            keys["source"], existing.get("historical_csv_source", _SOURCE_SEPARATE)
        ),
    }


def render_historical_csv_section(
    *,
    existing: dict,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
) -> None:
    """Radio + uploads for Verbrauch / PV / Energiemonitor; Ist-vs-Modell when Verbrauch set."""
    init_historical_csv_session(preview_id, existing)
    keys = session_keys(preview_id)

    st.subheader("Historische Jahresprofile (CSV)")
    st.caption(
        "Verbrauch (Pflicht für Ist-vs-Modell) und optional PV-Ertrag. "
        "Kanonisch: `timestamp;power_kw` (stündlich, ≥12 Monate). "
        "Loxone-Einzelserien und Energiemonitor-Statistik werden beim Import konvertiert. "
        "SOC / Batterie / Netzleistung werden nicht importiert."
    )

    source = st.radio(
        "Datenimport",
        options=[_SOURCE_SEPARATE, _SOURCE_ENERGIEMONITOR],
        format_func=lambda value: _SOURCE_LABELS[value],
        key=keys["source"],
        horizontal=False,
    )

    if source == _SOURCE_ENERGIEMONITOR:
        _render_energiemonitor_mode(preview_id, keys)
    else:
        _render_separate_mode(preview_id, keys)

    active_path = str(st.session_state.get(keys["verbrauch"], "") or "").strip()
    if not active_path:
        return
    from runtime_store.persist_paths import resolve_config_prefixed_path

    if not Path(resolve_config_prefixed_path(active_path)).is_file():
        st.warning(f"Verbrauchs-CSV nicht gefunden: `{active_path}`")
        return
    _render_ist_vs_modell(
        active_path=active_path,
        preview_id=preview_id,
        annual_kwh=annual_kwh,
        resolved=resolved,
        preview=preview,
        pv_path=str(st.session_state.get(keys["pv"], "") or "").strip(),
    )


def _render_separate_mode(preview_id: str, keys: dict[str, str]) -> None:
    st.markdown("**Verbrauch (Gesamt)**")
    verbrauch_input_key = f"house_profile_csv_input_{preview_id}"
    verbrauch_pending = f"house_profile_csv_pending_{preview_id}"
    verbrauch_upload_base = f"house_profile_csv_upload_{preview_id}"
    verbrauch_nonce = f"house_profile_csv_upload_nonce_{preview_id}"
    verbrauch_flash = f"house_profile_csv_flash_{preview_id}"

    apply_csv_path_pending(verbrauch_pending, keys["verbrauch"], verbrauch_input_key)
    if verbrauch_input_key not in st.session_state:
        st.session_state[verbrauch_input_key] = st.session_state[keys["verbrauch"]]

    flash = st.session_state.pop(verbrauch_flash, None)
    if flash:
        st.success(flash)

    path = labeled_text_input(
        "CSV-Pfad Verbrauch",
        value=st.session_state[keys["verbrauch"]],
        key=verbrauch_input_key,
        help="Relativer Pfad, z. B. config/uploads/mein_haushalt_verbrauch.csv",
    )
    st.session_state[keys["verbrauch"]] = path.strip()
    upload = single_csv_upload(
        "Verbrauch-CSV hochladen",
        key=csv_upload_widget_key(verbrauch_upload_base, verbrauch_nonce),
        help="Nur eine CSV-Datei für den Gesamtverbrauch.",
    )
    if upload is not None:
        try:
            saved = save_profile_consumption_csv(
                preview_id,
                upload.getvalue(),
                upload.name,
                role="verbrauch",
            )
            queue_csv_path_update(
                verbrauch_pending,
                saved,
                upload_nonce_key=verbrauch_nonce,
                flash_key=verbrauch_flash,
                flash_message=f"Verbrauch gespeichert und normalisiert: `{saved}`",
            )
            st.rerun()
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.error(f"Verbrauch-CSV ungültig: {exc}")
    if st.button("Verbrauch-Zuordnung entfernen", key=f"house_profile_csv_clear_{preview_id}"):
        queue_csv_path_update(
            verbrauch_pending,
            "",
            upload_nonce_key=verbrauch_nonce,
        )
        st.rerun()

    st.markdown("**PV-Ertrag (optional, Summe aller Anlagen)**")
    pv_input_key = f"house_profile_pv_csv_input_{preview_id}"
    pv_pending = f"house_profile_pv_csv_pending_{preview_id}"
    pv_upload_base = f"house_profile_pv_csv_upload_{preview_id}"
    pv_nonce = f"house_profile_pv_csv_upload_nonce_{preview_id}"
    pv_flash = f"house_profile_pv_csv_flash_{preview_id}"

    apply_csv_path_pending(pv_pending, keys["pv"], pv_input_key)
    if pv_input_key not in st.session_state:
        st.session_state[pv_input_key] = st.session_state[keys["pv"]]

    pv_flash_msg = st.session_state.pop(pv_flash, None)
    if pv_flash_msg:
        st.success(pv_flash_msg)

    pv_path = labeled_text_input(
        "CSV-Pfad PV-Ertrag",
        value=st.session_state[keys["pv"]],
        key=pv_input_key,
        help="Optional. Relativer Pfad zum PV-Jahresprofil.",
    )
    st.session_state[keys["pv"]] = pv_path.strip()
    pv_upload = single_csv_upload(
        "PV-Ertrag-CSV hochladen",
        key=csv_upload_widget_key(pv_upload_base, pv_nonce),
        help="Nur eine CSV-Datei für den PV-Ertrag.",
    )
    if pv_upload is not None:
        try:
            saved = save_profile_consumption_csv(
                preview_id,
                pv_upload.getvalue(),
                pv_upload.name,
                role="pv",
            )
            queue_csv_path_update(
                pv_pending,
                saved,
                upload_nonce_key=pv_nonce,
                flash_key=pv_flash,
                flash_message=f"PV-Ertrag gespeichert und normalisiert: `{saved}`",
            )
            st.rerun()
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.error(f"PV-CSV ungültig: {exc}")
    if st.button("PV-Zuordnung entfernen", key=f"house_profile_pv_csv_clear_{preview_id}"):
        queue_csv_path_update(pv_pending, "", upload_nonce_key=pv_nonce)
        st.rerun()


def _render_energiemonitor_mode(preview_id: str, keys: dict[str, str]) -> None:
    st.caption(
        "Erwartete Spalten u. a.: `Leistung Verbrauch [kW]` (Pflicht), "
        "`Leistung Produktion [kW]` (optional). Andere Spalten werden ignoriert."
    )
    em_upload_base = f"house_profile_em_csv_upload_{preview_id}"
    em_nonce = f"house_profile_em_csv_upload_nonce_{preview_id}"
    em_flash = f"house_profile_em_csv_flash_{preview_id}"
    verbrauch_input_key = f"house_profile_csv_input_{preview_id}"
    pv_input_key = f"house_profile_pv_csv_input_{preview_id}"

    flash = st.session_state.pop(em_flash, None)
    if flash:
        st.success(flash)

    upload = single_csv_upload(
        "Energiemonitor-CSV hochladen",
        key=csv_upload_widget_key(em_upload_base, em_nonce),
        help="Nur eine Energiemonitor-CSV-Datei.",
    )
    if upload is not None:
        try:
            result = save_energiemonitor_profile_csvs(
                preview_id,
                upload.getvalue(),
                upload.name,
            )
            total = result["total_profile_csv"]
            pv = result.get("pv_profile_csv", "")
            st.session_state[keys["verbrauch"]] = total
            st.session_state[verbrauch_input_key] = total
            st.session_state[keys["pv"]] = pv
            st.session_state[pv_input_key] = pv
            msg = f"Verbrauch: `{total}`"
            if pv:
                msg += f"; PV: `{pv}`"
            else:
                msg += " (keine Produktionsspalte — PV leer)"
            st.session_state[em_flash] = msg
            st.session_state[em_nonce] = int(st.session_state.get(em_nonce, 0) or 0) + 1
            st.rerun()
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.error(f"Energiemonitor-CSV ungültig: {exc}")

    if st.session_state.get(keys["verbrauch"]):
        st.caption(f"Verbrauch: `{st.session_state[keys['verbrauch']]}`")
    if st.session_state.get(keys["pv"]):
        st.caption(f"PV-Ertrag: `{st.session_state[keys['pv']]}`")

    if st.button(
        "Energiemonitor-Zuordnung entfernen",
        key=f"house_profile_em_csv_clear_{preview_id}",
    ):
        st.session_state[keys["verbrauch"]] = ""
        st.session_state[verbrauch_input_key] = ""
        st.session_state[keys["pv"]] = ""
        st.session_state[pv_input_key] = ""
        st.session_state[em_nonce] = int(st.session_state.get(em_nonce, 0) or 0) + 1
        st.rerun()


def _render_ist_vs_modell(
    *,
    active_path: str,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
    pv_path: str,
) -> None:
    from house_config.baseload import trim_baseload_floor_to_match_ist
    from house_config.consumption_csv import (
        load_hourly_profile_csv,
        normalize_profile_csv_file,
    )
    from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display
    from ui.consumption_display.adapters import bundle_from_csv_validation
    from ui.consumption_display.aggregation import (
        annual_kwh_actual,
        annual_kwh_from_bundle,
    )

    try:
        modeled_profile = {
            "annual_kwh": annual_kwh,
            "baseload_kwh": preview["baseload_kwh"],
            "consumers": resolved,
            "total_profile_csv": active_path,
            "pv_profile_csv": pv_path,
        }
        try:
            series = load_hourly_profile_csv(active_path)
        except ValueError:
            series = normalize_profile_csv_file(active_path)

        zero_bl_profile = {**modeled_profile, "baseload_kwh": 0.0}
        probe = bundle_from_csv_validation(series, zero_bl_profile)
        ist_annual = annual_kwh_actual(probe)
        model_consumers = annual_kwh_from_bundle(probe)
        trimmed = trim_baseload_floor_to_match_ist(
            float(annual_kwh),
            resolved,
            ist_annual,
            model_consumer_kwh=model_consumers,
        )
        modeled_profile = {
            **modeled_profile,
            "baseload_kwh": trimmed["baseload_kwh"],
        }
        st.caption(
            f"Grundlast an Ist angepasst: {trimmed['baseload_kwh']:.0f} kWh/a "
            f"(Ziel Ist {trimmed['ist_annual_kwh']:.0f} kWh; "
            f"effektive Untergrenze {100.0 * trimmed['floor_fraction']:.2f} %, "
            f"mindestens 1 %)."
        )
        render_consumption_display(
            ConsumptionDisplayMode.CSV_VALIDATION,
            key_prefix=f"house_profile_csv_{preview_id}",
            profile=modeled_profile,
            csv_series=series,
            annual_kwh=float(annual_kwh),
            reset_token=(
                f"{active_path}:{pv_path}:{trimmed['baseload_kwh']:.3f}:"
                f"{trimmed['ist_annual_kwh']:.3f}"
            ),
        )
    except (ValueError, OSError) as exc:
        st.error(f"CSV konnte nicht ausgewertet werden: {exc}")
