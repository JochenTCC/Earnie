"""§5.3 soft-fail superset reads after Prod cycle writes."""
from __future__ import annotations

import logging
import time
from typing import Any

from runtime_store.shadow import feed as shadow_feed

logger = logging.getLogger(__name__)

_DEFAULT_BUDGET_SEC = 10.0


def run_after_cycle(*, budget_sec: float = _DEFAULT_BUDGET_SEC) -> None:
    """Read unbound config entities/IOs/channels still missing from this cycle."""
    if not shadow_feed.is_feed_recording_enabled():
        return
    deadline = time.monotonic() + max(0.1, float(budget_sec))
    seen = shadow_feed.keys_seen_this_cycle()
    try:
        import config

        backend = str(config.get("EHAL_BACKEND") or "").strip().lower()
    except Exception:  # noqa: BLE001
        return
    try:
        if backend == "ha":
            _superset_ha(seen, deadline)
        elif backend == "openems":
            _superset_openems(seen, deadline)
        else:
            _superset_loxone(seen, deadline)
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow feed superset failed: %s", exc)


def _budget_ok(deadline: float) -> bool:
    return time.monotonic() < deadline


def _house_profiles_doc() -> dict[str, Any]:
    from house_config.ha_ehal_bindings import load_house_profiles_for_ha

    doc = load_house_profiles_for_ha()
    return doc if isinstance(doc, dict) else {}


def _superset_loxone(seen: frozenset[str], deadline: float) -> None:
    """No Merker HTTP: Loxone live reads are VO push only (recorded on the cycle path)."""
    del seen, deadline
    return


def _superset_ha(seen: frozenset[str], deadline: float) -> None:
    from house_config.ha_ehal_bindings import aggregate_ha_entities
    from integrations.ehal_live import get_ha_adapter

    entities = aggregate_ha_entities(_house_profiles_doc())
    try:
        adapter = get_ha_adapter()
    except Exception:  # noqa: BLE001
        return
    for entity_id in sorted({str(v).strip() for v in entities.values() if v}):
        if not _budget_ok(deadline):
            return
        path = f"/api/states/{entity_id}"
        key = f"ha:get:{path}"
        if key in seen:
            continue
        try:
            adapter.read_state(entity_id)
        except Exception:  # noqa: BLE001
            continue


def _openems_channel_pairs(adapter: Any) -> list[tuple[str, str]]:
    ess = str(getattr(adapter.cfg, "ess_component", "ess0") or "ess0")
    evcs = str(getattr(adapter.cfg, "evcs_component", "") or "")
    pairs = [
        ("_sum", "GridActivePower"),
        ("_sum", "ProductionActivePower"),
        ("_sum", "EssSoc"),
        ("_sum", "EssActivePower"),
        (ess, "Soc"),
        (ess, "ActivePower"),
    ]
    if evcs:
        pairs.extend([(evcs, "ActivePower"), (evcs, "ChargePower")])
    return pairs


def _superset_openems(seen: frozenset[str], deadline: float) -> None:
    from integrations.ehal_live import get_openems_adapter

    try:
        adapter = get_openems_adapter()
    except Exception:  # noqa: BLE001
        return
    for component, channel in _openems_channel_pairs(adapter):
        if not _budget_ok(deadline):
            return
        path = f"/rest/channel/{component}/{channel}"
        key = f"openems:get:{path}"
        if key in seen:
            continue
        try:
            adapter.read_channel(component, channel)
        except Exception:  # noqa: BLE001
            continue
