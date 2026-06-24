#!/usr/bin/env python3
"""CLI: persistente Laufzeitdateien bootstrapen (wird auch vom Container-Entrypoint aufgerufen)."""
from __future__ import annotations

import logging
import sys

from runtime_store.bootstrap import BootstrapError, run


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        run()
    except BootstrapError as exc:
        print(f"Bootstrap abgebrochen: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
