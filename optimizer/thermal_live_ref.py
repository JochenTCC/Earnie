"""Late-bound access to the ``optimizer.thermal_live_store`` facade.

Code split out of ``thermal_live_store`` resolves shared names through ``live`` at
call time, so ``monkeypatch.setattr(thermal_live_store, "<name>", ...)`` stays
effective exactly like before the split and no circular import occurs at load.
"""
from __future__ import annotations

import importlib
from typing import Any


class _LiveFacade:
    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("optimizer.thermal_live_store"), name)


live = _LiveFacade()
