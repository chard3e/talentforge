from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import textwrap
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - optional report dependency
    Image = ImageDraw = ImageFont = None


BG = "#101014"
PANEL = "#171720"
TEXT = "#f8fafc"
MUTED = "#b8b8c8"
GRID = "#30303d"
ACCENT = ["#ff315d", "#a855f7", "#22c55e", "#38bdf8", "#facc15", "#fb923c", "#e879f9"]


def load_json(path: str | Path | None, *, required: bool = False) -> Any | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        if required:
            raise FileNotFoundError(p)
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def ensure_pillow() -> None:
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError("Pillow is required for JPEG generation. Install pillow or use CSV/MD outputs only.")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    ensure_pillow()
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def fmt(value: Any) -> str:
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, float):
        if 0 <= value <= 1:
            return f"{value:.3f}"
        return f"{value:.2f}"
    return "" if value is None else str(value)


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    if not any(marker in text for marker in ("Ã", "Ä", "Å")):
        return text
    for encoding in ("cp1252", "latin1"):
        try:
            fixed = text.encode(encoding).decode("utf-8")
        except Exception:
            continue
        if fixed.count("�") < text.count("�") and not any(marker in fixed for marker in ("Ã", "Ä", "Å")):
            return fixed
        if not any(marker in fixed for marker in ("Ã", "Ä", "Å")):
            return fixed
    return text


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: list[dict[str, Any]], *, max_rows: int = 30) -> str:
    if not rows:
        return "_No data._"
    shown = rows[:max_rows]
    headers = list(shown[0].keys())
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in shown:
        lines.append("| " + " | ".join(fmt(row.get(header)) for header in headers) + " |")
    if len(rows) > max_rows:
        lines.append(f"| ... | {len(rows) - max_rows} more rows | | | |")
    return "\n".join(lines)


def aggregate_rows(ablation: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_key, run_data in sorted((ablation or {}).items()):
        agg = run_data.get("aggregate", {})
        if not agg:
            continue
        rows.append(
            {
                "run": run_key,
                "config": run_data.get("config", ""),
                "model": run_data.get("model", ""),
                "n": agg.get("n_cvs", 0),
                "success_rate": agg.get("success_rate", 0),
                "ner_f1": agg.get("avg_overall_ner_f1", 0),
                "skill_f1": agg.get("avg_skill_f1", 0),
                "company_f1": agg.get("avg_company_f1", 0),
                "education_f1": agg.get("avg_education_f1", 0),
                "re_f1": agg.get("avg_re_f1", 0),
                "kg_precision": agg.get("kg_triple_precision", 0),
                "kg_recall": agg.get("kg_triple_recall", 0),
                "kg_f1": agg.get("kg_triple_f1", 0),
                "hallucination_rate": agg.get("avg_hallucination_rate", 0),
                "unsupported_triple_rate": agg.get("avg_unsupported_triple_rate", 0),
                "avg_elapsed_sec": agg.get("avg_elapsed_sec", 0),
            }
        )
    return rows


def cv_error_rows(ablation: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_key, run_data in sorted((ablation or {}).items()):
        for item in run_data.get("cv_results", []):
            if item.get("error"):
                rows.append(
                    {
                        "run": run_key,
                        "source_file": item.get("source_file", ""),
                        "candidate_name": item.get("candidate_name", ""),
                        "error": item.get("error", ""),
                    }
                )
    return rows


def relation_rows(triple: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_key, run_data in sorted((triple or {}).get("runs", {}).items()):
        for relation, metrics in sorted(run_data.get("by_relation", {}).items()):
            rows.append(
                {
                    "run": run_key,
                    "relation": relation,
                    "precision": metrics.get("precision", 0),
                    "recall": metrics.get("recall", 0),
                    "f1": metrics.get("f1", 0),
                    "tp": metrics.get("true_positives", 0),
                    "fp": metrics.get("false_positives", 0),
                    "fn": metrics.get("false_negatives", 0),
                }
            )
    return rows


def metadata_rows(triple: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_key, run_data in sorted((triple or {}).get("runs", {}).items()):
        for field, values in sorted(run_data.get("by_metadata", {}).items()):
            for value, metrics in sorted(values.items()):
                rows.append(
                    {
                        "run": run_key,
                        "metadata_field": field,
                        "value": value,
                        "precision": metrics.get("precision", 0),
                        "recall": metrics.get("recall", 0),
                        "f1": metrics.get("f1", 0),
                    }
                )
    return rows


def dataset_distribution_rows(summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section, values in sorted((summary or {}).items()):
        if isinstance(values, dict):
            for key, value in sorted(values.items(), key=lambda item: str(item[0])):
                if isinstance(value, (int, float)):
                    rows.append({"section": clean_text(section), "value": clean_text(key), "count": value})
    return rows


def dataset_node_rows(manifest: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    counters: Counter[str] = Counter()
    profile_flags: Counter[str] = Counter()
    for item in manifest or []:
        expected_nodes = item.get("expected_nodes", {})
        if isinstance(expected_nodes, dict):
            for key, value in expected_nodes.items():
                if isinstance(value, (int, float)):
                    counters[key] += int(value)
        for flag in ["has_projects", "has_certifications", "has_languages"]:
            if item.get(flag):
                profile_flags[flag] += 1
    rows = [{"metric": key, "count": value} for key, value in sorted(counters.items())]
    rows.extend({"metric": key, "count": value} for key, value in sorted(profile_flags.items()))
    return rows


def matching_rows(matching: dict[str, Any] | None) -> list[dict[str, Any]]:
    agg = (matching or {}).get("aggregate", {})
    return [
        {"metric": key, "value": value}
        for key, value in agg.items()
        if isinstance(value, (int, float))
    ]


def matching_query_rows(matching: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in (matching or {}).get("queries", []):
        top = item.get("ranked_candidates", [])[:3]
        rows.append(
            {
                "query_id": item.get("query_id", ""),
                "hit_strong_at_1": item.get("hit_strong_at_1", False),
                "hit_any_relevant_at_3": item.get("hit_any_relevant_at_3", False),
                "relevant_recall_at_10": item.get("relevant_recall_at_10", 0),
                "ndcg_at_10": item.get("ndcg_at_10", 0),
                "top3": ", ".join(str(candidate.get("candidate_name")) for candidate in top),
                "error": item.get("error", ""),
            }
        )
    return rows


def entity_rows(entity: dict[str, Any] | None) -> list[dict[str, Any]]:
    agg = (entity or {}).get("aggregate", {})
    return [
        {"metric": key, "value": value}
        for key, value in agg.items()
        if isinstance(value, (int, float))
    ]


def entity_target_rows(entity: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in (entity or {}).get("targets", []):
        rows.append(
            {
                "entity_type": target.get("entity_type", ""),
                "canonical": target.get("canonical", ""),
                "merged": target.get("merged", False),
                "remaining_variant_count": target.get("remaining_variant_count", 0),
                "remaining_variants": ", ".join(target.get("remaining_variants", [])),
            }
        )
    return rows


def draw_bar_chart(
    path: Path,
    title: str,
    labels: list[str],
    values: list[float],
    *,
    percent: bool = False,
    subtitle: str = "",
    width: int = 1500,
    height: int = 850,
) -> None:
    ensure_pillow()
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((55, 38), title, fill=TEXT, font=font(42, True))
    if subtitle:
        draw.text((58, 92), subtitle, fill=MUTED, font=font(20))
    draw.rounded_rectangle((35, 130, width - 35, height - 45), radius=18, fill=PANEL, outline="#262633")

    left, top, right, bottom = 100, 175, width - 80, height - 170
    max_value = max(values) if values else 1.0
    max_value = 1.0 if percent else max(max_value, 1.0)
    for i in range(6):
        y = bottom - (bottom - top) * i / 5
        draw.line((left, y, right, y), fill=GRID, width=1)
        tick = max_value * i / 5
        draw.text((35, y - 11), f"{tick:.0%}" if percent else f"{tick:.1f}", fill=MUTED, font=font(18))

    slot = (right - left) / max(len(values), 1)
    bar_w = min(92, slot * 0.55)
    for idx, (label, value) in enumerate(zip(labels, values)):
        x0 = left + slot * idx + (slot - bar_w) / 2
        x1 = x0 + bar_w
        y0 = bottom - (bottom - top) * (value / max_value if max_value else 0)
        draw.rounded_rectangle((x0, y0, x1, bottom), radius=10, fill=ACCENT[idx % len(ACCENT)])
        draw.text((x0 - 8, y0 - 30), f"{value:.1%}" if percent else f"{value:.2f}", fill=TEXT, font=font(18))
        for line_idx, line in enumerate(textwrap.wrap(clean_text(label), width=16)[:3]):
            draw.text((x0 - 28, bottom + 18 + line_idx * 21), line, fill=MUTED, font=font(16))

    image.save(path, quality=95)


def draw_grouped_metrics(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_pillow()
    metrics = ["ner_f1", "skill_f1", "re_f1", "kg_f1"]
    width, height = 1800, 900
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((55, 38), "Extraction and KG Metrics", fill=TEXT, font=font(42, True))
    draw.text((58, 92), "Entity extraction, relation extraction and graph triple quality", fill=MUTED, font=font(20))
    draw.rounded_rectangle((35, 130, width - 35, height - 45), radius=18, fill=PANEL, outline="#262633")
    left, top, right, bottom = 100, 180, width - 80, height - 185
    for i in range(6):
        y = bottom - (bottom - top) * i / 5
        draw.line((left, y, right, y), fill=GRID, width=1)
        draw.text((40, y - 11), f"{i / 5:.1f}", fill=MUTED, font=font(18))

    group_slot = (right - left) / max(len(rows), 1)
    bar_w = min(36, group_slot / 6)
    for group_idx, row in enumerate(rows):
        base_x = left + group_slot * group_idx + group_slot * 0.15
        for metric_idx, metric in enumerate(metrics):
            value = float(row.get(metric, 0) or 0)
            x0 = base_x + metric_idx * (bar_w + 9)
            y0 = bottom - (bottom - top) * min(value, 1.0)
            draw.rounded_rectangle((x0, y0, x0 + bar_w, bottom), radius=7, fill=ACCENT[metric_idx])
        for line_idx, line in enumerate(textwrap.wrap(clean_text(row["run"]), width=18)[:3]):
            draw.text((base_x - 15, bottom + 18 + line_idx * 21), line, fill=MUTED, font=font(16))

    legend_x = width - 580
    for idx, metric in enumerate(metrics):
        x = legend_x + idx * 135
        draw.rounded_rectangle((x, 94, x + 24, 118), radius=5, fill=ACCENT[idx])
        draw.text((x + 32, 92), metric, fill=TEXT, font=font(17))
    image.save(path, quality=95)


def draw_table(path: Path, title: str, rows: list[dict[str, Any]], *, max_rows: int = 14) -> None:
    ensure_pillow()
    if not rows:
        return
    shown = rows[:max_rows]
    headers = list(shown[0].keys())
    col_w = max(170, min(310, 1700 // max(len(headers), 1)))
    width = max(1200, min(2200, 70 + col_w * len(headers)))
    row_h = 54
    height = 165 + row_h * (len(shown) + 1)
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.text((45, 35), title, fill=TEXT, font=font(38, True))
    draw.rounded_rectangle((25, 90, width - 25, height - 25), radius=14, fill=PANEL, outline="#262633")
    y = 112
    for idx, header in enumerate(headers):
        draw.text((45 + idx * col_w, y), clean_text(header)[:24], fill="#d9f99d", font=font(17, True))
    y += row_h
    for row in shown:
        draw.line((35, y - 12, width - 35, y - 12), fill=GRID, width=1)
        for idx, header in enumerate(headers):
            draw.text((45 + idx * col_w, y), fmt(row.get(header))[:28], fill=TEXT, font=font(16))
        y += row_h
    image.save(path, quality=95)


def write_manifest(path: Path, files: list[Path]) -> None:
    rows = [{"file": str(file), "size_bytes": file.stat().st_size} for file in sorted(files) if file.exists()]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def copy_input(source: str | None, target_dir: Path) -> None:
    if not source:
        return
    p = Path(source)
    if p.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target_dir / p.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create clean thesis tables, JPEG figures and markdown report.")
    parser.add_argument("--ablation", default="evaluation/thesis_runs/final_100/json/ablation_results.json")
    parser.add_argument("--triple", default="evaluation/thesis_runs/final_100/json/ablation_triple_results.json")
    parser.add_argument("--model-comparison", default=None)
    parser.add_argument("--model-triple", default=None)
    parser.add_argument("--dataset-summary", default="evaluation/dataset_summary.json")
    parser.add_argument("--dataset-manifest", default="evaluation/dataset_manifest.json")
    parser.add_argument("--matching", default="evaluation/thesis_runs/final_100/json/matching_results.json")
    parser.add_argument("--entity-resolution", default="evaluation/thesis_runs/final_100/json/entity_resolution_results.json")
    parser.add_argument("--output-dir", default="evaluation/thesis_outputs")
    parser.add_argument("--run-name", default="final_100")
    args = parser.parse_args()

    base = Path(args.output_dir) / args.run_name
    tables_dir = base / "tables"
    figures_dir = base / "figures"
    reports_dir = base / "reports"
    json_dir = base / "json"
    for directory in [tables_dir, figures_dir, reports_dir, json_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    ablation = load_json(args.ablation)
    triple = load_json(args.triple)
    model_comparison = load_json(args.model_comparison)
    model_triple = load_json(args.model_triple)
    dataset_summary = load_json(args.dataset_summary)
    dataset_manifest = load_json(args.dataset_manifest)
    matching = load_json(args.matching)
    entity_resolution = load_json(args.entity_resolution)

    copy_input(args.ablation, json_dir)
    copy_input(args.triple, json_dir)
    copy_input(args.model_comparison, json_dir)
    copy_input(args.model_triple, json_dir)
    copy_input(args.matching, json_dir)
    copy_input(args.entity_resolution, json_dir)

    rows_by_name = {
        "ablation_aggregate_metrics": aggregate_rows(ablation),
        "ablation_failed_cvs": cv_error_rows(ablation),
        "kg_relation_metrics": relation_rows(triple),
        "kg_metadata_breakdowns": metadata_rows(triple),
        "model_aggregate_metrics": aggregate_rows(model_comparison),
        "model_kg_relation_metrics": relation_rows(model_triple),
        "dataset_distributions": dataset_distribution_rows(dataset_summary),
        "dataset_node_coverage": dataset_node_rows(dataset_manifest),
        "matching_metrics": matching_rows(matching),
        "matching_query_results": matching_query_rows(matching),
        "entity_resolution_metrics": entity_rows(entity_resolution),
        "entity_resolution_targets": entity_target_rows(entity_resolution),
    }

    for name, rows in rows_by_name.items():
        save_csv(tables_dir / f"{name}.csv", rows)

    figure_errors: list[str] = []
    try:
        if rows_by_name["ablation_aggregate_metrics"]:
            rows = rows_by_name["ablation_aggregate_metrics"]
            draw_grouped_metrics(figures_dir / "01_ablation_metrics.jpeg", rows)
            draw_bar_chart(
                figures_dir / "02_ablation_hallucination_rates.jpeg",
                "Hallucination / Unsupported Extraction Rate",
                [row["run"] for row in rows],
                [float(row["hallucination_rate"] or 0) for row in rows],
                percent=True,
            )
            draw_table(figures_dir / "03_ablation_summary_table.jpeg", "Ablation Summary", rows)

        if rows_by_name["model_aggregate_metrics"]:
            rows = rows_by_name["model_aggregate_metrics"]
            draw_grouped_metrics(figures_dir / "04_model_comparison_metrics.jpeg", rows)
            draw_bar_chart(
                figures_dir / "05_model_runtime.jpeg",
                "Average Runtime by Model",
                [row["model"] or row["run"] for row in rows],
                [float(row["avg_elapsed_sec"] or 0) for row in rows],
                subtitle="seconds per CV",
            )
            draw_table(figures_dir / "06_model_summary_table.jpeg", "Model Comparison Summary", rows)

        relation_source = rows_by_name["kg_relation_metrics"]
        if relation_source:
            best_run = max(rows_by_name["ablation_aggregate_metrics"], key=lambda row: row.get("kg_f1", 0))["run"]
            best_relations = [row for row in relation_source if row["run"] == best_run]
            draw_bar_chart(
                figures_dir / "07_relation_f1_best_run.jpeg",
                f"Relation-level KG F1 - {best_run}",
                [row["relation"] for row in best_relations],
                [float(row["f1"] or 0) for row in best_relations],
            )

        for section in [
            "role_family_distribution",
            "title_group_distribution",
            "difficulty_distribution",
            "template_distribution",
            "format_distribution",
            "language_distribution",
        ]:
            dist = (dataset_summary or {}).get(section, {})
            if dist:
                draw_bar_chart(
                    figures_dir / f"08_dataset_{section}.jpeg",
                    section.replace("_", " ").title(),
                    [clean_text(key) for key in dist.keys()],
                    [float(value) for value in dist.values()],
                    subtitle=f"Total CV: {(dataset_summary or {}).get('total_cvs', '')}",
                )

        if rows_by_name["dataset_node_coverage"]:
            draw_bar_chart(
                figures_dir / "09_dataset_node_coverage.jpeg",
                "Expected Node Coverage in Gold Dataset",
                [row["metric"] for row in rows_by_name["dataset_node_coverage"]],
                [float(row["count"] or 0) for row in rows_by_name["dataset_node_coverage"]],
            )

        if rows_by_name["matching_metrics"]:
            selected = [
                row
                for row in rows_by_name["matching_metrics"]
                if row["metric"]
                in {
                    "hit_strong_at_1",
                    "hit_strong_at_3",
                    "hit_strong_at_5",
                    "hit_any_relevant_at_3",
                    "relevant_recall_at_10",
                    "ndcg_at_10",
                }
            ]
            draw_bar_chart(
                figures_dir / "10_matching_metrics.jpeg",
                "Candidate Matching Quality",
                [row["metric"] for row in selected],
                [float(row["value"] or 0) for row in selected],
            )
            draw_table(figures_dir / "11_matching_query_table.jpeg", "Matching Query Results", rows_by_name["matching_query_results"])

        if rows_by_name["entity_resolution_metrics"]:
            selected = [
                row
                for row in rows_by_name["entity_resolution_metrics"]
                if row["metric"] in {
                    "merge_success_rate",
                    "skill_node_count",
                    "company_node_count",
                    "institution_node_count",
                    "certification_node_count",
                }
            ]
            draw_bar_chart(
                figures_dir / "12_entity_resolution_metrics.jpeg",
                "Entity Resolution Metrics",
                [row["metric"] for row in selected],
                [float(row["value"] or 0) for row in selected],
            )
            draw_table(figures_dir / "13_entity_resolution_targets.jpeg", "Entity Resolution Targets", rows_by_name["entity_resolution_targets"])
    except Exception as exc:
        figure_errors.append(str(exc))

    generated_files = list(tables_dir.glob("*.csv")) + list(figures_dir.glob("*.jpeg"))
    write_manifest(reports_dir / "artifact_manifest.json", generated_files)

    report_lines = [
        "# TalentForge Thesis Evaluation Report",
        "",
        f"Run name: `{args.run_name}`",
        "",
        "## What this suite covers",
        "",
        "- CV extraction quality: NER F1, skill F1, company F1, education F1.",
        "- LLM-to-KG construction: relation extraction F1, KG triple precision/recall/F1, relation-level F1.",
        "- Evidence safety: hallucination / unsupported extraction rate and unsupported triple rate.",
        "- Dataset robustness: role family, title group, difficulty, language, file format and template distributions.",
        "- Matching quality: Hit@K, Recall@10 and NDCG@10 using `matching_ground_truth.json`.",
        "- Entity resolution: canonical merge success rate and remaining variant analysis.",
        "",
        "## Ablation Summary",
        markdown_table(rows_by_name["ablation_aggregate_metrics"]),
        "",
        "## Model Comparison Summary",
        markdown_table(rows_by_name["model_aggregate_metrics"]),
        "",
        "## Matching Metrics",
        markdown_table(rows_by_name["matching_metrics"]),
        "",
        "## Entity Resolution Metrics",
        markdown_table(rows_by_name["entity_resolution_metrics"]),
        "",
        "## Main Figures",
    ]
    report_lines.extend(f"- `{path.relative_to(base)}`" for path in sorted(figures_dir.glob("*.jpeg")))
    if figure_errors:
        report_lines.extend(["", "## Figure Generation Warnings"])
        report_lines.extend(f"- {error}" for error in figure_errors)
    (reports_dir / "thesis_report_summary.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(f"Thesis artifacts saved to: {base}")
    print(f"Tables : {tables_dir}")
    print(f"Figures: {figures_dir}")
    print(f"Report : {reports_dir / 'thesis_report_summary.md'}")


if __name__ == "__main__":
    main()
