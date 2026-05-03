"""
Entity Resolution: Skill, Company ve Institution isimlerini normalize eder ve
KG'deki mevcut düğümlerle eşleştirir.

Öncelik sırası:
  1. Alias dictionary  — "JS" → "JavaScript", "K8s" → "Kubernetes"
  2. Fuzzy match       — "Javascript" → mevcut "JavaScript" düğümü (eşik: 88)
  3. Olduğu gibi       — yeni düğüm olarak eklenir
"""

import re
import logging
from neo4j import Driver
from rapidfuzz import process, fuzz

logger = logging.getLogger(__name__)

# Canonical form: her alias → standart isim
SKILL_ALIASES: dict[str, str] = {
    # ── JavaScript ailesi ──────────────────────────────────────────
    "js":               "JavaScript",
    "javascript":       "JavaScript",
    "ts":               "TypeScript",
    "typescript":       "TypeScript",
    "nodejs":           "Node.js",
    "node.js":          "Node.js",
    "node js":          "Node.js",
    "reactjs":          "React",
    "react.js":         "React",
    "vuejs":            "Vue.js",
    "vue.js":           "Vue.js",
    "angularjs":        "Angular",
    "nextjs":           "Next.js",
    "next.js":          "Next.js",
    # ── Python ────────────────────────────────────────────────────
    "py":               "Python",
    "python3":          "Python",
    # ── Diğer diller ─────────────────────────────────────────────
    "golang":           "Go",
    "go lang":          "Go",
    "csharp":           "C#",
    "c sharp":          "C#",
    "cpp":              "C++",
    "c plus plus":      "C++",
    # ── ML / AI ───────────────────────────────────────────────────
    "ml":               "Machine Learning",
    "machine learning": "Machine Learning",
    "makine öğrenmesi": "Machine Learning",
    "makine ogenmesi":  "Machine Learning",
    "dl":               "Deep Learning",
    "deep learning":    "Deep Learning",
    "derin öğrenme":    "Deep Learning",
    "ai":               "Artificial Intelligence",
    "yapay zeka":       "Artificial Intelligence",
    "nlp":              "Natural Language Processing",
    "doğal dil işleme": "Natural Language Processing",
    "computer vision":  "Computer Vision",
    "gen ai":           "Generative AI",
    "generative ai":    "Generative AI",
    "llm":              "Large Language Models",
    "large language models": "Large Language Models",
    # ── Backend frameworks ────────────────────────────────────────
    "spring boot":      "Spring Boot",
    "dotnet":           ".NET",
    "asp.net":          "ASP.NET",
    # ── Databases ─────────────────────────────────────────────────
    "postgres":         "PostgreSQL",
    "postgresql":       "PostgreSQL",
    "mssql":            "SQL Server",
    "sql server":       "SQL Server",
    "microsoft sql server": "SQL Server",
    "mongo":            "MongoDB",
    "mongodb":          "MongoDB",
    "elastic search":   "Elasticsearch",
    "oracle db":        "Oracle",
    "oracle database":  "Oracle",
    # ── Cloud ─────────────────────────────────────────────────────
    "amazon web services": "AWS",
    "google cloud":     "GCP",
    "google cloud platform": "GCP",
    "microsoft azure":  "Azure",
    # ── DevOps ───────────────────────────────────────────────────
    "k8s":              "Kubernetes",
    "cicd":             "CI/CD",
    "ci cd":            "CI/CD",
    "github actions":   "GitHub Actions",
    "gitlab ci":        "GitLab CI",
    # ── Data engineering ─────────────────────────────────────────
    "apache spark":     "Apache Spark",
    "apache kafka":     "Apache Kafka",
    "apache airflow":   "Apache Airflow",
    "power bi":         "Power BI",
    "powerbi":          "Power BI",
    # ── Methods ───────────────────────────────────────────────────
    "restful":          "REST API",
    "rest api":         "REST API",
    "test driven development": "TDD",
    "ab testing":       "A/B Testing",
}


def _normalize(text: str) -> str:
    """Lowercase + Türkçe karakter dönüşümü + whitespace temizliği."""
    if not text:
        return ""
    for src, dst in {"İ": "i", "I": "ı", "Ş": "ş", "Ğ": "ğ",
                     "Ü": "ü", "Ö": "ö", "Ç": "ç"}.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text.lower().strip())


class EntityResolver:
    """
    KG yazımından önce çağrılır; her entity ismi için canonical form döndürür.
    Resolver transaction dışında çalışır — Neo4j session çakışması olmaz.
    """

    FUZZY_THRESHOLD = 88

    def __init__(self, driver: Driver):
        self.driver = driver
        self._skill_cache: list[str] | None = None
        self._company_cache: list[str] | None = None
        self._institution_cache: list[str] | None = None

    # ── Public API ────────────────────────────────────────────────

    def resolve_skill(self, raw: str) -> str:
        return self._resolve(raw, self._get_skill_cache)

    def resolve_company(self, raw: str) -> str:
        # Şirket isimlerinde alias dict kullanılmaz, sadece fuzzy
        return self._fuzzy_only(raw, self._get_company_cache)

    def resolve_institution(self, raw: str) -> str:
        return self._fuzzy_only(raw, self._get_institution_cache)

    def invalidate_cache(self):
        """Her CV yazımının ardından çağrılır — sonraki CV için taze cache."""
        self._skill_cache = None
        self._company_cache = None
        self._institution_cache = None

    # ── Core ──────────────────────────────────────────────────────

    def _resolve(self, raw: str, cache_fn) -> str:
        if not raw or not raw.strip():
            return raw

        # 1. Alias lookup
        canonical = SKILL_ALIASES.get(_normalize(raw))
        if canonical:
            logger.debug(f"[ER] alias  : '{raw}' → '{canonical}'")
            return canonical

        # 2. Fuzzy match
        return self._fuzzy_only(raw, cache_fn)

    def _fuzzy_only(self, raw: str, cache_fn) -> str:
        if not raw or not raw.strip():
            return raw

        existing = cache_fn()
        if not existing:
            return raw

        result = process.extractOne(raw, existing, scorer=fuzz.token_sort_ratio)
        if result and result[1] >= self.FUZZY_THRESHOLD:
            match = result[0]
            if match != raw:
                logger.debug(f"[ER] fuzzy  : '{raw}' → '{match}' (score={result[1]})")
            return match

        return raw

    # ── Cache loaders ─────────────────────────────────────────────

    def _get_skill_cache(self) -> list[str]:
        if self._skill_cache is None:
            self._skill_cache = self._fetch("Skill")
        return self._skill_cache

    def _get_company_cache(self) -> list[str]:
        if self._company_cache is None:
            self._company_cache = self._fetch("Company")
        return self._company_cache

    def _get_institution_cache(self) -> list[str]:
        if self._institution_cache is None:
            self._institution_cache = self._fetch("Institution")
        return self._institution_cache

    def _fetch(self, label: str) -> list[str]:
        try:
            with self.driver.session() as session:
                result = session.run(f"MATCH (n:{label}) RETURN n.name AS name")
                return [r["name"] for r in result if r["name"]]
        except Exception as e:
            logger.warning(f"[ER] cache fetch failed for {label}: {e}")
            return []
