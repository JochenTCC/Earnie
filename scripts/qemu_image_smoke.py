#!/usr/bin/env python3
"""
qemu_image_smoke.py — Import + tiny HiGHS smoke under constrained CPU (H2 / 2.6.k).

Intended to run *inside* a container image (app or add-on wrapper) with
OPENBLAS_NUM_THREADS=1. CI wraps this with qemu-user + -cpu kvm64-v1 / cortex-a72.

Usage (inside image):
  OPENBLAS_NUM_THREADS=1 python -m scripts.qemu_image_smoke
"""
from __future__ import annotations

import sys


def _check_imports() -> None:
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    import pyarrow  # noqa: F401
    import highspy  # noqa: F401
    import streamlit  # noqa: F401
    import optimizer  # noqa: F401
    import runtime_store  # noqa: F401
    print("imports: ok (numpy, pandas, pyarrow, highspy, streamlit, optimizer, runtime_store)")


def _small_highs_solve() -> None:
    import highspy

    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    # min x; 0 <= x <= 1
    h.addVar(0.0, 1.0)
    h.changeColCost(0, 1.0)
    h.run()
    status = h.getModelStatus()
    optimal = getattr(highspy.HighsModelStatus, "kOptimal", 7)
    if status != optimal:
        raise RuntimeError(f"HiGHS smoke failed: model status={status!r}")
    print("highs: ok (trivial LP)")


def main() -> int:
    _check_imports()
    _small_highs_solve()
    print("qemu_image_smoke: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
