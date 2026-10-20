"""Deprecated shim — use ``integrations.ehal_request_http`` (Binding Lx3).

URL path alias ``/ehal/loxone/status.json`` remains in the canonical module.
"""
from __future__ import annotations

import sys

from integrations import ehal_request_http as _impl

sys.modules[__name__] = _impl
