# TalentForge Thesis Evaluation Report

Run name: `final_100`

## What this suite covers

- CV extraction quality: NER F1, skill F1, company F1, education F1.
- LLM-to-KG construction: relation extraction F1, KG triple precision/recall/F1, relation-level F1.
- Evidence safety: hallucination / unsupported extraction rate and unsupported triple rate.
- Dataset robustness: role family, title group, difficulty, language, file format and template distributions.
- Matching quality: Hit@K, Recall@10 and NDCG@10 using `matching_ground_truth.json`.
- Entity resolution: canonical merge success rate and remaining variant analysis.

## Ablation Summary
| run | config | model | n | success_rate | ner_f1 | skill_f1 | company_f1 | education_f1 | re_f1 | kg_precision | kg_recall | kg_f1 | hallucination_rate | unsupported_triple_rate | avg_elapsed_sec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BL-1_Qwen2.5-7B-Instruct | BL-1 | Qwen/Qwen2.5-7B-Instruct | 100 | 1.000 | 0.956 | 0.974 | 0.982 | 0.912 | 0.775 | 0.924 | 0.724 | 0.812 | 0.055 | 0.035 | 14.38 |
| BL-2_Qwen2.5-7B-Instruct | BL-2 | Qwen/Qwen2.5-7B-Instruct | 100 | 1.000 | 0.965 | 0.973 | 0.982 | 0.940 | 0.764 | 0.901 | 0.734 | 0.809 | 0.000 | 0.027 | 14.32 |
| SYS-A_Qwen2.5-7B-Instruct | SYS-A | Qwen/Qwen2.5-7B-Instruct | 100 | 1.000 | 0.938 | 0.943 | 0.942 | 0.930 | 0.776 | 0.842 | 0.703 | 0.766 | 0.067 | 0.052 | 17.65 |
| SYS-B_Qwen2.5-7B-Instruct | SYS-B | Qwen/Qwen2.5-7B-Instruct | 100 | 1.000 | 0.883 | 0.926 | 0.982 | 0.740 | 0.729 | 0.813 | 0.758 | 0.785 | 0.034 | 0.058 | 13.66 |

## Model Comparison Summary
| run | config | model | n | success_rate | ner_f1 | skill_f1 | company_f1 | education_f1 | re_f1 | kg_precision | kg_recall | kg_f1 | hallucination_rate | unsupported_triple_rate | avg_elapsed_sec |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SYS-B_Llama-3.1-8B-Instruct | SYS-B | meta-llama/Llama-3.1-8B-Instruct | 24 | 0.240 | 0.836 | 0.866 | 0.891 | 0.750 | 0.733 | 0.809 | 0.610 | 0.696 | 0.082 | 0.084 | 13.42 |
| SYS-B_Mistral-7B-Instruct-v0.3 | SYS-B | mistralai/Mistral-7B-Instruct-v0.3 | 0 | 0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SYS-B_Qwen2.5-7B-Instruct | SYS-B | Qwen/Qwen2.5-7B-Instruct | 99 | 0.990 | 0.887 | 0.931 | 0.982 | 0.748 | 0.730 | 0.819 | 0.756 | 0.786 | 0.035 | 0.056 | 16.86 |

## Matching Metrics
| metric | value |
| --- | --- |
| n_queries | 20 |
| attempted_queries | 20 |
| success_rate | 1.000 |
| hit_strong_at_1 | 0.650 |
| hit_strong_at_3 | 0.900 |
| hit_strong_at_5 | 0.950 |
| hit_any_relevant_at_1 | 0.650 |
| hit_any_relevant_at_3 | 0.900 |
| hit_any_relevant_at_5 | 0.950 |
| strong_recall_at_10 | 0.720 |
| relevant_recall_at_10 | 0.500 |
| mrr | 0.778 |
| ndcg_at_10 | 0.650 |
| avg_elapsed_sec | 20.46 |

## Entity Resolution Metrics
| metric | value |
| --- | --- |
| targets | 41 |
| merged_targets | 32 |
| merge_success_rate | 0.780 |
| skill_node_count | 370 |
| company_node_count | 85 |
| institution_node_count | 27 |
| certification_node_count | 74 |

## Main Figures
- `figures\01_ablation_metrics.jpeg`
- `figures\02_ablation_hallucination_rates.jpeg`
- `figures\03_ablation_summary_table.jpeg`
- `figures\04_model_comparison_metrics.jpeg`
- `figures\05_model_runtime.jpeg`
- `figures\06_model_summary_table.jpeg`
- `figures\07_relation_f1_best_run.jpeg`
- `figures\08_dataset_difficulty_distribution.jpeg`
- `figures\08_dataset_format_distribution.jpeg`
- `figures\08_dataset_language_distribution.jpeg`
- `figures\08_dataset_role_family_distribution.jpeg`
- `figures\08_dataset_template_distribution.jpeg`
- `figures\09_dataset_node_coverage.jpeg`
- `figures\10_matching_metrics.jpeg`
- `figures\11_matching_query_table.jpeg`
- `figures\12_entity_resolution_metrics.jpeg`
- `figures\13_entity_resolution_targets.jpeg`