"""Engine fingerprint for expected.json / reports."""
from __future__ import annotations

from typing import Any


def engine_fingerprint(*, solver_mode: str = "strict") -> dict[str, Any]:
    from version import __version__

    highspy_version = _highspy_version()
    return {
        "earnie_version": __version__,
        "solver": "highs",
        "solver_mode": solver_mode,
        "highspy": highspy_version,
        "EARNIE_CBC_STRICT": "1",
    }


def _highspy_version() -> str:
    try:
        import importlib.metadata as metadata

        return metadata.version("highspy")
    except Exception:  # noqa: BLE001
        return "unknown"
