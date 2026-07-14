#!/usr/bin/env python3
"""Evaluiert Preisprognose vs. Spiegelung (Walk-forward oder Holdout)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data.price_forecast_eval import (
    chronological_split_evaluate,
    evaluate_strategies,
    walk_forward_evaluate,
)
from data.price_forecast_model import (
    FEATURE_VARIANT_BASE,
    FEATURE_VARIANT_EXTENDED,
    fit_price_model,
    load_training_dataset,
    resolve_feature_variant,
)


def _default_dataset() -> Path:
    cache = Path("data/cache")
    candidates = sorted(cache.glob("price_training_*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(
            "Kein Training-Dataset in data/cache/. "
            "Zuerst: python -m scripts.build_price_training_dataset"
        )
    return candidates[-1]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preisprognose vs. Spiegelung (Spec: price-forecast-renewables.md)"
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument(
        "--mode",
        choices=("holdout", "walk_forward", "full"),
        default="holdout",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=7)
    parser.add_argument(
        "--feature-variant",
        choices=(FEATURE_VARIANT_BASE, FEATURE_VARIANT_EXTENDED),
        default=None,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        dataset_path = args.dataset or _default_dataset()
        peek = load_training_dataset(
            dataset_path,
            feature_variant=FEATURE_VARIANT_BASE,
        )
        variant = args.feature_variant or resolve_feature_variant(peek)
        frame = (
            peek
            if variant == FEATURE_VARIANT_BASE
            else load_training_dataset(dataset_path, feature_variant=variant)
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(f"Dataset: {dataset_path} ({len(frame)} h, {variant})")
    try:
        if args.mode == "holdout":
            report = chronological_split_evaluate(
                frame, train_ratio=args.train_ratio, feature_variant=variant
            )
        elif args.mode == "walk_forward":
            report = walk_forward_evaluate(
                frame,
                train_days=args.train_days,
                test_days=args.test_days,
                feature_variant=variant,
            )
        else:
            model = fit_price_model(frame, feature_variant=variant)
            report = evaluate_strategies(frame, model=model)
    except ValueError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
