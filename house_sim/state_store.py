"""In-memory HA state objects and service write application."""
from __future__ import annotations

import copy
import threading
from typing import Any


WRITE_SERVICES = frozenset(
    {
        ("number", "set_value"),
        ("input_number", "set_value"),
        ("select", "select_option"),
    }
)


def _entity_domain(entity_id: str) -> str:
    return str(entity_id).split(".", 1)[0].strip().lower()


class StateStore:
    """Thread-safe map of entity_id → HA state object."""

    def __init__(self, entities: list[dict[str, Any]] | None = None) -> None:
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, Any]] = {}
        self._force_service_status: int | None = None
        for item in entities or []:
            self.upsert(item)

    def upsert(self, payload: dict[str, Any]) -> None:
        entity_id = str(payload.get("entity_id") or "").strip()
        if not entity_id:
            raise ValueError("HA state object requires entity_id")
        attrs = payload.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        with self._lock:
            self._states[entity_id] = {
                "entity_id": entity_id,
                "state": str(payload.get("state", "")),
                "attributes": dict(attrs),
            }

    def get(self, entity_id: str) -> dict[str, Any] | None:
        with self._lock:
            raw = self._states.get(entity_id)
            return copy.deepcopy(raw) if raw is not None else None

    def list_states(self) -> list[dict[str, Any]]:
        with self._lock:
            return [copy.deepcopy(v) for v in self._states.values()]

    def set_state(self, entity_id: str, state: str) -> None:
        with self._lock:
            current = self._states.get(entity_id)
            if current is None:
                raise KeyError(entity_id)
            current["state"] = str(state)

    def set_attribute(self, entity_id: str, key: str, value: Any) -> None:
        with self._lock:
            current = self._states.get(entity_id)
            if current is None:
                raise KeyError(entity_id)
            current["attributes"][key] = value

    def force_service_status(self, status: int | None) -> None:
        """When set, every service POST returns this HTTP status (tests)."""
        with self._lock:
            self._force_service_status = status

    def service_force_status(self) -> int | None:
        with self._lock:
            return self._force_service_status

    def apply_service(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> tuple[int, str]:
        """Apply HA service call. Returns (http_status, message)."""
        forced = self.service_force_status()
        if forced is not None:
            return forced, f"Forced HTTP {forced}"

        domain_l = str(domain).strip().lower()
        service_l = str(service).strip().lower()
        if (domain_l, service_l) not in WRITE_SERVICES:
            return 400, f"Unsupported service {domain_l}.{service_l}"

        entity_id = str(data.get("entity_id") or "").strip()
        if not entity_id:
            return 400, "Missing entity_id"
        if _entity_domain(entity_id) != domain_l:
            return 400, f"Entity domain mismatch for {entity_id}"

        with self._lock:
            current = self._states.get(entity_id)
            if current is None:
                return 404, f"Unknown entity {entity_id}"

            if service_l == "select_option":
                option = data.get("option")
                if option is None:
                    return 400, "Missing option"
                current["state"] = str(option)
            else:
                if "value" not in data:
                    return 400, "Missing value"
                current["state"] = str(data["value"])
            return 200, "ok"

    def numeric_state(self, entity_id: str) -> float | None:
        payload = self.get(entity_id)
        if payload is None:
            return None
        text = str(payload.get("state", "")).strip().replace(",", ".")
        if text.lower() in ("", "unavailable", "unknown", "none"):
            return None
        try:
            return float(text)
        except ValueError:
            return None
