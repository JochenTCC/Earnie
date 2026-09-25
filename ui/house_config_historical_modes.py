"""Historical CSV mode renderers (gesamt/component/balance/energiemonitor)."""
from __future__ import annotations

import config
from ui.house_config_historical_csv import _render_ist_vs_modell

from pathlib import Path

import streamlit as st

from ui.form_layout import labeled_text_input
from ui.house_config_io import (
    apply_csv_path_pending,
    csv_upload_widget_key,
    queue_csv_path_update,
    save_balance_total_from_component_paths,
    save_energiemonitor_profile_csvs,
    save_profile_consumption_csv,
    single_csv_upload,
)

_SOURCE_SEPARATE = "separate"
_SOURCE_ENERGIEMONITOR = "energiemonitor"
_SOURCE_BALANCE = "balance"
_SOURCE_LABELS = {
    _SOURCE_SEPARATE: (
        "Getrennte CSVs (Lastprofil + optional PV-Erzeugungsprofil)"
    ),
    _SOURCE_ENERGIEMONITOR: (
        "Loxone Energiemonitor - Leistungsprofile "
        "(PV + Batterie + Netz + Last)"
    ),
    _SOURCE_BALANCE: (
        "Bilanz - Leistungsprofile (PV + Batterie + Netz → Last)"
    ),
}
_VALID_SOURCES = frozenset(_SOURCE_LABELS)

_DIST_EQUAL = "equal"
_DIST_MONTHLY = "monthly"
_DIST_LABELS = {
    _DIST_EQUAL: "Jahres-Rest gleichmäßig",
    _DIST_MONTHLY: "Monats-Rest je Monat",
}



def session_keys(preview_id: str) -> dict[str, str]:
    return {
        "source": f"house_profile_hist_source_{preview_id}",
        "verbrauch": f"house_profile_csv_path_{preview_id}",
        "pv": f"house_profile_pv_csv_path_{preview_id}",
        "battery": f"house_profile_battery_csv_path_{preview_id}",
        "grid": f"house_profile_grid_csv_path_{preview_id}",
        "baseload_dist": f"house_profile_baseload_dist_{preview_id}",
    }

def _render_gesamtverbraeuche(
    *,
    preview_id: str,
    annual_kwh: float,
    resolved: list[dict],
    preview: dict,
    active_path: str,
    pv_path: str,
    battery_path: str,
    grid_path: str,
    balance_series: list[tuple[str, float]] | None,
    reset_extra: str,
) -> None:
    """Monatsverbrauch + stündlicher Verlauf — always visible."""
    from runtime_store.persist_paths import resolve_config_prefixed_path
    from ui.consumption_display import ConsumptionDisplayMode, render_consumption_display

    st.subheader("Gesamt-Lastverhalten")
    st.caption(
        "Monatsverbrauch und stündlicher Verlauf. Mit Lastprofil-CSV "
        "(direkt, Energiemonitor oder Bilanz): Ist vs. Modell; "
        "ohne CSV nur das modellierte Hausprofil."
    )

    has_ist = balance_series is not None
    if not has_ist and active_path:
        if Path(resolve_config_prefixed_path(active_path)).is_file():
            has_ist = True
        else:
            st.warning(f"Lastprofil-CSV nicht gefunden: `{active_path}`")

    if has_ist:
        _render_ist_vs_modell(
            active_path=active_path
            or f"bilanz:{pv_path}|{battery_path}|{grid_path}",
            preview_id=preview_id,
            annual_kwh=annual_kwh,
            resolved=resolved,
            preview=preview,
            pv_path=pv_path,
            csv_series=balance_series,
            reset_extra=reset_extra,
        )
        return

    modeled_profile = {
        "annual_kwh": annual_kwh,
        "baseload_kwh": preview["baseload_kwh"],
        "consumers": resolved,
    }
    render_consumption_display(
        ConsumptionDisplayMode.MODELED_PROFILE,
        key_prefix=f"house_profile_gesamt_{preview_id}",
        profile=modeled_profile,
        annual_kwh=float(annual_kwh),
        reset_token=(
            f"model:{preview_id}:{annual_kwh:.0f}:{preview['baseload_kwh']:.0f}:"
            f"{len(resolved)}"
        ),
    )

def _component_upload_keys(path_key: str) -> dict[str, str]:
    return {
        "input": f"{path_key}_input",
        "pending": f"{path_key}_pending",
        "upload_base": f"{path_key}_upload",
        "nonce": f"{path_key}_upload_nonce",
        "flash": f"{path_key}_flash",
    }

def _render_component_path_input(
    path_key: str,
    *,
    input_key: str,
    label: str,
    help_path: str,
    invert_key: str | None,
) -> str:
    """CSV path text input, optionally preceded by a sign-invert checkbox."""
    path_label = f"CSV-Pfad {label}"
    if invert_key is None:
        return labeled_text_input(
            path_label,
            value=st.session_state.get(path_key, ""),
            key=input_key,
            help=help_path,
        )
    invert_col, label_col, input_col = st.columns(
        [1.6, 1.4, 3.0],
        vertical_alignment="center",
    )
    with invert_col:
        st.checkbox(
            f"Vorzeichen {label} umkehren",
            value=False,
            key=invert_key,
        )
    label_col.markdown(path_label)
    return input_col.text_input(
        path_label,
        value=st.session_state.get(path_key, ""),
        key=input_key,
        help=help_path,
        label_visibility="collapsed",
    )

def _render_component_upload_row(
    label: str,
    *,
    path_key: str,
    ckeys: dict[str, str],
) -> tuple[object | None, bool]:
    up_col, clear_col = st.columns([4, 1], vertical_alignment="bottom")
    with up_col:
        upload = single_csv_upload(
            f"{label}-CSV hochladen",
            key=csv_upload_widget_key(ckeys["upload_base"], ckeys["nonce"]),
            help=f"Nur eine CSV-Datei für {label}.",
        )
    with clear_col:
        clear = st.button(
            "Zuordnung entfernen",
            key=f"{path_key}_clear",
        )
    return upload, clear

def _save_component_csv(
    upload,
    *,
    preview_id: str,
    role: str,
    preserve_sign: bool,
) -> str:
    if preserve_sign:
        return _save_signed_component_csv(
            preview_id,
            upload.getvalue(),
            upload.name,
            role=role,
        )
    return save_profile_consumption_csv(
        preview_id,
        upload.getvalue(),
        upload.name,
        role=role,
    )

def _render_component_upload(
    *,
    preview_id: str,
    path_key: str,
    label: str,
    role: str,
    help_path: str,
    preserve_sign: bool = False,
    invert_key: str | None = None,
) -> None:
    ckeys = _component_upload_keys(path_key)

    apply_csv_path_pending(ckeys["pending"], path_key, ckeys["input"])
    if ckeys["input"] not in st.session_state:
        st.session_state[ckeys["input"]] = st.session_state.get(path_key, "")

    flash = st.session_state.pop(ckeys["flash"], None)
    if flash:
        st.success(flash)

    path = _render_component_path_input(
        path_key,
        input_key=ckeys["input"],
        label=label,
        help_path=help_path,
        invert_key=invert_key,
    )
    st.session_state[path_key] = path.strip()
    upload, clear = _render_component_upload_row(
        label, path_key=path_key, ckeys=ckeys
    )
    if upload is not None:
        try:
            saved = _save_component_csv(
                upload,
                preview_id=preview_id,
                role=role,
                preserve_sign=preserve_sign,
            )
            queue_csv_path_update(
                ckeys["pending"],
                saved,
                upload_nonce_key=ckeys["nonce"],
                flash_key=ckeys["flash"],
                flash_message=f"{label} gespeichert und normalisiert: `{saved}`",
            )
            st.rerun()
        except (ValueError, OSError, FileNotFoundError) as exc:
            st.error(f"{label}-CSV ungültig: {exc}")
    if clear:
        queue_csv_path_update(ckeys["pending"], "", upload_nonce_key=ckeys["nonce"])
        st.rerun()

def _save_signed_component_csv(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    role: str,
) -> str:
    """Normalize bipolar battery/grid series without majority-sign flip."""
    from house_config.consumption_csv import (
        MIN_HOURS_IMPORT,
        detect_and_load_grid_raw_series,
        detect_and_load_raw_series,
        normalize_hourly_power_kw,
        write_canonical_hourly_csv,
    )
    from runtime_store.persist_paths import resolve_uploads_dir

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(filename).stem or role
    target = uploads_dir / f"{profile_id}_{role}_{stem}_resampled.csv"
    target.write_bytes(content)
    portable = f"config/uploads/{target.name}"
    if role == "grid":
        series = detect_and_load_grid_raw_series(portable)
    else:
        series = detect_and_load_raw_series(portable)
    rows = normalize_hourly_power_kw(
        series,
        min_hours=MIN_HOURS_IMPORT,
        source=portable,
        preserve_sign=True,
    )
    write_canonical_hourly_csv(portable, rows)
    return portable

def _render_separate_mode(preview_id: str, keys: dict[str, str]) -> None:
    st.markdown("**Lastprofil [kW] (Gesamt)**")
    _render_component_upload(
        preview_id=preview_id,
        path_key=keys["verbrauch"],
        label="Lastprofil",
        role="verbrauch",
        help_path="Relativer Pfad, z. B. config/uploads/mein_haushalt_lastprofil.csv",
    )
    st.markdown("**PV-Erzeugungsprofil [kW] (optional, Summe aller Anlagen)**")
    _render_component_upload(
        preview_id=preview_id,
        path_key=keys["pv"],
        label="PV",
        role="pv",
        help_path="Optional. Relativer Pfad zum PV-Erzeugungsprofil.",
    )

def _render_balance_mode(preview_id: str, keys: dict[str, str]) -> None:
    st.caption(
        "**Bilanz:** `P_Ges = P_PV + P_Batt + P_Grid`. "
        "Positiv bei Batterie/Netz = Leistung **in** das Haussystem "
        "(Entladen / Netzbezug). Negativ = Laden / Einspeisung. "
        "PV und Netz sind Pflicht; Batterie optional (fehlt → 0 kW). "
        "Sobald PV und Netz vorliegen, wird das Lastprofil automatisch "
        "abgeleitet und als Gesamt-CSV gespeichert."
    )
    invert_pv_key = f"house_profile_balance_invert_pv_{preview_id}"
    invert_batt_key = f"house_profile_balance_invert_batt_{preview_id}"
    invert_grid_key = f"house_profile_balance_invert_grid_{preview_id}"

    st.markdown("**PV-Erzeugungsprofil [kW] (Pflicht)**")
    _render_component_upload(
        preview_id=preview_id,
        path_key=keys["pv"],
        label="PV",
        role="pv",
        help_path="Pflicht für Bilanz-Import.",
        invert_key=invert_pv_key,
    )
    st.markdown("**Batterie-Leistung**")
    _render_component_upload(
        preview_id=preview_id,
        path_key=keys["battery"],
        label="Batterie",
        role="battery",
        help_path="+ = Entladen in das Haussystem.",
        preserve_sign=True,
        invert_key=invert_batt_key,
    )
    st.markdown("**Netz-Leistung**")
    _render_component_upload(
        preview_id=preview_id,
        path_key=keys["grid"],
        label="Netz",
        role="grid",
        help_path="+ = Netzbezug in das Haussystem.",
        preserve_sign=True,
        invert_key=invert_grid_key,
    )

    invert_pv = bool(st.session_state.get(invert_pv_key, False))
    invert_batt = bool(st.session_state.get(invert_batt_key, False))
    invert_grid = bool(st.session_state.get(invert_grid_key, False))

    pv = str(st.session_state.get(keys["pv"], "") or "").strip()
    batt = str(st.session_state.get(keys["battery"], "") or "").strip()
    grid = str(st.session_state.get(keys["grid"], "") or "").strip()
    _maybe_persist_balance_total(
        preview_id=preview_id,
        keys=keys,
        pv_path=pv,
        battery_path=batt,
        grid_path=grid,
        invert_pv=invert_pv,
        invert_battery=invert_batt,
        invert_grid=invert_grid,
    )

    if st.session_state.get(keys["verbrauch"]):
        st.caption(
            f"Abgeleitetes Lastprofil: `{st.session_state[keys['verbrauch']]}`"
        )

def _maybe_persist_balance_total(
    *,
    preview_id: str,
    keys: dict[str, str],
    pv_path: str,
    battery_path: str,
    grid_path: str,
    invert_pv: bool,
    invert_battery: bool,
    invert_grid: bool,
) -> None:
    """Write derived Gesamtverbrauch when PV + Netz are present (Batterie optional)."""
    if not (pv_path and grid_path):
        return
    fingerprint = (
        f"{pv_path}|{battery_path}|{grid_path}|"
        f"{invert_pv:d}|{invert_battery:d}|{invert_grid:d}"
    )
    fp_key = f"house_profile_balance_fp_{preview_id}"
    current = str(st.session_state.get(keys["verbrauch"], "") or "").strip()
    if st.session_state.get(fp_key) == fingerprint and current:
        return
    try:
        result = save_balance_total_from_component_paths(
            preview_id,
            pv_path=pv_path,
            battery_path=battery_path,
            grid_path=grid_path,
            invert_pv=invert_pv,
            invert_battery=invert_battery,
            invert_grid=invert_grid,
        )
    except (ValueError, OSError, FileNotFoundError) as exc:
        st.error(f"Bilanz ungültig: {exc}")
        return
    total = str(result["total_profile_csv"])
    st.session_state[keys["verbrauch"]] = total
    input_key = f"{keys['verbrauch']}_input"
    if input_key in st.session_state:
        st.session_state[input_key] = total
    st.session_state[fp_key] = fingerprint
    clipped = int(result.get("clipped_hours", 0) or 0)
    if clipped:
        st.warning(
            f"{clipped} Stunden mit negativem P_Ges auf 0 gekappt "
            "(Vorzeichen prüfen)."
        )

_EM_SLOTS = ("verbrauch", "pv", "battery", "grid")
_EM_CAPTION_LABELS = (
    ("verbrauch", "Lastprofil"),
    ("pv", "PV-Erzeugungsprofil"),
    ("battery", "Batterie"),
    ("grid", "Netz"),
)
_EM_MISSING_HINTS = (
    ("pv", "PV", " (keine Produktionsspalte — PV leer)"),
    ("battery", "Batterie", " (keine Batterie-Spalte — Batterie leer)"),
    ("grid", "Netz", " (keine Energieversorger-Spalte — Netz leer)"),
)

def _em_set_paths(keys: dict[str, str], values: dict[str, str]) -> None:
    """Write both the store key and its `_input` widget twin per component."""
    for slot in _EM_SLOTS:
        st.session_state[keys[slot]] = values[slot]
        st.session_state[f"{keys[slot]}_input"] = values[slot]

def _em_flash_message(values: dict[str, str]) -> str:
    msg = f"Lastprofil: `{values['verbrauch']}`"
    for slot, label, missing in _EM_MISSING_HINTS:
        if values[slot]:
            msg += f"; {label}: `{values[slot]}`"
        else:
            msg += missing
    return msg

def _bump_nonce(nonce_key: str) -> None:
    st.session_state[nonce_key] = int(st.session_state.get(nonce_key, 0) or 0) + 1

def _store_energiemonitor_upload(
    upload,
    *,
    preview_id: str,
    keys: dict[str, str],
    flash_key: str,
    nonce_key: str,
) -> None:
    try:
        result = save_energiemonitor_profile_csvs(
            preview_id,
            upload.getvalue(),
            upload.name,
        )
        values = {
            "verbrauch": result["total_profile_csv"],
            "pv": result.get("pv_profile_csv", ""),
            "battery": result.get("battery_profile_csv", ""),
            "grid": result.get("grid_profile_csv", ""),
        }
        _em_set_paths(keys, values)
        st.session_state[flash_key] = _em_flash_message(values)
        _bump_nonce(nonce_key)
        st.rerun()
    except (ValueError, OSError, FileNotFoundError) as exc:
        st.error(f"Energiemonitor-CSV ungültig: {exc}")

def _render_energiemonitor_captions(keys: dict[str, str]) -> None:
    for slot, label in _EM_CAPTION_LABELS:
        if st.session_state.get(keys[slot]):
            st.caption(f"{label}: `{st.session_state[keys[slot]]}`")

def _render_energiemonitor_mode(preview_id: str, keys: dict[str, str]) -> None:
    st.caption(
        "Erwartete Spalten: `Leistung Verbrauch [kW]` (Pflicht, direkt als "
        "Lastprofil), optional `Leistung Produktion [kW]` (PV), "
        "`Leistung Batterie` und `Leistung Energieversorger [kW]` (Netz). "
        "Lastprofil wird nicht aus Bilanz berechnet. SOC wird ignoriert."
    )
    em_upload_base = f"house_profile_em_csv_upload_{preview_id}"
    em_nonce = f"house_profile_em_csv_upload_nonce_{preview_id}"
    em_flash = f"house_profile_em_csv_flash_{preview_id}"

    flash = st.session_state.pop(em_flash, None)
    if flash:
        st.success(flash)

    up_col, clear_col = st.columns([4, 1], vertical_alignment="bottom")
    with up_col:
        upload = single_csv_upload(
            "Energiemonitor-CSV hochladen",
            key=csv_upload_widget_key(em_upload_base, em_nonce),
            help="Nur eine Energiemonitor-CSV-Datei.",
        )
    with clear_col:
        clear = st.button(
            "Zuordnung entfernen",
            key=f"house_profile_em_csv_clear_{preview_id}",
        )
    if upload is not None:
        _store_energiemonitor_upload(
            upload,
            preview_id=preview_id,
            keys=keys,
            flash_key=em_flash,
            nonce_key=em_nonce,
        )

    _render_energiemonitor_captions(keys)

    if clear:
        _em_set_paths(keys, {slot: "" for slot in _EM_SLOTS})
        _bump_nonce(em_nonce)
        st.rerun()

def _hourly_consumer_sum(consumer_series: dict[str, list[float]]) -> list[float]:
    if not consumer_series:
        return []
    length = len(next(iter(consumer_series.values())))
    totals = [0.0] * length
    for series in consumer_series.values():
        for index, value in enumerate(series):
            totals[index] += float(value)
    return totals

def _baseload_display_equal(probe, *, annual_kwh: float, resolved: list[dict]):
    """Flat annual residual baseload for Ist-vs-Modell charts."""
    from dataclasses import replace

    from data.consumption_profiles import MODELED_PROFILE_HOURS_PER_YEAR
    from house_config.baseload import trim_baseload_floor_to_match_ist
    from ui.consumption_display.aggregation import (
        annual_kwh_actual,
        annual_kwh_from_bundle,
    )

    trimmed = trim_baseload_floor_to_match_ist(
        float(annual_kwh),
        resolved,
        annual_kwh_actual(probe),
        model_consumer_kwh=annual_kwh_from_bundle(probe),
    )
    baseload_kw = float(trimmed["baseload_kwh"]) / MODELED_PROFILE_HOURS_PER_YEAR
    caption = (
        f"Grundlast an Ist angepasst: {trimmed['baseload_kwh']:.0f} kWh/a "
        f"(Ziel Ist {trimmed['ist_annual_kwh']:.0f} kWh; "
        f"effektive Untergrenze {100.0 * trimmed['floor_fraction']:.2f} %, "
        f"mindestens 1 %)."
    )
    return (
        replace(probe, baseload=[baseload_kw] * len(probe.timestamps)),
        float(trimmed["baseload_kwh"]),
        caption,
    )

def _baseload_display_monthly(probe, series: list[tuple[str, float]]):
    """Per-month residual baseload for Ist-vs-Modell charts."""
    from dataclasses import replace

    from house_config.baseload import monthly_aligned_baseload_kw

    ist_kw = list(probe.actual_total or [float(kw) for _, kw in series])
    consumer_kw = _hourly_consumer_sum(probe.consumer_series)
    if not consumer_kw:
        consumer_kw = [0.0] * len(probe.timestamps)
    baseload_series = monthly_aligned_baseload_kw(
        probe.timestamps,
        ist_kw,
        consumer_kw,
    )
    display_bl_kwh = sum(baseload_series)
    caption = (
        f"Monats-Rest-Grundlast: {display_bl_kwh:.0f} kWh "
        f"(Summe der Monatsreste; keine 1 %-Untergrenze; "
        f"Monate mit Verbrauchern > Ist ohne Basislast)."
    )
    return replace(probe, baseload=baseload_series), display_bl_kwh, caption
