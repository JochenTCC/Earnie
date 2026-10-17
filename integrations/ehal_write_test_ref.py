"""Late-bound access to the ``integrations.ehal_write_test`` facade.

Code split out of ``ehal_write_test`` resolves shared names (``ehal_live``,
``mapped_write_targets``, ...) through ``live`` at call time. That keeps
``patch("integrations.ehal_write_test.<name>")`` effective exactly like before the
split and avoids a circular import at module load.
"""
from __future__ import annotations

import importlib
from typing import Any


class _LiveFacade:
    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("integrations.ehal_write_test"), name)


live = _LiveFacade()
