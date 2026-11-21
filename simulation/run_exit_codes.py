"""Exit codes of ``scripts/run_backtesting.py`` as a process.

- ``0``: the run finished and wrote its log.
- ``1``: crash (an uncaught exception; Python's own exit code).
- ``EXIT_ABORTED`` (2): the run refused to start or stopped on its own check, e.g. a pending
  config migration, a config that does not load, stale consumption data or a bad argument.
  argparse uses the same code for a bad command line.
- ``EXIT_CANCELLED`` (130, ``simulation.backtesting_progress``): cancelled from the UI.

Light module (no config import), so the script can map an abort that happens while it loads
the config at import time.
"""
from __future__ import annotations

import sys

EXIT_ABORTED = 2


def aborted_exit(exc: SystemExit) -> SystemExit:
    """Map a deliberate ``SystemExit`` of the run to ``EXIT_ABORTED``.

    ``SystemExit("message")`` prints the message to stderr like Python does and exits with
    ``EXIT_ABORTED``; any other non-zero code becomes ``EXIT_ABORTED`` too. Code 0 / None
    stays a normal end.
    """
    code = exc.code
    if code is None or code == 0:
        return exc
    if not isinstance(code, int):
        print(code, file=sys.stderr, flush=True)
    return SystemExit(EXIT_ABORTED)
