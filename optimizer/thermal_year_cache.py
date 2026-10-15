"""Process-wide memo for 8760 h thermal year simulations.

Keys are built from the full call inputs (climate series hashed by content,
including their index), so a hit is always the result a fresh simulation
would return — no invalidation needed. Hits return fresh list copies so a
caller mutating its result cannot poison the cache.
"""
from __future__ import annotations

import hashlib
import json
import threading
from array import array
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import TypeVar

import numpy as np
import pandas as pd

DEFAULT_MAXSIZE = 16

T = TypeVar("T")


def fingerprint_series(values: object) -> tuple | None:
    """Content hash of a climate series (pandas Series incl. index, or float list)."""
    if values is None:
        return None
    digest = hashlib.blake2b(digest_size=16)
    if isinstance(values, pd.Series):
        hashed = pd.util.hash_pandas_object(values, index=True).to_numpy()
        digest.update(hashed.tobytes())
        meta = (str(values.dtype), str(values.index.dtype), len(values))
        return ("series", meta, digest.hexdigest())
    if isinstance(values, np.ndarray):
        floats = np.ascontiguousarray(values, dtype=np.float64)
        digest.update(floats.tobytes())
        return ("ndarray", floats.shape, digest.hexdigest())
    if isinstance(values, (list, tuple)):
        digest.update(array("d", (float(v) for v in values)).tobytes())
        return ("list", len(values), digest.hexdigest())
    raise TypeError(f"unsupported climate series type: {type(values)!r}")


def fingerprint_json(value: object) -> str:
    """Stable key for parameter dicts / lists (e.g. heat_storage, thermal_rc)."""
    return json.dumps(value, sort_keys=True, default=str, ensure_ascii=False)


def _key_value(name: str, value: object) -> Hashable:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (pd.Series, np.ndarray)):
        return fingerprint_series(value)
    if isinstance(value, (list, tuple)):
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
            return fingerprint_series(value)
        return fingerprint_json(value)
    if isinstance(value, dict):
        return fingerprint_json(value)
    raise TypeError(f"unsupported year-model argument {name}={type(value)!r}")


def call_key(kwargs: dict[str, object]) -> tuple:
    """Hashable key over all keyword arguments of a year-model call."""
    return tuple((name, _key_value(name, kwargs[name])) for name in sorted(kwargs))


class YearModelCache:
    """Bounded LRU keyed by hashable call fingerprints; thread-safe bookkeeping."""

    def __init__(self, name: str, *, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize <= 0:
            raise ValueError(f"maxsize must be > 0, got {maxsize}")
        self.name = name
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0
        self._entries: OrderedDict[Hashable, object] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(
        self,
        key: Hashable,
        compute: Callable[[], T],
        copy: Callable[[T], T],
    ) -> T:
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                self.hits += 1
                return copy(self._entries[key])  # type: ignore[arg-type]
            self.misses += 1
        value = compute()
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self.maxsize:
                self._entries.popitem(last=False)
        return copy(value)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses, "size": len(self._entries)}


HOUSE_YEAR_CACHE = YearModelCache("house_year_result")
THERMAL_RC_YEAR_CACHE = YearModelCache("thermal_rc_year")
# ThermalHorizon P1: derived parameters (small frozen dataclasses).
THERMAL_PARAMETERS_CACHE = YearModelCache("thermal_parameters", maxsize=64)


def clear_year_model_caches() -> None:
    HOUSE_YEAR_CACHE.clear()
    THERMAL_RC_YEAR_CACHE.clear()
    THERMAL_PARAMETERS_CACHE.clear()


def year_model_cache_stats() -> dict[str, dict[str, int]]:
    return {
        HOUSE_YEAR_CACHE.name: HOUSE_YEAR_CACHE.stats(),
        THERMAL_RC_YEAR_CACHE.name: THERMAL_RC_YEAR_CACHE.stats(),
        THERMAL_PARAMETERS_CACHE.name: THERMAL_PARAMETERS_CACHE.stats(),
    }
