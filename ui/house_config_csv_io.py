"""CSV upload / path-queue helpers for Hauskonfigurator."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from house_config.id_slug import slug_id
from runtime_store.persist_paths import resolve_uploads_dir

def _stable_upload_csv_name(
    profile_id: str,
    *,
    consumer_id: str = "",
    role: str = "",
) -> str:
    """Fallback filename per profile role / consumer when upload name is missing."""
    prefix = str(profile_id or "profile").strip() or "profile"
    consumer = str(consumer_id or "").strip()
    role_part = str(role or "").strip()
    if consumer:
        return f"{prefix}_{consumer}.csv"
    if role_part:
        return f"{prefix}_{role_part}.csv"
    return f"{prefix}_verbrauch.csv"

def _resampled_upload_csv_name(filename: str, *, fallback: str) -> str:
    """Build ``{original_stem}_resampled.csv`` from the uploaded basename."""
    # Strip both separators explicitly: the browser-supplied name may carry a
    # Windows-style path even when this server process runs on Linux (Path.name
    # only recognizes '/' there), and vice versa.
    normalized = str(filename or "").strip().replace("\\", "/")
    basename = Path(normalized).name
    if not basename:
        return fallback
    stem = Path(basename).stem.strip()
    if not stem or stem in (".", ".."):
        return fallback
    if stem.lower().endswith("_resampled"):
        return f"{stem}.csv"
    return f"{stem}_resampled.csv"

def single_csv_upload(
    label: str,
    *,
    key: str,
    help: str | None = None,
):
    """Streamlit CSV uploader that accepts exactly one file.

    Returns the uploaded file, or None if empty / rejected (more than one file).
    """
    import streamlit as st

    upload = st.file_uploader(
        label,
        type=["csv"],
        accept_multiple_files=False,
        key=key,
        help=help or "Nur eine CSV-Datei erlaubt.",
    )
    if upload is None:
        return None
    if isinstance(upload, list):
        if len(upload) > 1:
            st.error("Nur eine CSV-Datei erlaubt.")
            return None
        return upload[0] if upload else None
    return upload

def apply_csv_path_pending(
    pending_key: str,
    path_key: str,
    input_key: str,
    *,
    use_key: str | None = None,
) -> None:
    """Apply queued path to canonical + text_input keys before widgets render."""
    import streamlit as st

    if pending_key not in st.session_state:
        return
    pending = str(st.session_state.pop(pending_key) or "")
    st.session_state[path_key] = pending
    st.session_state[input_key] = pending
    if use_key is not None and not pending:
        st.session_state[use_key] = False

def queue_csv_path_update(
    pending_key: str,
    path: str,
    *,
    upload_nonce_key: str | None = None,
    flash_key: str | None = None,
    flash_message: str | None = None,
) -> None:
    """Queue path/widget sync for next run; bump uploader nonce to drop sticky file."""
    import streamlit as st

    st.session_state[pending_key] = str(path or "")
    if upload_nonce_key is not None:
        st.session_state[upload_nonce_key] = int(
            st.session_state.get(upload_nonce_key, 0) or 0
        ) + 1
    if flash_key and flash_message:
        st.session_state[flash_key] = flash_message

def csv_upload_widget_key(base_key: str, nonce_key: str) -> str:
    """Stable base key + nonce so clearing/re-upload resets Streamlit file_uploader."""
    import streamlit as st

    nonce = int(st.session_state.get(nonce_key, 0) or 0)
    return f"{base_key}__n{nonce}"

def save_profile_consumption_csv(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    consumer_id: str = "",
    normalize: bool = True,
    min_hours: int = 0,
    role: str = "",
) -> str:
    """Speichert Verbrauchs-CSV unter uploads/ neben der aktiven Config; optional normalisiert.

    Target name is ``{original_stem}_resampled.csv`` (basename only). If ``filename``
    is empty/invalid, falls back to a stable ``{profile}_{role|consumer}.csv`` name.
    Same original basename re-uploaded overwrites that resampled file.
    Returns a portable ``config/uploads/…`` path for storage in house profiles.

    ``min_hours``: ``0`` / omitted → soft import floor (``MIN_HOURS_IMPORT``);
    pass ``MIN_HOURS_FULL_YEAR`` when a full year is required.
    """
    from house_config.consumption_csv import (
        MIN_HOURS_IMPORT,
        normalize_profile_csv_file,
    )

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    fallback = _stable_upload_csv_name(
        profile_id, consumer_id=consumer_id, role=role
    )
    target = uploads_dir / _resampled_upload_csv_name(filename, fallback=fallback)
    target.write_bytes(content)
    portable = f"config/uploads/{target.name}"
    if normalize:
        hours = min_hours if min_hours > 0 else MIN_HOURS_IMPORT
        normalize_profile_csv_file(portable, min_hours=hours)
    return portable

def save_energiemonitor_profile_csvs(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    min_hours: int = 0,
) -> dict[str, str]:
    """Import Energiemonitor → Verbrauch (+ optional PV/Batt/Netz) under uploads/."""
    from house_config.consumption_csv import (
        MIN_HOURS_IMPORT,
        import_energiemonitor_to_canonical,
    )

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "energiemonitor.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    raw_path = uploads_dir / f"{profile_id}_energiemonitor_raw_{safe_name}"
    raw_path.write_bytes(content)
    hours = min_hours if min_hours > 0 else MIN_HOURS_IMPORT
    verbrauch_dest = f"config/uploads/{profile_id}_energiemonitor_verbrauch.csv"
    produktion_dest = f"config/uploads/{profile_id}_energiemonitor_produktion.csv"
    battery_dest = f"config/uploads/{profile_id}_energiemonitor_battery.csv"
    grid_dest = f"config/uploads/{profile_id}_energiemonitor_grid.csv"
    return import_energiemonitor_to_canonical(
        raw_path.as_posix(),
        verbrauch_dest=verbrauch_dest,
        produktion_dest=produktion_dest,
        battery_dest=battery_dest,
        grid_dest=grid_dest,
        min_hours=hours,
    )

def save_energiemonitor_balance_profile_csvs(
    profile_id: str,
    content: bytes,
    filename: str,
    *,
    min_hours: int = 0,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> dict[str, object]:
    """Energiemonitor → Bilanz (PV+Batt+Grid) → derived Verbrauch."""
    from house_config.consumption_csv import (
        MIN_HOURS_IMPORT,
        import_energiemonitor_balance_to_canonical,
    )

    uploads_dir = Path(resolve_uploads_dir())
    uploads_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name or "energiemonitor.csv"
    if not safe_name.lower().endswith(".csv"):
        safe_name = f"{safe_name}.csv"
    raw_path = uploads_dir / f"{profile_id}_energiemonitor_balance_raw_{safe_name}"
    raw_path.write_bytes(content)
    hours = min_hours if min_hours > 0 else MIN_HOURS_IMPORT
    return import_energiemonitor_balance_to_canonical(
        raw_path.as_posix(),
        verbrauch_dest=f"config/uploads/{profile_id}_balance_verbrauch.csv",
        pv_dest=f"config/uploads/{profile_id}_balance_pv.csv",
        battery_dest=f"config/uploads/{profile_id}_balance_battery.csv",
        grid_dest=f"config/uploads/{profile_id}_balance_grid.csv",
        min_hours=hours,
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )

def save_balance_total_from_component_paths(
    profile_id: str,
    *,
    pv_path: str,
    battery_path: str,
    grid_path: str,
    min_hours: int = 0,
    invert_pv: bool = False,
    invert_battery: bool = False,
    invert_grid: bool = False,
) -> dict[str, object]:
    """Derive total_profile_csv from three already-stored component paths."""
    from house_config.consumption_csv import (
        MIN_HOURS_IMPORT,
        derive_and_write_balance_total,
    )

    hours = min_hours if min_hours > 0 else MIN_HOURS_IMPORT
    total_dest = f"config/uploads/{profile_id}_balance_verbrauch.csv"
    return derive_and_write_balance_total(
        pv_path=pv_path,
        battery_path=battery_path,
        grid_path=grid_path,
        total_dest=total_dest,
        min_hours=hours,
        invert_pv=invert_pv,
        invert_battery=invert_battery,
        invert_grid=invert_grid,
    )
