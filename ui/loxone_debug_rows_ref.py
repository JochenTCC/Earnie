"""Late-bound access to the ``ui.loxone_debug_rows`` facade.

Write-row code split out of ``loxone_debug_rows`` resolves ``build_loxone_setpoint_io_index``
and ``loxone_write_field_to_io`` through ``live`` at call time, so
``patch("ui.loxone_debug_rows.<name>")`` stays effective exactly like before the split.
"""
from __future__ import annotations

import importlib
from typing import Any


class _LiveFacade:
    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("ui.loxone_debug_rows"), name)


live = _LiveFacade()
