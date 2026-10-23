"""Session memo for slow HK / shared consumption bundle builds."""
from __future__ import annotations

from collections.abc import Callable, MutableMapping
from typing import Any

import streamlit as st

from ui.auto_persist import payload_fingerprint
from ui.consumption_display.types import ConsumptionSeriesBundle

_SESSION_CACHE_KEY = "hk_consumption_bundle_cache"
_SPINNER_LABEL = "Modell-Jahresverbrauch wird berechnet…"


def fingerprint_modeled_profile(profile: dict) -> str:
    """Stable hash of the modeled-profile payload used for charts."""
    return payload_fingerprint(profile)


def _session_store() -> MutableMapping[str, ConsumptionSeriesBundle]:
    store = st.session_state.get(_SESSION_CACHE_KEY)
    if store is None:
        store = {}
        st.session_state[_SESSION_CACHE_KEY] = store
    return store


def get_or_build_consumption_bundle(
    cache_key: str,
    builder: Callable[[], ConsumptionSeriesBundle],
    *,
    store: MutableMapping[str, ConsumptionSeriesBundle] | None = None,
    show_spinner: bool = True,
    spinner_label: str = _SPINNER_LABEL,
) -> ConsumptionSeriesBundle:
    """Return a cached bundle or build it once (optional Streamlit spinner).

    Pass ``store`` in unit tests to avoid touching ``st.session_state``.
    """
    memo: MutableMapping[str, ConsumptionSeriesBundle]
    if store is not None:
        memo = store
    else:
        memo = _session_store()
    hit = memo.get(cache_key)
    if hit is not None:
        return hit
    if show_spinner and store is None:
        with st.spinner(spinner_label):
            bundle = builder()
    else:
        bundle = builder()
    memo[cache_key] = bundle
    return bundle


def modeled_profile_cache_key(profile: dict, *, extra: str = "") -> str:
    """Cache key for model-only Gesamt-Lastverhalten."""
    base = fingerprint_modeled_profile(profile)
    return f"modeled:{base}:{extra}" if extra else f"modeled:{base}"


def csv_validation_probe_cache_key(
    profile: dict,
    *,
    active_path: str,
    series_fingerprint: str,
) -> str:
    """Cache key for the Ist-vs-Modell probe (baseload_kwh forced to 0)."""
    return (
        f"csv_probe:{fingerprint_modeled_profile(profile)}:"
        f"{active_path}:{series_fingerprint}"
    )


def fingerprint_ist_series(series: list[tuple[str, float]]) -> str:
    """Fingerprint of loaded Ist CSV series (timestamps + values)."""
    # Sample endpoints + length keep the key small for multi-year CSVs.
    if not series:
        return payload_fingerprint([])
    n = len(series)
    sample: list[Any] = [n, series[0], series[n // 2], series[-1]]
    return payload_fingerprint(sample)
