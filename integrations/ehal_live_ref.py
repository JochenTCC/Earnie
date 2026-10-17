"""Late-bound access to the ``integrations.ehal_live`` façade.

Code split out of ``ehal_live`` resolves shared names (``config``, adapter getters,
backend checks, ...) through ``live`` at call time. That keeps
``patch("integrations.ehal_live.<name>")`` effective exactly like before the split
and avoids a circular import at module load.
"""
from __future__ import annotations

import importlib
from typing import Any


class _LiveFacade:
    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("integrations.ehal_live"), name)


live = _LiveFacade()
