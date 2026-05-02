# TalentForge

**LLM-Driven Knowledge Graph for AI-Powered HR Candidate Matching System**

Büyük Dil Modelleri ve Bilgi Grafikleri ile Akıllı İnsan Kaynakları ve Aday Eşleştirme Sistemi

![Marmara Üniversitesi](https://img.shields.io/badge/Marmara%20Üniversitesi-Bilgisayar%20Mühendisliği-blue)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Neo4j](https://img.shields.io/badge/Neo4j-5.x-0081C9)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688)

## 📋 Proje Açıklaması

TalentForge, **CV'lerden** Büyük Dil Modelleri (LLM) ile yapısal bilgi çıkaran, bu bilgileri **Neo4j** tabanlı bir **Bilgi Grafiği**’nde modelleyen ve İK uzmanlarının doğal dilde yazdığı pozisyon kriterlerini grafik + vektör hibrit sorgularla en uygun adayları sıralayan **akıllı bir aday eşleştirme sistemi**dir.

Proje, Marmara Üniversitesi Teknoloji Fakültesi Bilgisayar Mühendisliği Bölümü bitirme projesi kapsamında geliştirilmektedir.

### Geliştirenler
- **Gizem ÖZDEMİR**
- **Muhammed Emin SOLAKOĞLU**
- **Emre KILIÇ**

**Danışman:** Doç. Dr. Buket DOĞAN  
**Dönem:** 2025

## ✨ Ana Özellikler

- LLM ile CV’den otomatik bilgi çıkarımı (Few-shot + CoT + Structured Output)
- Yetenek normalizasyonu (ESCO taksonomisi + embedding)
- Varlık birleştirme (Entity Resolution)
- KG destekli RAG doğrulama döngüsü (halüsinasyon azaltımı)
- Hibrit sorgu motoru (Graph + Vector + Reciprocal Rank Fusion)
- Açıklanabilir eşleştirme (explainable matching)
- KVKK ve etik uyumlu tasarım

## 🛠 Teknoloji Yığını (Tech Stack)

| Katman              | Teknoloji                          |
|---------------------|------------------------------------|
| Backend             | FastAPI + Python 3.11              |
| Asenkron İşlem      | Celery + Redis                     |
| Veritabanı          | Neo4j 5.x (Graph + Vector Index)   |
| İlişkisel DB        | PostgreSQL                         |
| Dosya Depolama      | MinIO (S3 uyumlu)                  |
| LLM                 | Llama 3.1 / Qwen2.5 (Ollama) + GPT-4o (değerlendirme) |
| Embedding           | BAAI/bge-m3                        |
| CV Parsing          | unstructured + pdfplumber + Tesseract |
| ORM / Client        | Neo4j Python Driver + LangChain/LlamaIndex |

## 🚀 Hızlı Başlangıç (Quick Start)

```bash
# 1. Repoyu klonla
git clone https://github.com/kullanıcı-adın/TalentForge.git
cd TalentForge

# 2. Docker ile tüm servisi ayağa kaldır
docker compose up -d

# 3. (İleride) Backend servisini çalıştır
# uv sync && uv run fastapi dev app/main.py
Detaylı kurulum ve geliştirme adımları için CONTRIBUTING.md dosyasını inceleyin.
📁 Proje Klasör Yapısı
BashTalentForge/
├── app/                  # FastAPI backend
├── core/                 # config, settings
├── extraction/           # CV parser + LLM extractor
├── graph/                # Neo4j işlemleri, Cypher
├── query/                # sorgu motoru + hybrid retriever
├── prompts/              # tüm LLM prompt'ları
├── tests/                # birim ve entegrasyon testleri
├── data/                 # gold standard, ESCO dataset
├── docker-compose.yml
├── .env.example
├── README.md
└── docs/
📊 Mimari
(Yakında draw.io / Mermaid diyagramı eklenecek)
🎯 Hedefler ve Hipotezler

H1: LLM çıkarımında F1 ≥ 0.85
H3: Hibrit sorgu ile NDCG@10’da %15+ iyileşme
H4: RAG doğrulama ile halüsinasyon oranı ≥%20 azalma

📄 Lisans
Bu proje Marmara Üniversitesi Bitirme Projesi kapsamında geliştirilmektedir.
Akademik amaçlı kullanım için izinlidir.
