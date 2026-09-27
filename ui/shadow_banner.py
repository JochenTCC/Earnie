"""Shadow Mode UI banner and helpers (2.7.f S3)."""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from runtime_store.shadow.cycle import feed_health
from runtime_store.shadow.mode import is_shadow_mode
from runtime_store.shadow.writes import read_shadow_writes
from version import __version__


def render_shadow_banner() -> None:
    """Persistent banner on every page while Shadow Mode is active."""
    if not is_shadow_mode():
        return
    health = feed_health()
    age = health.get("heartbeat_age_sec")
    age_txt = f"{int(age)} s" if isinstance(age, (int, float)) else "?"
    hb = health.get("heartbeat_ts") or "?"
    stand = hb
    if isinstance(hb, str) and hb.endswith("Z"):
        try:
            dt = datetime.fromisoformat(hb.replace("Z", "+00:00"))
            stand = dt.astimezone().strftime("%H:%M:%S")
        except ValueError:
            stand = hb
    msg = (
        f"**Shadow-Modus** — Eingänge aus Prod-Feed "
        f"(Stand {stand}, Alter {age_txt}), keine Schreibzugriffe, "
        f"Konfiguration schreibgeschützt"
    )
    if health.get("stale"):
        st.warning(msg + " — **Prod-Feed veraltet**")
    else:
        st.info(msg)
    prod_ver = health.get("prod_version") or "?"
    st.caption(f"Shadow v{__version__} · Prod v{prod_ver}")


def render_shadow_would_write_table(*, limit: int = 50) -> None:
    """Show recent shadow_writes.jsonl rows (would-write log)."""
    if not is_shadow_mode():
        return
    rows = read_shadow_writes(limit=limit)
    st.subheader("Shadow — would write")
    if not rows:
        st.caption("Noch keine blockierten Schreibvorgänge in dieser Runtime.")
        return
    display = [
        {
            "Zeit": r.get("ts", ""),
            "cycle_seq": r.get("cycle_seq", ""),
            "Backend": r.get("backend", ""),
            "Ziel": r.get("target", ""),
            "Wert": str(r.get("value", "")),
            "Quelle": r.get("source", ""),
        }
        for r in reversed(rows)
    ]
    st.dataframe(display, hide_index=True, width="stretch")


def render_shadow_feed_connection_note() -> None:
    """Replace live backend probes with feed status on Smarthome page."""
    if not is_shadow_mode():
        return
    health = feed_health()
    st.info("Shadow — Feed (kein Backend-Probe)")
    st.caption(
        f"cycle_seq={health.get('cycle_seq')} · "
        f"heartbeat_age={health.get('heartbeat_age_sec')} · "
        f"backend={health.get('ehal_backend') or '?'}"
    )
