"""
Entity Resolution — KG'deki duplicate düğümleri birleştirir.

Üç aşamalı çözümleme:
  1. Sinonim Sözlüğü: Bilinen eşdeğerleri birleştirir (K8s → Kubernetes)
  2. Fuzzy Matching: Benzer isimleri rapidfuzz ile tespit eder (React.js ≈ React)
  3. Neo4j MERGE: Duplicate düğümleri ve ilişkilerini birleştirir

APOC bağımlılığı YOK — saf Cypher ile çalışır.

Kullanım:
  resolver = EntityResolver(neo4j_driver)
  stats = resolver.resolve_all()
"""

import logging
from typing import Dict, List, Tuple, Set
from neo4j import Driver

logger = logging.getLogger(__name__)


# ── Sinonim Sözlükleri ────────────────────────────────────────────────

SKILL_SYNONYMS: Dict[str, List[str]] = {
    # Programlama dilleri
    "JavaScript":       ["JS", "Javascript", "javascript", "Java Script"],
    "TypeScript":       ["TS", "Typescript", "typescript"],
    "Python":           ["python", "Python3", "python3"],
    "C#":               ["CSharp", "C Sharp", "c#", "csharp"],

    # Frameworks
    "React":            ["React.js", "ReactJS", "Reactjs", "react.js"],
    "Next.js":          ["NextJS", "Nextjs", "next.js"],
    "Vue":              ["Vue.js", "VueJS", "Vuejs", "vue.js"],
    "Angular":          ["AngularJS", "Angular.js", "angular"],
    "Node.js":          ["NodeJS", "Nodejs", "node.js"],
    "Express":          ["Express.js", "ExpressJS", "express.js"],
    ".NET Core":        ["dotnet", "DotNet", ".Net Core", "ASP.NET"],
    "Spring Boot":      ["SpringBoot", "spring boot"],
    "FastAPI":          ["fastapi", "Fast API"],

    # Veritabanı
    "PostgreSQL":       ["Postgres", "postgres", "PSQL", "psql"],
    "MongoDB":          ["Mongo", "mongo", "MongoDb"],
    "MySQL":            ["mysql", "MySql"],
    "Oracle DB":        ["Oracle", "OracleDB", "Oracle Database"],
    "Elasticsearch":    ["ElasticSearch", "Elastic Search", "elastic"],
    "Redis":            ["redis"],

    # DevOps & Cloud
    "Kubernetes":       ["K8s", "k8s", "Kubernetes (K8s)", "kubernetes"],
    "Docker":           ["docker"],
    "AWS":              ["Amazon Web Services", "aws", "AWS (EKS, RDS, SQS, Lambda)"],
    "Google Cloud":     ["GCP", "Google Cloud Platform", "gcp"],
    "Azure":            ["Microsoft Azure", "azure"],
    "Jenkins":          ["jenkins"],
    "GitHub Actions":   ["Github Actions", "GH Actions", "github actions"],
    "Terraform":        ["terraform"],
    "ArgoCD":           ["Argo CD", "argocd"],
    "CI/CD":            ["CICD", "CI CD", "ci/cd"],

    # Data Science
    "Machine Learning": ["ML", "ml", "Makine Öğrenmesi", "makine öğrenmesi"],
    "Deep Learning":    ["DL", "dl", "Derin Öğrenme", "derin öğrenme"],
    "Pandas":           ["pandas"],
    "NumPy":            ["Numpy", "numpy"],

    # Araçlar
    "Git":              ["git"],
    "Jira":             ["jira", "JIRA"],
    "DataDog":          ["Datadog", "datadog"],
    "Kafka":            ["Apache Kafka", "apache kafka", "kafka"],
    "RabbitMQ":         ["Rabbit MQ", "rabbitmq"],

    # Soft Skills
    "Leadership":       ["Team Leadership", "Takım Liderliği", "Teknik Liderlik", "liderlik"],
    "Mentoring":        ["Mentorluk", "mentorluk", "Mentorship"],
    "Agile":            ["Agile/Scrum", "agile"],
    "Scrum":            ["scrum", "Scrum Master"],
    "Project Management": ["Proje Yönetimi", "proje yönetimi"],

    # Domain / Mimari
    "Microservices":    ["Mikroservis", "Mikroservis Mimarisi", "mikroservis", "Microservice"],
    "Event-Driven Architecture": ["Event-Driven", "Event Driven Architecture", "event-driven"],
    "Data Privacy":     ["Privacy", "Veri Gizliligi", "Veri Gizliliği", "Privacy-by-design"],
    "KVKK":             ["Kisisel Verilerin Korunmasi", "Kişisel Verilerin Korunması"],
    "GDPR":             ["General Data Protection Regulation"],
    "ISO 27001":        ["ISO27001", "Information Security Management"],
    "Power BI":         ["PowerBI", "Microsoft Power BI"],
    "NLP":              ["Natural Language Processing", "Dogal Dil Isleme", "Doğal Dil İşleme"],
    "MLOps":            ["ML Ops", "Model Operations"],
    "CI/CD":            ["CICD", "CI CD", "Continuous Integration", "Continuous Delivery"],
    "Data Mapping":     ["Veri Envanteri", "Data Inventory"],
    "Vendor Risk Management": ["Vendor Compliance", "Third Party Risk", "Supplier Risk"],
}

COMPANY_SYNONYMS: Dict[str, List[str]] = {
    "Garanti BBVA":     ["Garanti BBVA Teknoloji", "Garanti Bankası", "Garanti"],
    "Trendyol":         ["Trendyol Teknoloji", "Trendyol Group"],
    "Turkcell":         ["Turkcell Teknoloji", "Turkcell İletişim"],
    "İş Bankası":       ["Türkiye İş Bankası", "İşbank"],
    "Akbank":           ["Akbank T.A.Ş.", "Akbank Teknoloji"],
    "Yapı Kredi":       ["Yapı ve Kredi Bankası", "Yapı Kredi Teknoloji"],
    "Hepsiburada":      ["Hepsiburada Teknoloji", "D-Market"],
    "Getir":            ["Getir Teknoloji"],
    "Papara":           ["Papara Teknoloji", "Papara Elektronik Para"],
}

INSTITUTION_SYNONYMS: Dict[str, List[str]] = {
    "ODTÜ": ["ODTU", "Orta Doğu Teknik Üniversitesi", "Orta Dogu Teknik Universitesi", "METU", "Middle East Technical University"],
    "Boğaziçi Üniversitesi": ["Bogazici Universitesi", "Bogazici", "Boğaziçi", "BOUN"],
    "İstanbul Teknik Üniversitesi": ["Istanbul Teknik Universitesi", "İTÜ", "ITU", "Istanbul Teknik"],
    "Yıldız Teknik Üniversitesi": ["Yildiz Teknik Universitesi", "YTÜ", "YTU", "Yıldız Teknik", "Yildiz Teknik"],
    "Marmara Üniversitesi": ["Marmara Universitesi", "Marmara", "Marmara University"],
    "İstanbul Bilgi Üniversitesi": ["Istanbul Bilgi Universitesi", "Bilgi Üniversitesi", "Istanbul Bilgi", "İstanbul Bilgi"],
    "Hacettepe Üniversitesi": ["Hacettepe Universitesi", "Hacettepe"],
}

CERTIFICATION_SYNONYMS: Dict[str, List[str]] = {
    "ISO 27001": ["ISO27001", "ISO 27001 Lead Implementer", "ISO 27001 Lead Auditor"],
    "IAPP CIPP/E": ["CIPP/E", "CIPPE", "Certified Information Privacy Professional Europe"],
    "AWS Certified Solutions Architect": ["AWS SAA", "Solutions Architect Associate"],
    "CKA": ["Certified Kubernetes Administrator"],
    "CKAD": ["Certified Kubernetes Application Developer"],
    "Professional Scrum Master": ["PSM", "Scrum Master"],
}


def _normalize(text: str) -> str:
    """Karşılaştırma için normalize"""
    for k, v in {"İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s",
                 "Ğ": "g", "ğ": "g", "Ü": "u", "ü": "u", "Ö": "o",
                 "ö": "o", "Ç": "c", "ç": "c"}.items():
        text = text.replace(k, v)
    return text.lower().strip()


def _norm(text: str) -> str:
    for k, v in {
        "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s",
        "Ğ": "g", "ğ": "g", "Ü": "u", "ü": "u", "Ö": "o",
        "ö": "o", "Ç": "c", "ç": "c", "Ä°": "i", "Ä±": "i",
        "Å": "s", "ÅŸ": "s", "Ä": "g", "ÄŸ": "g", "Ãœ": "u",
        "Ã¼": "u", "Ã–": "o", "Ã¶": "o", "Ã‡": "c", "Ã§": "c",
    }.items():
        text = text.replace(k, v)
    return " ".join(text.lower().replace("_", " ").replace("-", " ").strip().split())


# ── Ana sınıf ─────────────────────────────────────────────────────────

class EntityResolver:
    """
    KG'deki duplicate düğümleri tespit edip birleştirir.

    Kullanım:
        resolver = EntityResolver(driver)
        stats = resolver.resolve_all()
    """

    def __init__(self, driver: Driver, fuzzy_threshold: int = 85):
        self.driver = driver
        self.fuzzy_threshold = fuzzy_threshold

    def resolve_all(self) -> Dict[str, int]:
        """Tüm entity tiplerini çözümler"""
        logger.info("🔍 Entity Resolution başlatılıyor...")

        stats = {
            "skills_canonical_property": self._resolve_canonical_property("Skill", ["canonical_name"]),
            "companies_canonical_property": self._resolve_canonical_property("Company", ["canonical_company_name", "canonical_name"]),
            "institutions_canonical_property": self._resolve_canonical_property("Institution", ["canonical_institution", "canonical_name"]),
            "skills_synonym": self._resolve_synonyms("Skill", SKILL_SYNONYMS),
            "companies_synonym": self._resolve_synonyms("Company", COMPANY_SYNONYMS),
            "institutions_synonym": self._resolve_synonyms("Institution", INSTITUTION_SYNONYMS),
            "certifications_synonym": self._resolve_synonyms("Certification", CERTIFICATION_SYNONYMS),
            "skills_fuzzy": self._resolve_fuzzy("Skill"),
            "companies_fuzzy": self._resolve_fuzzy("Company"),
            "institutions_fuzzy": self._resolve_fuzzy("Institution", threshold=88),
            "certifications_fuzzy": self._resolve_fuzzy("Certification", threshold=90),
        }

        total = sum(stats.values())
        logger.info(f"✅ Entity Resolution tamamlandı — {total} birleştirme: {stats}")
        return stats

    # ── Sinonim çözümleme ─────────────────────────────────────────────

    def _resolve_synonyms(self, label: str, synonyms: Dict[str, List[str]]) -> int:
        """Sinonim sözlüğüne göre düğümleri birleştirir"""
        merged_count = 0

        with self.driver.session() as session:
            for canonical, aliases in synonyms.items():
                for alias in aliases:
                    if alias == canonical:
                        continue

                    # Alias düğümü var mı kontrol et
                    check = session.run(f"""
                        MATCH (a:{label} {{name: $alias}})
                        RETURN count(a) AS cnt
                    """, alias=alias)

                    if check.single()["cnt"] > 0:
                        # Canonical düğümü yoksa oluştur
                        session.run(f"""
                            MERGE (:{label} {{name: $canonical}})
                        """, canonical=canonical)

                        # Birleştir
                        self._merge_nodes(session, label, alias, canonical)
                        merged_count += 1
                        logger.info(f"  🔗 {label}: '{alias}' → '{canonical}'")

        return merged_count

    def _resolve_canonical_property(self, label: str, property_names: List[str]) -> int:
        """Merge nodes when LLM/gold import stored a canonical property on the node."""
        merged_count = 0
        with self.driver.session() as session:
            for prop in property_names:
                rows = session.run(
                    f"""
                    MATCH (n:{label})
                    WHERE n.{prop} IS NOT NULL
                      AND n.name IS NOT NULL
                      AND n.{prop} <> n.name
                    RETURN n.name AS name, n.{prop} AS canonical
                    """
                ).data()
                for row in rows:
                    name = row.get("name")
                    canonical = row.get("canonical")
                    if not name or not canonical or _norm(name) == _norm(canonical):
                        continue
                    session.run(f"MERGE (:{label} {{name: $canonical}})", canonical=canonical)
                    self._merge_nodes(session, label, name, canonical)
                    merged_count += 1
                    logger.info(f"  canonical {label}: '{name}' -> '{canonical}'")
        return merged_count

    # ── Fuzzy çözümleme ───────────────────────────────────────────────

    def _resolve_fuzzy(self, label: str, threshold: int | None = None) -> int:
        """rapidfuzz ile benzer isimleri tespit edip birleştirir"""
        try:
            from rapidfuzz import fuzz
        except ImportError:
            logger.warning("⚠️ rapidfuzz yüklü değil, fuzzy matching atlanıyor")
            return 0

        # Tüm düğüm isimlerini çek
        with self.driver.session() as session:
            result = session.run(f"MATCH (n:{label}) RETURN n.name AS name")
            names = [r["name"] for r in result if r["name"]]

        if len(names) < 2:
            return 0

        # Benzer çiftleri bul
        resolved: Set[str] = set()
        merge_pairs: List[Tuple[str, str]] = []

        for i, name1 in enumerate(names):
            if name1 in resolved:
                continue
            for name2 in names[i + 1:]:
                if name2 in resolved:
                    continue

                n1 = _norm(name1)
                n2 = _norm(name2)

                # Tam eşleşme (sadece case/Türkçe karakter farkı)
                if n1 == n2:
                    shorter = name1 if len(name1) <= len(name2) else name2
                    longer = name2 if shorter == name1 else name1
                    merge_pairs.append((longer, shorter))
                    resolved.add(longer)
                    continue

                # Çok kısa isimlerde fuzzy match tehlikeli (JS ≈ C# gibi)
                if len(n1) < 4 or len(n2) < 4:
                    continue

                # Fuzzy eşleşme
                score = fuzz.ratio(n1, n2)
                if score >= (threshold or self.fuzzy_threshold):
                    shorter = name1 if len(name1) <= len(name2) else name2
                    longer = name2 if shorter == name1 else name1
                    merge_pairs.append((longer, shorter))
                    resolved.add(longer)

        # Birleştir
        merged_count = 0
        with self.driver.session() as session:
            for from_name, to_name in merge_pairs:
                self._merge_nodes(session, label, from_name, to_name)
                merged_count += 1
                logger.info(f"  🔗 {label} (fuzzy): '{from_name}' → '{to_name}'")

        return merged_count

    # ── Düğüm birleştirme ─────────────────────────────────────────────

    def _merge_nodes(self, session, label: str, from_name: str, to_name: str):
        """
        from_name düğümünün tüm ilişkilerini to_name'e taşır,
        sonra from_name düğümünü siler. APOC gerektirmez.
        """
        if label == "Skill":
            self._merge_skill(session, from_name, to_name)
        elif label == "Company":
            self._merge_company(session, from_name, to_name)
        elif label == "Institution":
            self._merge_institution(session, from_name, to_name)
        elif label == "Certification":
            self._merge_certification(session, from_name, to_name)
        else:
            self._merge_generic(session, label, from_name, to_name)

    def _merge_skill(self, session, from_name: str, to_name: str):
        """Skill düğümlerini birleştirir — HAS_SKILL ve USED_SKILL ilişkilerini taşır"""
        # HAS_SKILL ilişkilerini taşı (Candidate → Skill)
        session.run("""
            MATCH (c:Candidate)-[old:HAS_SKILL]->(from:Skill {name: $from_name})
            MERGE (to:Skill {name: $to_name})
            MERGE (c)-[new:HAS_SKILL]->(to)
            SET new.years_experience = coalesce(new.years_experience, old.years_experience),
                new.level = coalesce(new.level, old.level),
                new.confidence = coalesce(new.confidence, old.confidence),
                new.category = coalesce(new.category, old.category)
            DELETE old
        """, from_name=from_name, to_name=to_name)

        # USED_SKILL ilişkilerini taşı (Experience → Skill)
        session.run("""
            MATCH (e:Experience)-[old:USED_SKILL]->(from:Skill {name: $from_name})
            MERGE (to:Skill {name: $to_name})
            MERGE (e)-[:USED_SKILL]->(to)
            DELETE old
        """, from_name=from_name, to_name=to_name)

        # Eski düğümü sil
        session.run("""
            MATCH (from:Skill {name: $from_name})
            WHERE NOT exists((from)--())
            DELETE from
        """, from_name=from_name)

    def _merge_company(self, session, from_name: str, to_name: str):
        """Company düğümlerini birleştirir — AT_COMPANY ilişkilerini taşır"""
        session.run("""
            MATCH (e:Experience)-[old:AT_COMPANY]->(from:Company {name: $from_name})
            MERGE (to:Company {name: $to_name})
            MERGE (e)-[:AT_COMPANY]->(to)
            DELETE old
        """, from_name=from_name, to_name=to_name)

        session.run("""
            MATCH (from:Company {name: $from_name})
            WHERE NOT exists((from)--())
            DELETE from
        """, from_name=from_name)

    def _merge_institution(self, session, from_name: str, to_name: str):
        session.run("""
            MATCH (e:Education)-[old:AT_INSTITUTION]->(from:Institution {name: $from_name})
            MERGE (to:Institution {name: $to_name})
            MERGE (e)-[:AT_INSTITUTION]->(to)
            DELETE old
        """, from_name=from_name, to_name=to_name)

        session.run("""
            MATCH (from:Institution {name: $from_name})
            WHERE NOT exists((from)--())
            DELETE from
        """, from_name=from_name)

    def _merge_certification(self, session, from_name: str, to_name: str):
        session.run("""
            MATCH (c:Candidate)-[old:HAS_CERTIFICATION]->(from:Certification {name: $from_name})
            MERGE (to:Certification {name: $to_name})
            MERGE (c)-[:HAS_CERTIFICATION]->(to)
            DELETE old
        """, from_name=from_name, to_name=to_name)

        session.run("""
            MATCH (from:Certification {name: $from_name})
            WHERE NOT exists((from)--())
            DELETE from
        """, from_name=from_name)

    def _merge_generic(self, session, label: str, from_name: str, to_name: str):
        """Genel düğüm birleştirme — düğümü siler, ilişkileri taşımaz"""
        session.run(f"""
            MATCH (from:{label} {{name: $from_name}})
            DETACH DELETE from
        """, from_name=from_name)
