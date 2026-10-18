"""Thin HouseSim → Earnie push client (Binding P5d).

Pushes contract entity states to ``GET /ehal/telemetry/<id>/<v>`` and applies
``status.json`` setpoints onto HouseSim ``number.*`` entities. Earnie-facing;
keeps ``house_sim/core`` free of Earnie imports.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote

from ehal.push_signals import HEARTBEAT_ID
from house_sim.contract import ContractBundle
from house_sim.state_store import StateStore

logger = logging.getLogger(__name__)


class PushClient:
    """HTTP client for Earnie telemetry inbox + status.json."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str,
        timeout_s: float = 5.0,
    ) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        if not self.base_url:
            raise ValueError("push harness needs a non-empty Earnie base_url")
        self.token = str(token or "").strip()
        if not self.token:
            raise ValueError("push harness needs a non-empty push token")
        self.timeout_s = float(timeout_s)

    def _get(self, path: str) -> tuple[int, bytes]:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return int(resp.status), resp.read()
        except urllib.error.HTTPError as exc:
            return int(exc.code), exc.read() if exc.fp else b""

    def push_value(self, ehal_id: str, value: float | int | str) -> int:
        """Push one telemetry sample; returns HTTP status (204 = ok)."""
        qid = quote(str(ehal_id).strip(), safe=".")
        raw = quote(str(value), safe=".-")
        path = f"/ehal/telemetry/{qid}/{raw}?t={quote(self.token, safe='')}"
        status, _body = self._get(path)
        return status

    def push_heartbeat(self) -> int:
        return self.push_value(HEARTBEAT_ID, 1)

    def fetch_status(self) -> dict[str, Any]:
        path = f"/ehal/status.json?t={quote(self.token, safe='')}"
        status, body = self._get(path)
        if status != 200:
            raise RuntimeError(f"status.json HTTP {status}")
        data = json.loads(body.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise RuntimeError("status.json must be a JSON object")
        return data


def _numeric_state(store: StateStore, entity_id: str) -> float:
    payload = store.get(entity_id)
    if payload is None:
        raise KeyError(entity_id)
    return float(payload["state"])


def push_reads(bundle: ContractBundle, client: PushClient) -> list[tuple[str, int]]:
    """Push every activated read signal from the contract store."""
    results: list[tuple[str, int]] = []
    for sig in bundle.read_signals:
        entity_id = bundle.entity_by_ehal[sig.ehal_id]
        value = _numeric_state(bundle.store, entity_id)
        status = client.push_value(sig.ehal_id, value)
        results.append((sig.ehal_id, status))
    hb = client.push_heartbeat()
    results.append((HEARTBEAT_ID, hb))
    return results


def apply_status_setpoints(
    store: StateStore,
    status: dict[str, Any],
    write_entity_by_ehal: dict[str, str],
) -> list[str]:
    """Apply ``status.json`` write keys onto HouseSim number entities."""
    applied: list[str] = []
    for ehal_id, entity_id in write_entity_by_ehal.items():
        if ehal_id not in status:
            continue
        raw = status[ehal_id]
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"status.json {ehal_id!r} is not numeric: {raw!r}"
            ) from exc
        store.set_state(entity_id, str(value))
        applied.append(ehal_id)
    return applied


def push_cycle(bundle: ContractBundle, client: PushClient) -> dict[str, Any]:
    """One push + status apply cycle. Returns a small report dict."""
    push_results = push_reads(bundle, client)
    bad = [(qid, st) for qid, st in push_results if st not in (200, 204)]
    if bad:
        raise RuntimeError(f"telemetry push failed: {bad}")
    status = client.fetch_status()
    applied = apply_status_setpoints(
        bundle.store, status, bundle.write_entity_by_ehal
    )
    return {
        "pushed": [qid for qid, _ in push_results],
        "status_keys": sorted(status.keys()),
        "setpoints_applied": applied,
    }


class PushLoop:
    """Background periodic push (CLI contract mode)."""

    def __init__(
        self,
        bundle: ContractBundle,
        client: PushClient,
        *,
        interval_s: float = 10.0,
    ) -> None:
        self.bundle = bundle
        self.client = client
        self.interval_s = max(0.5, float(interval_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_report: dict[str, Any] | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("push loop already running")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="house-sim-push-loop",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=self.interval_s + 2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.last_report = push_cycle(self.bundle, self.client)
                self.last_error = None
                logger.info(
                    "house_sim push cycle ok: %s",
                    self.last_report.get("pushed"),
                )
            except Exception as exc:  # noqa: BLE001 — loop must keep ticking
                self.last_error = str(exc)
                logger.warning("house_sim push cycle failed: %s", exc)
            self._stop.wait(self.interval_s)


def sleep_interruptible(seconds: float, stop: threading.Event | None = None) -> None:
    """Sleep helper for CLI (tests can patch)."""
    if stop is None:
        time.sleep(seconds)
        return
    stop.wait(seconds)
