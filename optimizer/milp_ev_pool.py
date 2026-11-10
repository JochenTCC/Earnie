"""Pool constraints of dynamic EVs that are not assigned to a wallbox (multi-EV M4, D8).

A dynamic EV that is not plugged in may charge at any free wallbox it may use
(``house_config.wallboxes.pool_dynamic_ev_view``: :data:`VIEW_POOL_KEY`). Picking one
wallbox per car would be a guess, so the MILP only keeps the plan physically possible:
per slot, the charging cars must fit onto distinct free wallboxes.

For a set ``U`` of free wallboxes, the cars that may use only wallboxes of ``U`` cannot
charge more than ``|U|`` at a time (Hall's condition on the on-variables; it holds for every
``U`` exactly when the charging cars of a slot can each get their own wallbox). Their summed
power stays below the summed maximum power of ``U``. The constraints reuse the EVs' existing
on-variables and add no binaries. Wallboxes are grouped by the cars that share them; each
group enumerates its wallbox subsets, so a group is limited to :data:`MAX_POOL_WALLBOXES`.
"""
from __future__ import annotations

import logging
from itertools import combinations
from typing import Any

import pulp

from house_config.wallboxes import VIEW_DYNAMIC_KEY, VIEW_POOL_KEY, wallbox_max_power_kw

from .milp_consumer_vars import _flex_power_at_t
from .milp_horizon_types import MilpHorizonModel

logger = logging.getLogger(__name__)

MAX_POOL_WALLBOXES = 8


def _pool_evs(model: MilpHorizonModel) -> list[dict[str, Any]]:
    return [
        c
        for c in model.planned_consumers
        if c.get(VIEW_POOL_KEY) and str(c["id"]) in model.consumer_on
    ]


def _groups(evs: list[dict[str, Any]]) -> list[tuple[list[dict[str, Any]], list[str]]]:
    """Connected groups (EVs, wallbox ids) of EVs that share free wallboxes."""
    remaining = list(evs)
    out: list[tuple[list[dict[str, Any]], list[str]]] = []
    while remaining:
        group = [remaining.pop(0)]
        boxes = set(group[0][VIEW_POOL_KEY])
        grew = True
        while grew:
            grew = False
            for ev in list(remaining):
                if boxes & set(ev[VIEW_POOL_KEY]):
                    group.append(ev)
                    boxes |= set(ev[VIEW_POOL_KEY])
                    remaining.remove(ev)
                    grew = True
        out.append((group, sorted(boxes)))
    return out


def _wallbox_max_kw(evs: list[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for ev in evs:
        for wallbox in ev.get(VIEW_DYNAMIC_KEY) or []:
            out.setdefault(wallbox["id"], wallbox_max_power_kw(wallbox))
    return out


def add_ev_pool_constraints(model: MilpHorizonModel) -> int:
    """Add the D8 pool constraints for every slot; returns the number of constraints."""
    evs = _pool_evs(model)
    if not evs:
        return 0
    max_kw = _wallbox_max_kw(evs)
    added = 0
    for group, boxes in _groups(evs):
        if len(boxes) > MAX_POOL_WALLBOXES:
            raise ValueError(
                f"Dynamische E-Autos {sorted(str(e['id']) for e in group)} teilen sich "
                f"{len(boxes)} Wallboxen; die Pool-Planung unterstützt höchstens "
                f"{MAX_POOL_WALLBOXES} Wallboxen je Gruppe."
            )
        subsets: list[tuple[tuple[str, ...], list[dict[str, Any]]]] = []
        for size in range(1, len(boxes) + 1):
            for subset in combinations(boxes, size):
                inside = set(subset)
                members = [e for e in group if set(e[VIEW_POOL_KEY]) <= inside]
                if not members:
                    continue
                full = size == len(boxes)
                # Count: only binding when more cars than wallboxes; power: whole group.
                if len(members) > size or (full and len(members) > 1):
                    subsets.append((subset, members))
        for t in range(model.horizon):
            for subset, members in subsets:
                if len(members) > len(subset):
                    model.prob += (
                        pulp.lpSum(model.consumer_on[str(e["id"])][t] for e in members)
                        <= len(subset),
                        f"ev_pool_n_{'_'.join(subset)}_{t}",
                    )
                    added += 1
                if len(subset) == len(boxes) and len(members) > 1:
                    model.prob += (
                        pulp.lpSum(
                            _flex_power_at_t(
                                e,
                                model.consumer_on,
                                model.consumer_p,
                                model.consumer_milp_charge_kw[str(e["id"])],
                                t,
                            )
                            for e in members
                        )
                        <= sum(max_kw[w] for w in subset),
                        f"ev_pool_kw_{'_'.join(subset)}_{t}",
                    )
                    added += 1
    logger.debug("MILP: %s Pool-Nebenbedingungen für dynamische E-Autos.", added)
    return added
