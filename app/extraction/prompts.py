"""
CV Bilgi Çıkarımı için Prompt Şablonları
─────────────────────────────────────────
• Chain-of-Thought (CoT) yönlendirmesi
• Few-shot örnekler
• Dolaylı anlam çıkarımı kuralları (Semantic Inference)
"""

# ── System Prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Sen deneyimli bir İnsan Kaynakları ve NLP uzmanısın.
Görevin, verilen CV metninden hem AÇIK (explicit) hem de DOLAYLI (implicit) bilgi çıkarmaktır.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 BÖLÜM 1 · ADIM ADIM DÜŞÜNME (Chain of Thought)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Her CV için şu sırayla ilerle:
  1. Kişisel bilgileri bul (isim, e-posta, telefon, konum).
  2. Özet/profil cümlesini çıkar.
  3. Deneyimleri kronolojik sırayla listele.
  4. Her deneyimde:
     a. Açıkça yazılan yetenekleri çıkar.
     b. Dolaylı olarak anlaşılan yetenekleri çıkar (bkz. Bölüm 2).
     c. Şirketin sektörünü belirle → aday o sektörde deneyimli say.
  5. Yetenekleri kategorize et ve normalize et.
  6. Eğitim bilgilerini çıkar.
  7. Dil bilgilerini ve sertifikaları çıkar.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 BÖLÜM 2 · DOLAYLI ANLAM ÇIKARIMI (Semantic Inference)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Sadece açıkça yazılan bilgiyi değil, metinden makul şekilde
çıkarılabilecek bilgiyi de yakala. Örnekler:

▸ SEKTÖR ÇIKARIMI (Şirket → Sektör)
  "Garanti BBVA'da çalıştı"       → sektör: Bankacılık/Finans
  "Trendyol'da çalıştı"           → sektör: E-Ticaret/Teknoloji
  "Memorial Hastanesi'nde çalıştı" → sektör: Sağlık
  "PwC'de çalıştı"                → sektör: Danışmanlık/Denetim
  Eğer şirket tanınmıyorsa sektörü metinden çıkarmaya çalış,
  çıkaramıyorsan null bırak.

▸ YETENEK SİNONİMLERİ (Farklı yazım → Aynı yetenek)
  "ML" / "Machine Learning" / "Makine Öğrenmesi"  → name: "Machine Learning"
  "JS" / "JavaScript" / "javascript"               → name: "JavaScript"
  "K8s" / "Kubernetes"                              → name: "Kubernetes"
  "DL" / "Deep Learning" / "Derin Öğrenme"         → name: "Deep Learning"
  "React.js" / "ReactJS" / "React"                 → name: "React"
  "Postgres" / "PostgreSQL"                        → name: "PostgreSQL"
  HER ZAMAN en yaygın/standart formu kullan.

▸ DOLAYLI YETENEK ÇIKARIMI (Eylem → Yetenek)
  "Takım liderliği yaptım"           → Soft Skill: "Leadership"
  "Müşteri ile görüşmeler yürüttüm"  → Soft Skill: "Communication"
  "Proje planlaması ve yönetimi"      → Soft Skill: "Project Management"
  "A/B testleri yürüttüm"            → Domain: "A/B Testing"
  "CI/CD pipeline kurdum"            → DevOps: "CI/CD"
  "REST API geliştirdim"             → skill: "REST API"
  "Agile/Scrum ile çalıştım"         → Soft Skill: "Agile"
  Dolaylı çıkarılan yeteneklerin confidence değeri 0.60-0.75 olmalı.

▸ KIDEM SEVİYESİ ÇIKARIMI (Unvan → Seniority)
  "Stajyer" / "Intern"               → Junior
  "Jr." / "Junior"                    → Junior
  "Yazılım Geliştirici" (2-4 yıl)    → Mid
  "Senior" / "Kıdemli" / "Lead"      → Senior
  "Müdür" / "Director" / "VP"        → Lead
  Bu bilgiyi summary alanına yansıt.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 BÖLÜM 3 · ALAN KURALLARI
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

### Genel
- CV'de açıkça YAZILMAYAN bilgiyi UYDURMA.
  Dolaylı çıkarım ile uydurma arasındaki fark:
  ✓ Dolaylı çıkarım: "Trendyol'da çalıştı" → sektör: E-Ticaret (makul)
  ✗ Uydurma: "Trendyol'da çalıştı" → "AWS kullandı" (metinde yok)
- Türkçe CV → Türkçe yanıt. İngilizce CV → İngilizce yanıt.
- Placeholder değerleri ("Company Name", "University Name", "Job Position",
  "Department Name") → "Belirtilmemiş" yaz veya null bırak.

### Tarihler
  "Oca 2023", "Mar 2021", "Haz 2019" formatında yaz.
  Devam eden → is_current=true, end_date=null.

### Yetenekler (skills)
  - category: Programming | Framework | Database | Cloud | DevOps |
              Soft Skill | Tool | Design | Data Science | Domain | Other
  - level: 1-5 (ipucu yoksa null). HER SKİLL İÇİN AYRI DEĞER VER, hepsine 5 yazma.
    Örnek: Python(ana dil, 9 yıl)→level:5, Jira(sadece stajda)→level:2, Go(sadece 1 şirkette)→level:3
  - years_experience: O SKILL'İN KULLANILDIĞI TOPLAM SÜRE.
    Hesaplama: skill hangi deneyimlerde kullanıldıysa o deneyimlerin sürelerini topla.
    Örnek: Python 4 şirkette kullanıldı(2016-2025)→9, Go sadece Papara'da(2022-2025)→3, Oracle DB sadece Garanti'de(2017-2019)→2
    Metinde açıkça yazmıyorsa null yaz, 9 YAZMA.
  - evidence_text: Yeteneğin CV'de geçtiği orijinal cümle/ifade.
  - evidence_text MAKSİMUM 15 kelime. Kısa alıntı yap, uzun cümle YAZMA, aynı cümleyi tekrarlama.
  - confidence:
      0.90-1.00 → Açıkça yazılmış ("Python, Java, SQL" gibi listeler)
      0.75-0.89 → Güçlü ipucu ("FastAPI ile mikroservis geliştirdim")
      0.60-0.74 → Dolaylı çıkarım ("takım yönetimi" → Leadership)
      < 0.60    → KULLANMA, çok spekülatif.

### Deneyimler (experiences)
  - company_name: Gerçek şirket adı. Placeholder ise "Belirtilmemiş".
  - role_title: Pozisyon unvanı.
  - description: 1-2 cümle özet.
  - achievements: Somut başarılar. Rakamlar varsa mutlaka ekle.
  - skills_used: O deneyimde kullanılan yetenekler (normalize edilmiş).
  - evidence_text: İlgili metin parçası.

### Eğitim (educations)
  - degree: "Lisans" / "Yüksek Lisans" / "Doktora" / "Ön Lisans" /
            "Bachelor's" / "Master's" / "PhD" / "MBA"
  - Erasmus, exchange, değişim programları da ayrı eğitim kaydı olarak ekle
    (degree: "Erasmus" veya "Exchange Program")
  - field: Bölüm adı. Placeholder ise null.
  - institution: Okul adı. Placeholder ise null.
"""

# ── Few-shot Örnek ────────────────────────────────────────────────────────────

FEW_SHOT_EXAMPLE = """\
## ÖRNEK — Dolaylı çıkarım dahil

### CV Metni:
\"\"\"
Elif Kara
elif.kara@gmail.com | 0533 987 6543 | Ankara

HAKKIMDA
7 yıllık deneyime sahip kıdemli veri bilimci. Finans ve e-ticaret
sektörlerinde büyük ölçekli ML projeleri yönettim.

DENEYİM
Senior Data Scientist — Getir (Şub 2022 – Halen)
- Talep tahmin modeli geliştirdim, MAPE %12'den %7'ye düştü
- 5 kişilik ML takımını yönetiyorum
- Python, PySpark, MLflow ile end-to-end pipeline kurdum
- A/B testleri ile model performansını ölçtüm

Veri Bilimci — QNB Finansbank (Oca 2019 – Oca 2022)
- Kredi skorlama modeli geliştirdim (XGBoost, LightGBM)
- SQL ile büyük ölçekli veri analizi
- Müşteri segmentasyonu için clustering algoritmaları uyguladım

Stajyer — Turkcell (Haz 2017 – Ağu 2017)
- Churn prediction modeli için veri ön işleme

EĞİTİM
İstatistik Yüksek Lisans — ODTÜ (2017-2019) — GPA: 3.72
Endüstri Mühendisliği Lisans — Bilkent Üniversitesi (2013-2017)

SERTİFİKA
- AWS Machine Learning Specialty (2023)
- Google Professional Data Engineer (2021)

DİLLER
- Türkçe (Ana dil), İngilizce (C1), Fransızca (B1)
\"\"\"

### Beklenen Çıktı (dolaylı çıkarımlar ★ ile işaretli):
{
  "candidate_name": "Elif Kara",
  "email": "elif.kara@gmail.com",
  "phone": "0533 987 6543",
  "location": "Ankara",
  "summary": "7 yıllık deneyime sahip kıdemli (Senior) veri bilimci. Finans ve e-ticaret sektörlerinde büyük ölçekli ML projeleri yönetmiş.",
  "experiences": [
    {
      "company_name": "Getir",
      "role_title": "Senior Data Scientist",
      "start_date": "Şub 2022",
      "end_date": null,
      "is_current": true,
      "location": null,
      "description": "Talep tahmin modeli geliştirme, ML takım yönetimi, end-to-end pipeline oluşturma ve A/B test süreçleri.",
      "achievements": ["Talep tahmin modelinde MAPE %12'den %7'ye düşürüldü", "5 kişilik ML takımı yönetimi"],
      "skills_used": ["Python", "PySpark", "MLflow", "A/B Testing", "Machine Learning"],
      "evidence_text": "Talep tahmin modeli geliştirdim, MAPE %12'den %7'ye düştü. 5 kişilik ML takımını yönetiyorum.",
      "confidence": 0.95
    },
    {
      "company_name": "QNB Finansbank",
      "role_title": "Veri Bilimci",
      "start_date": "Oca 2019",
      "end_date": "Oca 2022",
      "is_current": false,
      "location": null,
      "description": "Kredi skorlama modeli geliştirme, büyük ölçekli SQL veri analizi ve müşteri segmentasyonu.",
      "achievements": ["Kredi skorlama modeli geliştirdi"],
      "skills_used": ["XGBoost", "LightGBM", "SQL", "Machine Learning", "Clustering"],
      "evidence_text": "Kredi skorlama modeli geliştirdim (XGBoost, LightGBM). SQL ile büyük ölçekli veri analizi.",
      "confidence": 0.95
    },
    {
      "company_name": "Turkcell",
      "role_title": "Stajyer",
      "start_date": "Haz 2017",
      "end_date": "Ağu 2017",
      "is_current": false,
      "location": null,
      "description": "Churn prediction modeli için veri ön işleme çalışması.",
      "achievements": [],
      "skills_used": ["Data Preprocessing", "Machine Learning"],
      "evidence_text": "Churn prediction modeli için veri ön işleme",
      "confidence": 0.85
    }
  ],
  "skills": [
    {"name": "Python",          "category": "Programming",   "years_experience": 7, "level": 5, "evidence_text": "Python, PySpark, MLflow ile end-to-end pipeline kurdum", "confidence": 0.95},
    {"name": "Machine Learning","category": "Data Science",  "years_experience": 7, "level": 5, "evidence_text": "büyük ölçekli ML projeleri yönettim", "confidence": 0.95},
    {"name": "PySpark",         "category": "Data Science",  "years_experience": null, "level": 4, "evidence_text": "Python, PySpark, MLflow ile end-to-end pipeline kurdum", "confidence": 0.9},
    {"name": "MLflow",          "category": "Tool",          "years_experience": null, "level": null, "evidence_text": "Python, PySpark, MLflow ile end-to-end pipeline kurdum", "confidence": 0.9},
    {"name": "XGBoost",         "category": "Data Science",  "years_experience": null, "level": null, "evidence_text": "Kredi skorlama modeli geliştirdim (XGBoost, LightGBM)", "confidence": 0.9},
    {"name": "LightGBM",        "category": "Data Science",  "years_experience": null, "level": null, "evidence_text": "Kredi skorlama modeli geliştirdim (XGBoost, LightGBM)", "confidence": 0.9},
    {"name": "SQL",             "category": "Database",      "years_experience": null, "level": 4, "evidence_text": "SQL ile büyük ölçekli veri analizi", "confidence": 0.9},
    {"name": "A/B Testing",     "category": "Data Science",  "years_experience": null, "level": null, "evidence_text": "A/B testleri ile model performansını ölçtüm", "confidence": 0.85},
    {"name": "Clustering",      "category": "Data Science",  "years_experience": null, "level": null, "evidence_text": "Müşteri segmentasyonu için clustering algoritmaları", "confidence": 0.85},
    {"name": "Leadership",      "category": "Soft Skill",    "years_experience": null, "level": null, "evidence_text": "5 kişilik ML takımını yönetiyorum", "confidence": 0.7},
    {"name": "Data Preprocessing","category": "Data Science","years_experience": null, "level": null, "evidence_text": "Churn prediction modeli için veri ön işleme", "confidence": 0.7}
  ],
  "educations": [
    {"degree": "Yüksek Lisans", "field": "İstatistik",            "institution": "ODTÜ",                "start_year": 2017, "end_year": 2019, "gpa": 3.72},
    {"degree": "Lisans",        "field": "Endüstri Mühendisliği", "institution": "Bilkent Üniversitesi", "start_year": 2013, "end_year": 2017, "gpa": null}
  ],
  "languages": ["Türkçe (Ana dil)", "İngilizce (C1)", "Fransızca (B1)"],
  "certifications": ["AWS Machine Learning Specialty (2023)", "Google Professional Data Engineer (2021)"]
}
"""

# ── User Prompt Builder ───────────────────────────────────────────────────────

def build_user_prompt(cv_text: str, max_chars: int = 6000) -> str:
    """
    Few-shot örnek + gerçek CV metnini birleştiren kullanıcı prompt'u.
    """
    truncated = cv_text[:max_chars]

    return f"""{FEW_SHOT_EXAMPLE}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Şimdi aşağıdaki CV'yi analiz et.

Kurallar:
1. Adım adım düşün (önce kişisel bilgi, sonra deneyim, sonra skill, …).
2. Hem AÇIK hem DOLAYLI bilgileri çıkar.
3. Yetenek isimlerini NORMALIZE et (sinonim → standart form).
4. Metinde olmayan bilgiyi UYDURMA.
5. Placeholder değerleri kullanma ("Company Name" vb. → "Belirtilmemiş" yaz).
6. Dolaylı çıkarımlarda confidence 0.60-0.75 arasında olmalı.

### CV Metni:
\"\"\"
{truncated}
\"\"\"
"""