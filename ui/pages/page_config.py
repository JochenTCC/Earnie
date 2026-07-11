"""Konfigurations-Seite: Roh-JSON-Editor für config.json (Validierung + Schema)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import jsonschema
import streamlit as st

import config
from runtime_store.persist_paths import config_schema_file, resolve_config_json_path
from ui.config_forms import render_system_parameter_section
from ui.help_hint import render_page_title_with_help

_EDITOR_KEY = "config_json_editor"
_CONFIG_HELP = (
    "Roh-JSON-Editor für `config.json`. **Validieren** prüft Syntax und Schema, "
    "**Speichern** schreibt atomar und lädt die Konfiguration neu (`reinit_config`)."
)


def _read_config_text(path: str) -> str:
    """Liest config.json tolerant (UTF-8, Fallback cp1252)."""
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return Path(path).read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(
        f"'{path}' ist weder UTF-8 noch cp1252 lesbar — bitte als UTF-8 speichern."
    )


def _load_schema() -> dict | None:
    schema_path = config_schema_file()
    if not os.path.isfile(schema_path):
        return None
    with open(schema_path, encoding="utf-8") as handle:
        return json.load(handle)


def _validate_text(text: str) -> tuple[dict | None, str | None]:
    """Parst und validiert den Editor-Text. Liefert (data, fehlermeldung)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"Ungültiges JSON (Zeile {exc.lineno}, Spalte {exc.colno}): {exc.msg}"
    schema = _load_schema()
    if schema is None:
        return data, None
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        location = " → ".join(str(p) for p in exc.absolute_path) or "(Wurzel)"
        return None, f"Schema-Verletzung bei {location}: {exc.message}"
    return data, None


def _save_text(path: str, text: str) -> None:
    """Schreibt den Text atomar (Temp-Datei + os.replace)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def _render_editor(path: str) -> None:
    if _EDITOR_KEY not in st.session_state:
        st.session_state[_EDITOR_KEY] = _read_config_text(path)
    st.text_area("config.json", key=_EDITOR_KEY, height=480)

    col_validate, col_save, col_reload = st.columns(3)
    if col_validate.button("Validieren"):
        _, error = _validate_text(st.session_state[_EDITOR_KEY])
        if error:
            st.error(error)
        else:
            st.success("JSON und Schema sind gültig.")
    if col_save.button("Speichern", type="primary"):
        _handle_save(path)
    if col_reload.button("Neu laden (Datei)"):
        st.session_state[_EDITOR_KEY] = _read_config_text(path)
        st.rerun()


def _handle_save(path: str) -> None:
    _, error = _validate_text(st.session_state[_EDITOR_KEY])
    if error:
        st.error(f"Nicht gespeichert — {error}")
        return
    try:
        _save_text(path, st.session_state[_EDITOR_KEY])
        config.reinit_config()
    except (OSError, ValueError) as exc:
        st.error(f"Speichern fehlgeschlagen: {exc}")
        return
    st.success("Gespeichert und Konfiguration neu geladen.")


def render() -> None:
    render_page_title_with_help("⚙️ Konfiguration", _CONFIG_HELP, key="config_scope_help")
    path = resolve_config_json_path()
    st.caption(f"Datei: `{path}`")

    with st.expander("Komfort-Ansicht: Live-Szenario (Entitäts-Referenzen)", expanded=False):
        render_system_parameter_section()

    st.subheader("Roh-JSON-Editor")
    try:
        _render_editor(path)
    except (OSError, ValueError) as exc:
        st.error(f"config.json konnte nicht gelesen werden: {exc}")
