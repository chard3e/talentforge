from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path
from typing import Any

import requests


def normalize(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower().strip()
    tr_map = str.maketrans({
        "\u0131": "i",
        "\u0130": "i",
        "\u011f": "g",
        "\u00fc": "u",
        "\u015f": "s",
        "\u00f6": "o",
        "\u00e7": "c",
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })
    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_id_to_name(gold_path: str | Path) -> dict[str, str]:
    path = Path(gold_path)
    if not path.exists():
        return {}
    items = load_json(path)
    if not isinstance(items, list):
        return {}
    return {
        normalize(item.get("cv_id")): normalize(item.get("candidate_name"))
        for item in items
        if normalize(item.get("cv_id")) and normalize(item.get("candidate_name"))
    }


def expected_aliases(query: dict[str, Any], keys: list[str], id_to_name: dict[str, str]) -> list[set[str]]:
    expected: list[set[str]] = []
    for key in keys:
        for item in query.get(key, []):
            if isinstance(item, dict):
                raw_values = [
                    item.get("candidate_id"),
                    item.get("cv_id"),
                    item.get("candidate_name"),
                ]
            else:
                raw_values = [item]

            aliases: set[str] = set()
            for raw in raw_values:
                value = normalize(raw)
                if not value:
                    continue
                aliases.add(value)
                if value in id_to_name:
                    aliases.add(id_to_name[value])
            if aliases:
                expected.append(aliases)
    return expected


def candidate_keys(item: dict[str, Any]) -> set[str]:
    return {
        value
        for value in {
            normalize(item.get("candidate_id")),
            normalize(item.get("id")),
            normalize(item.get("name")),
        }
        if value
    }


def count_found(expected: list[set[str]], returned_keys: set[str]) -> int:
    return sum(1 for aliases in expected if aliases & returned_keys)


def relevance_for(keys: set[str], strong: list[set[str]], partial: list[set[str]]) -> int:
    if any(keys & aliases for aliases in strong):
        return 2
    if any(keys & aliases for aliases in partial):
        return 1
    return 0


def dcg(relevances: list[int]) -> float:
    total = 0.0
    for idx, rel in enumerate(relevances, start=1):
        if rel:
            total += rel / (1 if idx == 1 else math.log2(idx + 1))
    return total


def evaluate_query(api_base: str, query: dict[str, Any], timeout: int, id_to_name: dict[str, str]) -> dict[str, Any]:
    started = time.time()
    response = requests.post(
        f"{api_base.rstrip('/')}/nl-search",
        json={"query": query["query_text"]},
        timeout=timeout,
    )
    elapsed = round(time.time() - started, 2)
    response.raise_for_status()
    payload = response.json()
    results = payload.get("results", [])

    strong = expected_aliases(query, ["strong_expected", "expected_strong_matches"], id_to_name)
    partial = expected_aliases(query, ["partial_expected", "expected_relevant_matches"], id_to_name)
    relevant = strong + partial
    ranked_keys = [candidate_keys(item) for item in results if candidate_keys(item)]
    relevances = [relevance_for(keys, strong, partial) for keys in ranked_keys]

    top1 = set().union(*ranked_keys[:1]) if ranked_keys[:1] else set()
    top3 = set().union(*ranked_keys[:3]) if ranked_keys[:3] else set()
    top5 = set().union(*ranked_keys[:5]) if ranked_keys[:5] else set()
    top10 = set().union(*ranked_keys[:10]) if ranked_keys[:10] else set()
    strong_found_10 = count_found(strong, top10)
    relevant_found_10 = count_found(relevant, top10)
    ideal_rels = sorted([2] * len(strong) + [1] * len(partial), reverse=True)[:10]
    ndcg_10 = dcg(relevances[:10]) / dcg(ideal_rels) if ideal_rels and dcg(ideal_rels) else 0.0
    reciprocal_rank = next((1 / rank for rank, rel in enumerate(relevances, start=1) if rel > 0), 0.0)

    return {
        "query_id": query["query_id"],
        "query_text": query["query_text"],
        "elapsed_sec": elapsed,
        "parsed_query": payload.get("parsed_query", {}),
        "ranked_candidates": [
            {
                "rank": index + 1,
                "candidate_id": item.get("candidate_id") or item.get("id"),
                "candidate_name": item.get("name"),
                "score": item.get("total_score"),
                "relevance": relevance_for(candidate_keys(item), strong, partial),
            }
            for index, item in enumerate(results)
        ],
        "strong_expected_count": len(strong),
        "partial_expected_count": len(partial),
        "hit_strong_at_1": count_found(strong, top1) > 0,
        "hit_strong_at_3": count_found(strong, top3) > 0,
        "hit_strong_at_5": count_found(strong, top5) > 0,
        "hit_any_relevant_at_1": count_found(relevant, top1) > 0,
        "hit_any_relevant_at_3": count_found(relevant, top3) > 0,
        "hit_any_relevant_at_5": count_found(relevant, top5) > 0,
        "strong_recall_at_10": strong_found_10 / len(strong) if strong else None,
        "relevant_recall_at_10": relevant_found_10 / len(relevant) if relevant else None,
        "mrr": round(reciprocal_rank, 4),
        "ndcg_at_10": round(ndcg_10, 4),
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [r for r in results if "error" not in r]
    if not ok:
        return {"n_queries": 0, "success_rate": 0.0}

    def avg_bool(key: str) -> float:
        return round(sum(1 for r in ok if r.get(key)) / len(ok), 4)

    def avg_optional(key: str) -> float:
        values = [r[key] for r in ok if r.get(key) is not None]
        return round(sum(values) / len(values), 4) if values else 0.0

    return {
        "n_queries": len(ok),
        "attempted_queries": len(results),
        "success_rate": round(len(ok) / len(results), 4),
        "hit_strong_at_1": avg_bool("hit_strong_at_1"),
        "hit_strong_at_3": avg_bool("hit_strong_at_3"),
        "hit_strong_at_5": avg_bool("hit_strong_at_5"),
        "hit_any_relevant_at_1": avg_bool("hit_any_relevant_at_1"),
        "hit_any_relevant_at_3": avg_bool("hit_any_relevant_at_3"),
        "hit_any_relevant_at_5": avg_bool("hit_any_relevant_at_5"),
        "strong_recall_at_10": avg_optional("strong_recall_at_10"),
        "relevant_recall_at_10": avg_optional("relevant_recall_at_10"),
        "mrr": avg_optional("mrr"),
        "ndcg_at_10": avg_optional("ndcg_at_10"),
        "avg_elapsed_sec": round(sum(r.get("elapsed_sec", 0.0) for r in ok) / len(ok), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", default="evaluation/matching_ground_truth.json")
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="evaluation/thesis_outputs/matching_results.json")
    parser.add_argument("--gold", default="evaluation/golden_extractions_pretty.json")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    queries = load_json(args.ground_truth)
    id_to_name = build_id_to_name(args.gold)
    results = []
    for index, query in enumerate(queries, start=1):
        print(f"[{index}/{len(queries)}] {query['query_id']}")
        try:
            results.append(evaluate_query(args.api_base, query, args.timeout, id_to_name))
        except Exception as exc:
            results.append({
                "query_id": query.get("query_id"),
                "query_text": query.get("query_text"),
                "error": str(exc),
            })

    payload = {"aggregate": aggregate(results), "queries": results}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("\nMatching evaluation")
    print("=" * 72)
    for key, value in payload["aggregate"].items():
        print(f"{key:<26} {value}")
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
