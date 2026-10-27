"""Compare the rule engine with a turnover-only baseline by held-out archetype.

This is a descriptive synthetic benchmark. The rule thresholds are development
heuristics, so the result is not a blind holdout or real-football performance
claim. All five variants of each archetype stay in the same fold.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invisible_game import analyze_match, load_match_events  # noqa: E402


def _counts(rows: Iterable[tuple[int, int]]) -> dict[str, float | int]:
    pairs = list(rows)
    tp = sum(actual == 1 and predicted == 1 for actual, predicted in pairs)
    fp = sum(actual == 0 and predicted == 1 for actual, predicted in pairs)
    fn = sum(actual == 1 and predicted == 0 for actual, predicted in pairs)
    tn = sum(actual == 0 and predicted == 0 for actual, predicted in pairs)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "windows": len(pairs),
        "positive_windows": sum(actual for actual, _ in pairs),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def _choose_turnover_threshold(rows: list[dict[str, object]]) -> int:
    if not rows:
        raise ValueError("Cannot choose a baseline threshold without training rows")
    maximum = max(int(row["dangerous_turnovers"]) for row in rows)
    candidates = range(maximum + 2)
    scored = []
    for threshold in candidates:
        result = _counts(
            (
                int(row["actual"]),
                int(int(row["dangerous_turnovers"]) >= threshold),
            )
            for row in rows
        )
        scored.append((float(result["f1"]), float(result["precision"]), threshold))
    return max(scored)[2]


def run_evaluation(data_dir: Path = ROOT / "data") -> dict[str, object]:
    matches = list(csv.DictReader((data_dir / "matches.csv").open(encoding="utf-8-sig", newline="")))
    labels = list(csv.DictReader((data_dir / "ground_truth_labels.csv").open(encoding="utf-8-sig", newline="")))
    labels_by_key = {(row["match_id"], row["window_id"]): row for row in labels}
    rows: list[dict[str, object]] = []
    for match in matches:
        analysis = analyze_match(load_match_events(data_dir / "events.csv", match["match_id"]))
        for window in analysis.windows:
            number = window.window_start_seconds // 900 + 1
            label = labels_by_key.get((match["match_id"], f"{match['match_id']}_W{number}"))
            if label is None:
                raise ValueError(f"Missing label for {match['match_id']} window {number}")
            rows.append(
                {
                    "match_id": match["match_id"],
                    "scenario_type": match["scenario_type"],
                    "actual": int(label["risk_label"]),
                    "engine_prediction": int(window.persistent_risk),
                    "dangerous_turnovers": window.dangerous_turnovers,
                }
            )

    scenarios = sorted({str(row["scenario_type"]) for row in rows})
    if len(scenarios) < 2:
        raise ValueError("At least two scenario archetypes are needed for grouped evaluation")
    folds = []
    held_out_predictions: list[tuple[int, int]] = []
    baseline_predictions: list[tuple[int, int]] = []
    for held_out in scenarios:
        training = [row for row in rows if row["scenario_type"] != held_out]
        testing = [row for row in rows if row["scenario_type"] == held_out]
        threshold = _choose_turnover_threshold(training)
        engine_pairs = [(int(row["actual"]), int(row["engine_prediction"])) for row in testing]
        baseline_pairs = [
            (int(row["actual"]), int(int(row["dangerous_turnovers"]) >= threshold))
            for row in testing
        ]
        held_out_predictions.extend(engine_pairs)
        baseline_predictions.extend(baseline_pairs)
        folds.append(
            {
                "held_out_scenario_type": held_out,
                "train_scenario_types": len(scenarios) - 1,
                "test_matches": len({str(row["match_id"]) for row in testing}),
                "turnover_baseline_threshold_selected_on_train": threshold,
                "rule_engine": _counts(engine_pairs),
                "turnover_only_baseline": _counts(baseline_pairs),
            }
        )

    return {
        "schema_version": "invisible-game.synthetic-evaluation.v1",
        "split_unit": "scenario_type",
        "scenario_types": len(scenarios),
        "matches": len(matches),
        "windows": len(rows),
        "label_prevalence": round(sum(int(row["actual"]) for row in rows) / len(rows), 4),
        "rule_engine": _counts(held_out_predictions),
        "group_selected_turnover_only_baseline": _counts(baseline_predictions),
        "folds": folds,
        "interpretation": (
            "All sibling match variants stay in one scenario fold. The rule thresholds are fixed "
            "development heuristics and may have been informed by this synthetic dataset; this is "
            "a descriptive transfer check against constructed labels, not an untouched holdout or "
            "evidence of accuracy on real football."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    try:
        print(json.dumps(run_evaluation(args.data_dir), ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
