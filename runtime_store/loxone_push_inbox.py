"""Deprecated shim — use ``runtime_store.ehal_push_inbox`` (Binding Lx3)."""
from __future__ import annotations

import sys

from runtime_store import ehal_push_inbox as _impl

sys.modules[__name__] = _impl
