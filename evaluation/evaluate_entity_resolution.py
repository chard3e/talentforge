from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import get_neo4j_driver


def normalize(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower().strip()
    tr_map = str.maketrans({
        "ı": "i",
        "İ": "i",
        "ğ": "g",
        "ü": "u",
        "ş": "s",
        "ö": "o",
        "ç": "c",
    })
    text = text.translate(tr_map)
    text = re.sub(r"[^a-z0-9+#./ -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def load_json(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_names(label: str) -> list[str]:
    driver = get_neo4j_driver()
    with driver.session() as session:
        rows = session.run(f"MATCH (n:{label}) RETURN n.name AS name").data()
    return [row["name"] for row in rows if row.get("name")]


def evaluate(targets: list[dict[str, Any]]) -> dict[str, Any]:
    names_by_type = {
        "skill": fetch_names("Skill"),
        "company": fetch_names("Company"),
        "institution": fetch_names("Institution"),
        "certification": fetch_names("Certification"),
    }
    normalized_by_type = {
        entity_type: {normalize(name): name for name in names}
        for entity_type, names in names_by_type.items()
    }

    rows = []
    for target in targets:
        entity_type = target.get("entity_type")
        canonical = target.get("canonical")
        variants = target.get("observed_variants", [])
        existing = normalized_by_type.get(entity_type, {})

        canonical_present = normalize(canonical) in existing
        remaining_variants = [
            variant for variant in variants
            if normalize(variant) in existing and normalize(variant) != normalize(canonical)
        ]
        merged = canonical_present and not remaining_variants
        rows.append({
            "entity_type": entity_type,
            "canonical": canonical,
            "canonical_present": canonical_present,
            "remaining_variant_count": len(remaining_variants),
            "remaining_variants": remaining_variants,
            "merged": merged,
        })

    total = len(rows)
    merged_count = sum(1 for row in rows if row["merged"])
    return {
        "aggregate": {
            "targets": total,
            "merged_targets": merged_count,
            "merge_success_rate": round(merged_count / total, 4) if total else 0.0,
            "skill_node_count": len(names_by_type["skill"]),
            "company_node_count": len(names_by_type["company"]),
            "institution_node_count": len(names_by_type["institution"]),
            "certification_node_count": len(names_by_type["certification"]),
        },
        "targets": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--targets", default="evaluation/entity_resolution_targets.json")
    parser.add_argument("--output", default="evaluation/thesis_outputs/entity_resolution_results.json")
    args = parser.parse_args()

    targets = load_json(args.targets)
    report = evaluate(targets)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("\nEntity resolution evaluation")
    print("=" * 72)
    for key, value in report["aggregate"].items():
        print(f"{key:<24} {value}")
    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
