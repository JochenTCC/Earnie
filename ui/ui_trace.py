"""Opt-in stderr trace for hunting Streamlit rerun loops (``EARNIE_UI_TRACE=1``, set by the e2e server)."""
from __future__ import annotations

import os
import sys
import time


def trace(message: str) -> None:
    if os.environ.get("EARNIE_UI_TRACE") != "1":
        return
    print(f"[ui-trace {time.monotonic():.3f}] {message}", file=sys.stderr, flush=True)
