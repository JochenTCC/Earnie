#!/usr/bin/env python3
"""Vergleicht Preis-Modell base vs. extended (mit Last/Residuallast)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data.price_forecast_eval import compare_feature_variants
from data.price_forecast_model import FEATURE_VARIANT_BASE, FEATURE_VARIANT_EXTENDED, load_training_dataset


def _default_dataset() -> Path:
    cache = Path("data/cache")
    candidates = sorted(cache.glob("price_training_*.csv"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError("Kein Training-Dataset in data/cache/.")
    return candidates[-1]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Vergleich base (Wind/Solar/Wetter) vs. extended (+ Last/Residuallast)"
    )
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--train-days", type=int, default=90)
    parser.add_argument("--test-days", type=int, default=7)
    return parser.parse_args(argv)


def _summarize(report: dict) -> str:
    holdout = report.get("holdout", {})
    lines = [f"Dataset: {report.get('rows', '?')} h"]
    for variant in (FEATURE_VARIANT_BASE, FEATURE_VARIANT_EXTENDED):
        if variant not in holdout:
            continue
        entry = holdout[variant]
        model = entry.get("model", {})
        model_peak = entry.get("model_peak", {})
        mirror = entry.get("mirror", {})
        lines.append(
            f"{variant} Holdout MAE: Modell {model.get('mae_cent_kwh', '?'):.3f} | "
            f"Spiegel {mirror.get('mae_cent_kwh', '?'):.3f} | "
            f"Peak-MAE {model_peak.get('mae_cent_kwh', '?'):.3f}"
        )
    wf = report.get("walk_forward", {})
    for variant in (FEATURE_VARIANT_BASE, FEATURE_VARIANT_EXTENDED):
        if variant not in wf or "error" in wf[variant]:
            continue
        entry = wf[variant]
        lines.append(
            f"{variant} Walk-forward MAE: Modell {entry['mean_model_mae_cent_kwh']:.3f} | "
            f"Spiegel {entry['mean_mirror_mae_cent_kwh']:.3f} | "
            f"Delta {entry['mean_mae_delta_model_better']:+.3f}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        dataset_path = args.dataset or _default_dataset()
        frame = load_training_dataset(dataset_path, feature_variant=FEATURE_VARIANT_BASE)
        if "eu_load_mw" not in frame.columns:
            print(
                "Hinweis: Last-Spalten fehlen — zuerst "
                "python -m scripts.enrich_price_training_dataset <csv>",
                file=sys.stderr,
            )
            return 1
        frame = load_training_dataset(dataset_path, feature_variant=FEATURE_VARIANT_EXTENDED)
        report = compare_feature_variants(
            frame,
            train_ratio=args.train_ratio,
            train_days=args.train_days,
            test_days=args.test_days,
        )
    except (OSError, ValueError, FileNotFoundError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1

    print(_summarize(report))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
