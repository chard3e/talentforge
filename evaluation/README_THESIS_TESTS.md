# TalentForge Thesis Test Pipeline

Bu klasor, 100 CV dataset ile tezde kullanilacak final deneylerini temiz ve
tekrarlanabilir bicimde uretmek icin duzenlendi.

Korunan input dosyalari:

- `golden_extractions_pretty.json`: tum CV'ler icin ana gold extraction dosyasi
- `gold_per_cv/`: CV bazli gold kayitlar
- `dataset_manifest.json` / `dataset_manifest.csv`: dataset dagilim ve metadata
- `dataset_summary.json`: tezde raporlanacak dataset dagilimlari
- `matching_ground_truth.json`: aday-ilan / NL query matching beklentileri
- `entity_resolution_targets.json`: canonical entity merge hedefleri

Final kosular icin onerilen cikti yapisi:

```text
evaluation/
  thesis_runs/
    final_100/
      json/
        ablation_results.json
        ablation_triple_results.json
        model_comparison_sysb.json
        model_comparison_sysb_triples.json
        matching_results.json
        entity_resolution_results.json
  thesis_outputs/
    final_100/
      tables/
      figures/
      reports/
      json/
```

## 0. Ortam

```powershell
$env:UV_CACHE_DIR="$env:TEMP\talentforge-uv-cache"
$env:UV_PYTHON="C:\Users\gizem\AppData\Local\Programs\Python\Python313\python.exe"
```

API gerektiren testler icin `.env` icinde en az `HF_TOKEN`, `NEO4J_URI`,
`NEO4J_USERNAME`, `NEO4J_PASSWORD` ve gerekiyorsa `DATABASE_URL` dolu olmali.

## 1. Prompt Ablation Testi

Tek model sabitken prompt/pipeline varyantlarini olcer.

```powershell
uv run --no-dev --no-python-downloads python evaluation/ablation_runner.py `
  --cv_dir data/cvs `
  --gold evaluation/golden_extractions_pretty.json `
  --n_cvs 100 `
  --configs BL-1 BL-2 SYS-A SYS-B `
  --models Qwen/Qwen2.5-7B-Instruct `
  --output evaluation/thesis_runs/final_100/json/ablation_results.json `
  --no_resume
```

Raporlanan metrikler: NER F1, Skill F1, RE F1, KG triple P/R/F1, hallucination /
unsupported extraction rate, unsupported triple rate, success rate, sure.

## 2. Aktif Sistemle Model Karsilastirmasi

Projede aktif kullanilan `SYS-B` prompt/pipeline sabitlenerek HF modelleri
karsilastirilir.

```powershell
uv run --no-dev --no-python-downloads python evaluation/ablation_runner.py `
  --cv_dir data/cvs `
  --gold evaluation/golden_extractions_pretty.json `
  --n_cvs 100 `
  --configs SYS-B `
  --models Qwen/Qwen2.5-7B-Instruct meta-llama/Llama-3.1-8B-Instruct mistralai/Mistral-7B-Instruct-v0.3 `
  --output evaluation/thesis_runs/final_100/json/model_comparison_sysb.json `
  --no_resume
```

HF Router tarafinda model erisimi degisebilir. Bir model hata verirse ayni
komuta erisilebilir baska bir instruct model eklenebilir.

## 3. Triple-level KG Metrikleri

Ablation sonucunu graph triple seviyesinde tekrar olcer:

```powershell
uv run --no-dev --no-python-downloads python evaluation/evaluate_ablation_triples.py `
  --ablation evaluation/thesis_runs/final_100/json/ablation_results.json `
  --gold evaluation/golden_extractions_pretty.json `
  --output evaluation/thesis_runs/final_100/json/ablation_triple_results.json
```

Model karsilastirmasi icin:

```powershell
uv run --no-dev --no-python-downloads python evaluation/evaluate_ablation_triples.py `
  --ablation evaluation/thesis_runs/final_100/json/model_comparison_sysb.json `
  --gold evaluation/golden_extractions_pretty.json `
  --output evaluation/thesis_runs/final_100/json/model_comparison_sysb_triples.json
```

Bu metriklere `HAS_PROJECT` ve `PROJECT_USED_SKILL` iliskileri de dahildir.

## 4. Matching Ground Truth Testi

Bu test gercek FastAPI + Neo4j matching motorunu kullanir. Once API calismali:

```powershell
uv run --no-dev --no-python-downloads uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Ayri terminalde:

```powershell
uv run --no-dev --no-python-downloads python evaluation/evaluate_matching_ground_truth.py `
  --ground-truth evaluation/matching_ground_truth.json `
  --api-base http://127.0.0.1:8000 `
  --output evaluation/thesis_runs/final_100/json/matching_results.json
```

Metrikler: Hit@1/3/5, strong match recall@10, any relevant recall@10, NDCG@10,
ortalama sorgu suresi.

## 5. Entity Resolution Testi

Aura/local Neo4j hangi ortamda test edilecekse `.env` o ortami gostermeli.
Once sistemde entity resolution endpoint'i calistirilir:

```powershell
uv run --no-dev --no-python-downloads python -c "import requests; print(requests.post('http://127.0.0.1:8000/resolve-entities', timeout=120).json())"
```

Sonra canonical hedeflerin merge durumu olculur:

```powershell
uv run --no-dev --no-python-downloads python evaluation/evaluate_entity_resolution.py `
  --targets evaluation/entity_resolution_targets.json `
  --output evaluation/thesis_runs/final_100/json/entity_resolution_results.json
```

Metrikler: merge success rate, kalan varyant sayisi, skill/company node sayilari.

## 6. Tez Tablo ve JPEG Grafiklerini Uretme

Yukaridaki JSON ciktilari olustuktan sonra tek komutla temiz tablo/grafik klasoru
uretilir:

```powershell
uv run --no-dev --no-python-downloads python evaluation/thesis_report.py `
  --ablation evaluation/thesis_runs/final_100/json/ablation_results.json `
  --triple evaluation/thesis_runs/final_100/json/ablation_triple_results.json `
  --model-comparison evaluation/thesis_runs/final_100/json/model_comparison_sysb.json `
  --model-triple evaluation/thesis_runs/final_100/json/model_comparison_sysb_triples.json `
  --dataset-summary evaluation/dataset_summary.json `
  --dataset-manifest evaluation/dataset_manifest.json `
  --matching evaluation/thesis_runs/final_100/json/matching_results.json `
  --entity-resolution evaluation/thesis_runs/final_100/json/entity_resolution_results.json `
  --output-dir evaluation/thesis_outputs `
  --run-name final_100
```

Uretilen ciktilar:

- `evaluation/thesis_outputs/final_100/tables/*.csv`
- `evaluation/thesis_outputs/final_100/figures/*.jpeg`
- `evaluation/thesis_outputs/final_100/reports/thesis_report_summary.md`
- `evaluation/thesis_outputs/final_100/reports/artifact_manifest.json`
- `evaluation/thesis_outputs/final_100/json/`: raporda kullanilan ham JSON kopyalari

## Tez Icin Yeterli Test Seti

Bu final suite su basliklari kapsar:

- LLM extraction kalitesi: NER, skill, company, education F1
- Iliski cikarma: experience-company-skill RE F1
- Bilgi grafigi insasi: triple precision, recall, F1 ve relation-level F1
- Project node/edge kapsami: `Project`, `HAS_PROJECT`, `PROJECT_USED_SKILL`
- Kanit guvenligi: hallucination / unsupported extraction ve unsupported triple rate
- Prompt ablation: BL-1, BL-2, SYS-A, SYS-B
- Model karsilastirmasi: aktif SYS-B prompt ile birden fazla HF instruct model
- Matching: Hit@K, Recall@10, NDCG@10
- Entity resolution: canonical merge basarisi
- Dataset guvenirligi: rol, zorluk, format, dil, template ve node coverage dagilimlari
