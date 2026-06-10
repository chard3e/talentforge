"""
Compute triple-level KG construction metrics from ablation_runner outputs.

Requires ablation_runner results created after prediction persistence was added.
Older result files only contain aggregate metrics and cannot be triple-evaluated.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from evaluation.triple_evaluator import evaluate_triples, save_report


def load_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def source_file_of(item: dict[str, Any]) -> str | None:
    """Return the CV file name across old and new gold/result schemas."""
    return item.get("source_file") or item.get("file_name")


def prediction_pairs_for_run(
    run_data: dict[str, Any],
    gold_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_source = {
        source_file_of(item): item.get("prediction", {})
        for item in run_data.get("cv_results", [])
        if item.get("prediction") and source_file_of(item)
    }
    paired_predictions = []
    paired_gold = []
    for gold in gold_items:
        prediction = by_source.get(source_file_of(gold))
        if prediction:
            paired_predictions.append(prediction)
            paired_gold.append(gold)
    return paired_predictions, paired_gold


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablation", default="evaluation/ablation_results.json")
    parser.add_argument("--gold", default="evaluation/golden_extractions_pretty.json")
    parser.add_argument("--output", default="evaluation/ablation_triple_results.json")
    args = parser.parse_args()

    ablation = load_json(args.ablation)
    gold_items = load_json(args.gold)

    reports = {}
    skipped = {}
    for run_key, run_data in ablation.items():
        predictions, paired_gold = prediction_pairs_for_run(run_data, gold_items)
        available = len(predictions)
        if available == 0:
            skipped[run_key] = "No stored predictions. Re-run ablation_runner for this run."
            continue

        report = evaluate_triples(predictions, paired_gold)
        reports[run_key] = {
            "available_predictions": available,
            "total_gold_records": len(paired_gold),
            "overall": report.overall.__dict__,
            "by_relation": {key: value.__dict__ for key, value in report.by_relation.items()},
            "by_metadata": {
                field: {key: value.__dict__ for key, value in values.items()}
                for field, values in report.by_metadata.items()
            },
            "total_gold_triples": report.total_gold_triples,
            "total_pred_triples": report.total_pred_triples,
        }

    payload = {"runs": reports, "skipped": skipped}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\nTriple-level ablation results")
    print("=" * 80)
    print(f"{'Run':<38} {'N':>3} {'P':>7} {'R':>7} {'F1':>7} {'Gold':>6} {'Pred':>6}")
    print("-" * 80)
    for run_key, report in sorted(reports.items()):
        overall = report["overall"]
        print(
            f"{run_key:<38} {report['available_predictions']:>3} "
            f"{overall['precision']:>7.3f} {overall['recall']:>7.3f} "
            f"{overall['f1']:>7.3f} {report['total_gold_triples']:>6} "
            f"{report['total_pred_triples']:>6}"
        )
    if skipped:
        print("\nSkipped runs need re-run because raw predictions are not stored:")
        for run_key in sorted(skipped):
            print(f"- {run_key}")
    print(f"\nSaved: {args.output}")


if __name__ == "__main__":
    main()
