"""Dynamic EVs in the Scenario Explorer and backtesting: first come, first served (multi-EV D9).

The simulation has no plug events, so a dynamic EV cannot be assigned the way the live engine
does it. D9 fixes the rule instead: the EVs are taken in the order of their arrival
(``car_available_from_hour`` of the ``weekday`` block; ties by EV Kennung). Each one gets the
first wallbox of its ``wallbox_ids`` whose cars so far have no charging window
(``car_available_from_hour`` … ``ready_by_hour``, daily) overlapping its own; it is then
planned as the pair with that wallbox (D2). An EV that finds no free wallbox is not planned.

The assignment holds for the whole run. The ``weekend`` block must give the same assignment,
else the run stops with a message (a per-day assignment would change a car's limits in the
middle of a night horizon). :func:`assign_dynamic_evs_fcfs` is a pure function of the
consumer list, so every SE call site that resolves the consumers gets the same result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RULE_TEXT = (
    "Wer zuerst kommt, lädt zuerst: Reihenfolge nach Ankunft (car_available_from_hour), "
    "bei Gleichstand nach Kennung; jedes Auto nimmt die erste erlaubte Wallbox, deren "
    "Ladefenster frei ist."
)


@dataclass(frozen=True)
class FcfsRow:
    ev_id: str
    wallbox_id: str | None
    available_from_hour: int
    ready_by_hour: int


def _window(consumer: dict[str, Any], day_key: str) -> tuple[int, int] | None:
    block = (consumer.get("charging_schedule") or {}).get(day_key)
    if not isinstance(block, dict) or not block:
        return None
    start = block.get("car_available_from_hour")
    end = block.get("ready_by_hour")
    if start is None or end is None:
        raise ValueError(
            f"Simulation: E-Auto '{consumer['id']}' mit dynamischer Wallbox-Zuordnung braucht "
            f"im Ladeplan ({day_key}) car_available_from_hour und ready_by_hour — daraus "
            "bestimmt der Scenario Explorer, welches Auto zuerst kommt."
        )
    return int(start) % 24, int(end) % 24


def _span(window: tuple[int, int]) -> tuple[int, int]:
    start, end = window
    return start, end + 24 if end <= start else end


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """Daily windows overlap (each repeats every 24 h)."""
    a0, a1 = _span(a)
    b0, b1 = _span(b)
    return any(a0 < b1 + shift and b0 + shift < a1 for shift in (-24, 0, 24))


def _assign(evs: list[dict[str, Any]], day_key: str) -> dict[str, tuple[str | None, tuple[int, int]]]:
    from house_config.wallboxes import dynamic_wallbox_ids

    windows = {str(ev["id"]): _window(ev, day_key) for ev in evs}
    if any(w is None for w in windows.values()):
        return {}
    order = sorted(evs, key=lambda ev: (windows[str(ev["id"])][0], str(ev["id"])))
    taken: dict[str, list[tuple[int, int]]] = {}
    out: dict[str, tuple[str | None, tuple[int, int]]] = {}
    for ev in order:
        ev_id = str(ev["id"])
        window = windows[ev_id]
        chosen = next(
            (
                wid
                for wid in dynamic_wallbox_ids(ev)
                if not any(_overlap(window, other) for other in taken.get(wid, []))
            ),
            None,
        )
        if chosen is not None:
            taken.setdefault(chosen, []).append(window)
        out[ev_id] = (chosen, window)
    return out


def fcfs_assignment(consumers: list[dict[str, Any]]) -> list[FcfsRow]:
    """D9 rows (arrival order) of the dynamic EVs in ``consumers``; ``[]`` without any."""
    from house_config.wallboxes import is_dynamic_ev

    evs = [c for c in consumers if str(c.get("type") or "") == "ev" and is_dynamic_ev(c)]
    if not evs:
        return []
    weekday = _assign(evs, "weekday")
    if not weekday:
        missing = sorted(str(ev["id"]) for ev in evs if _window(ev, "weekday") is None)
        raise ValueError(
            f"Simulation: E-Autos mit dynamischer Wallbox-Zuordnung ({', '.join(missing)}) "
            "brauchen einen Werktags-Ladeplan (car_available_from_hour, ready_by_hour)."
        )
    weekend = _assign(evs, "weekend")
    if weekend:
        differs = sorted(
            ev_id for ev_id, (wid, _w) in weekday.items() if weekend[ev_id][0] != wid
        )
        if differs:
            raise ValueError(
                "Simulation: Die Wallbox-Zuordnung „wer zuerst kommt“ ergibt am Wochenende "
                f"eine andere Wallbox als werktags für {', '.join(differs)}. Der Scenario "
                "Explorer ordnet einmal pro Lauf zu — Ankunftszeiten oder erlaubte Wallboxen "
                "so anpassen, dass beide Tagesarten dieselbe Zuordnung ergeben."
            )
    rows = [
        FcfsRow(ev_id=ev_id, wallbox_id=wid, available_from_hour=w[0], ready_by_hour=w[1])
        for ev_id, (wid, w) in weekday.items()
    ]
    return rows


def assign_dynamic_evs_fcfs(consumers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """``consumers`` with every dynamic EV planned as the pair of its D9 wallbox, or left out
    when no wallbox was free for it."""
    from house_config.wallboxes import assigned_dynamic_ev_view, is_dynamic_ev

    by_ev = {row.ev_id: row.wallbox_id for row in fcfs_assignment(consumers)}
    out: list[dict[str, Any]] = []
    for consumer in consumers:
        if str(consumer.get("type") or "") != "ev" or not is_dynamic_ev(consumer):
            out.append(consumer)
            continue
        wallbox_id = by_ev.get(str(consumer["id"]))
        if wallbox_id:
            out.append(assigned_dynamic_ev_view(consumer, wallbox_id))
    return out


def describe_fcfs(rows: list[FcfsRow]) -> list[str]:
    """German lines for the SE: which car charges where."""
    lines: list[str] = []
    for row in rows:
        window = f"{row.available_from_hour:02d}–{row.ready_by_hour:02d} Uhr"
        if row.wallbox_id:
            lines.append(f"{row.ev_id} → Wallbox {row.wallbox_id} ({window})")
        else:
            lines.append(f"{row.ev_id}: keine freie Wallbox ({window}) — wird nicht geladen")
    return lines
