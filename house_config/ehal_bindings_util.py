"""Small helpers shared by the EHAL binding migration modules (split from ehal_bindings)."""
from __future__ import annotations



def _nonempty(value: object) -> str:
    return str(value or "").strip()


def _put_binding(bindings: dict[str, str], field: str, address: object) -> None:
    name = _nonempty(address)
    if field and name and field not in bindings:
        bindings[field] = name
