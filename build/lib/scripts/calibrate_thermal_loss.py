#!/usr/bin/env python3
"""Kalibriert heat_loss_kw_per_k – nutzt scripts.tune_thermal_model."""
from __future__ import annotations

import sys

from scripts.tune_thermal_model import main as tune_main


def main(argv: list[str] | None = None) -> int:
    return tune_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
