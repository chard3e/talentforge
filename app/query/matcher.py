"""
Çok kriterli aday eşleştirme motoru.
QuerySpec'teki tüm alanları kullanarak adayları skorlar ve sıralar.
Açıklanabilir eşleştirme (explainable matching) sağlar.

Skorlama ağırlıkları:
  - must_have_skills:   %30
  - nice_to_have_skills: %10
  - seniority:          %15
  - title:              %10
  - experience_years:   %10
  - education:          %8
  - location:           %7
  - languages:          %5
  - certifications:     %5
"""

from typing import List, Dict, Any, Optional, Tuple
import logging
from neo4j import Driver
from app.schemas.query import QuerySpec, Seniority, Degree
from app.extraction.embedding_service import EmbeddingService, generate_embedding, build_candidate_summary

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────

SENIORITY_MAP = {"junior": 1, "mid": 2, "senior": 3, "lead": 4}

DEGREE_MAP = {"bsc": 1, "msc": 2, "phd": 3}

SKILL_ALIASES = {
    "JavaScript": ["JS", "Java Script", "ECMAScript"],
    "TypeScript": ["TS"],
    "Node.js": ["NodeJS", "Node", "Node JS"],
    "React": ["React.js", "ReactJS", "React JS"],
    "Next.js": ["NextJS", "Next JS"],
    "Python": ["Python3", "py", "piton"],
    "PostgreSQL": ["Postgres", "Postgre SQL", "PSQL"],
    "MongoDB": ["Mongo", "Mongo DB"],
    "Kubernetes": ["K8s", "kube"],
    "AWS": ["Amazon Web Services", "AWS Cloud"],
    "Google Cloud": ["GCP", "Google Cloud Platform"],
    "Machine Learning": ["ML", "Makine Ogrenmesi", "Makine Öğrenmesi"],
    "Deep Learning": ["DL", "Derin Ogrenme", "Derin Öğrenme"],
    "NLP": ["Natural Language Processing", "Dogal Dil Isleme", "Doğal Dil İşleme"],
    "MLOps": ["ML Ops", "Model Operations"],
    "CI/CD": ["CICD", "CI CD", "Continuous Integration", "Continuous Delivery"],
    "Microservices": ["Microservice", "Mikroservis", "Mikroservis Mimarisi"],
    "Event-Driven Architecture": ["Event Driven", "Event-Driven", "EDA"],
    "Data Privacy": ["Privacy", "Veri Gizliligi", "Veri Gizliliği"],
    "KVKK": ["Kisisel Verilerin Korunmasi", "Kişisel Verilerin Korunması"],
    "GDPR": ["General Data Protection Regulation"],
    "ISO 27001": ["ISO27001", "Information Security Management"],
    "Power BI": ["PowerBI"],
}

TITLE_ALIASES = {
    "Backend Developer": ["Backend Engineer", "Software Engineer", "API Developer"],
    "Frontend Developer": ["Frontend Engineer", "UI Developer"],
    "Full Stack Developer": ["Fullstack Developer", "Full-Stack Developer", "Full Stack Engineer"],
    "ML AI Engineer": ["ML Engineer", "AI Engineer", "Machine Learning Engineer", "Data Scientist"],
    "Data Analyst": ["BI Analyst", "Business Intelligence Analyst", "Veri Analisti"],
    "Data Engineer": ["Veri Muhendisi", "Veri Mühendisi", "ETL Developer"],
    "DevOps Cloud Engineer": ["Cloud Engineer", "Platform Engineer", "Site Reliability Engineer", "SRE"],
    "Cybersecurity Specialist": ["Security Specialist", "GRC Specialist", "Siber Guvenlik", "Siber Güvenlik"],
    "Data Privacy Specialist": ["Compliance Specialist", "Uyum Uzmani", "Uyum Uzmanı", "KVKK GDPR"],
    "Business Analyst": ["Is Analisti", "İş Analisti", "Process Analyst"],
    "Product Manager": ["Urun Yoneticisi", "Ürün Yöneticisi"],
    "Talent Acquisition Specialist": ["Recruiter", "People Ops", "Insan Kaynaklari", "İnsan Kaynakları"],
}

INSTITUTION_ALIASES = {
    "ODTU": ["ODTÜ", "Orta Dogu Teknik Universitesi", "Orta Doğu Teknik Üniversitesi", "METU", "Middle East Technical University"],
    "Bogazici Universitesi": ["Boğaziçi Üniversitesi", "Bogazici", "Boğaziçi", "BOUN"],
    "Istanbul Teknik Universitesi": ["İstanbul Teknik Üniversitesi", "ITU", "İTÜ", "Istanbul Teknik"],
    "Yildiz Teknik Universitesi": ["Yıldız Teknik Üniversitesi", "YTU", "YTÜ", "Yildiz Teknik", "Yıldız Teknik"],
    "Marmara Universitesi": ["Marmara Üniversitesi", "Marmara", "Marmara University"],
    "Istanbul Bilgi Universitesi": ["İstanbul Bilgi Üniversitesi", "Bilgi", "Istanbul Bilgi", "İstanbul Bilgi"],
    "Hacettepe Universitesi": ["Hacettepe Üniversitesi", "Hacettepe"],
}

SENIORITY_KEYWORDS = {
    "lead": ["lead", "principal", "staff", "müdür", "director", "vp", "cto", "cio", "baş"],
    "senior": ["senior", "sr.", "kıdemli", "uzman", "specialist", "expert"],
    "junior": ["junior", "jr.", "stajyer", "intern", "trainee", "çırak", "asistan"],
}

LANG_ALIASES = {
    "english":    ["ingilizce", "english", "eng", "en"],
    "ingilizce":  ["ingilizce", "english", "eng", "en"],
    "turkish":    ["turkce", "turkish", "tur", "tr"],
    "turkce":     ["turkce", "turkish", "tur", "tr"],
    "german":     ["almanca", "german", "deutsch", "ger", "de"],
    "almanca":    ["almanca", "german", "deutsch", "ger", "de"],
    "french":     ["fransizca", "french", "francais", "fra", "fr"],
    "fransizca":  ["fransizca", "french", "francais", "fra", "fr"],
    "spanish":    ["ispanyolca", "spanish", "espanol", "spa", "es"],
    "arabic":     ["arapca", "arabic", "ara", "ar"],
    "russian":    ["rusca", "russian", "rus", "ru"],
    "chinese":    ["cince", "chinese", "zho", "zh"],
    "japanese":   ["japonca", "japanese", "jpn", "ja"],
    "korean":     ["korece", "korean", "kor", "ko"],
    "italian":    ["italyanca", "italian", "ita", "it"],
    "portuguese": ["portekizce", "portuguese", "por", "pt"],
    "dutch":      ["felemenkce", "hollandaca", "dutch", "nld", "nl"],
}


# ── Yardımcı fonksiyon ────────────────────────────────────────────────

def _normalize_turkish(text: str) -> str:
    """Türkçe karakter normalizasyonu (İ/I/ı → i vb.)"""
    for k, v in {"İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s",
                 "Ğ": "g", "ğ": "g", "Ü": "u", "ü": "u", "Ö": "o",
                 "ö": "o", "Ç": "c", "ç": "c"}.items():
        text = text.replace(k, v)
    return text.lower().strip()


def _normalize_match_text(text: str) -> str:
    for k, v in {
        "İ": "i", "I": "i", "ı": "i", "Ş": "s", "ş": "s",
        "Ğ": "g", "ğ": "g", "Ü": "u", "ü": "u", "Ö": "o",
        "ö": "o", "Ç": "c", "ç": "c", "Ä°": "i", "Ä±": "i",
        "Å": "s", "ÅŸ": "s", "Ä": "g", "ÄŸ": "g", "Ãœ": "u",
        "Ã¼": "u", "Ã–": "o", "Ã¶": "o", "Ã‡": "c", "Ã§": "c",
    }.items():
        text = text.replace(k, v)
    return " ".join(text.lower().replace("_", " ").replace("-", " ").strip().split())


def _expanded_terms(text: str, aliases: Dict[str, List[str]]) -> set[str]:
    norm = _normalize_match_text(text)
    terms = {norm} if norm else set()
    for canonical, values in aliases.items():
        canonical_norm = _normalize_match_text(canonical)
        alias_norms = {_normalize_match_text(value) for value in values}
        if norm == canonical_norm or norm in alias_norms:
            terms.add(canonical_norm)
            terms.update(alias_norms)
    return {term for term in terms if term}


# ── Ana sınıf ─────────────────────────────────────────────────────────

def _skill_matches(query_skill: str, candidate_skills: set[str]) -> bool:
    """Match exact, contained, or fuzzy skill names after normalization."""
    query_terms = _expanded_terms(query_skill, SKILL_ALIASES)
    candidate_terms = set(candidate_skills)
    for candidate_skill in candidate_skills:
        candidate_terms.update(_expanded_terms(candidate_skill, SKILL_ALIASES))

    if query_terms & candidate_terms:
        return True

    if any(q in c or c in q for q in query_terms for c in candidate_terms if len(q) >= 3 and len(c) >= 3):
        return True

    try:
        from rapidfuzz import fuzz
        return any(fuzz.ratio(q, c) > 78 for q in query_terms for c in candidate_terms)
    except Exception:
        return False


class CandidateMatcher:
    """İK sorgusuna göre adayları çok kriterli skorlama ile bulan matcher."""

    def __init__(self, driver: Driver):
        self.driver = driver

    def search(
        self,
        query: QuerySpec,
        limit: int = 10,
        min_score: float = 25.0,
        apply_hard_gate: bool = True,
    ) -> List[Dict[str, Any]]:
        candidates = self._fetch_candidates()

        if not candidates:
            logger.warning("⚠️ KG'de aday bulunamadı")
            return []

        # 1. Graf tabanlı skorlama
        scored = []
        for candidate in candidates:
            result = self._score_candidate(candidate, query)
            scored.append(result)

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        graph_ranked = {c["name"]: i for i, c in enumerate(scored)}

        # 2. Vektör arama (free_text veya skill listesinden)
        vector_ranked = {}
        query_text = self._build_query_text(query)
        if query_text:
            try:
                embedding_svc = EmbeddingService(self.driver)
                vector_results = embedding_svc.vector_search(query_text, top_k=20)
                vector_ranked = {r["name"]: i for i, r in enumerate(vector_results)}
            except Exception as e:
                logger.warning(f"⚠️ Vektör arama başarısız: {e}")

        # 3. RRF birleştirme
        if vector_ranked:
            scored = self._rrf_merge(scored, graph_ranked, vector_ranked)

        scored = [
            candidate for candidate in scored
            if candidate["total_score"] >= min_score
            and (not apply_hard_gate or not candidate.get("_hard_gate_failed"))
        ]
        for candidate in scored:
            candidate.pop("_hard_gate_failed", None)

        logger.info(f"🔍 {len(scored)}/{len(candidates)} aday eşleşti")
        return scored[:limit]

    # ── Neo4j veri çekme ──────────────────────────────────────────────

    def _fetch_candidates(self) -> List[Dict[str, Any]]:
        """Neo4j'den tüm adayları ilişkileriyle birlikte çeker"""
        with self.driver.session() as session:
            result = session.run("""
                MATCH (c:Candidate)

                OPTIONAL MATCH (c)-[hs:HAS_SKILL]->(s:Skill)
                WITH c, collect({
                    name: s.name,
                    category: hs.category,
                    years: hs.years_experience,
                    level: hs.level,
                    confidence: hs.confidence
                }) AS raw_skills
                WITH c, [x IN raw_skills WHERE x.name IS NOT NULL] AS skills

                OPTIONAL MATCH (c)-[:HAS_EXPERIENCE]->(e:Experience)-[:AT_COMPANY]->(co:Company)
                WITH c, skills, collect({
                    role: e.role_title,
                    company: co.name,
                    start_date: e.start_date,
                    end_date: e.end_date,
                    is_current: e.is_current,
                    location: e.location,
                    description: e.description
                }) AS experiences

                OPTIONAL MATCH (c)-[:HAS_EDUCATION]->(ed:Education)-[:AT_INSTITUTION]->(i:Institution)
                WITH c, skills, experiences, collect({
                    degree: ed.degree,
                    field: ed.field,
                    institution: i.name,
                    gpa: ed.gpa
                }) AS educations

                OPTIONAL MATCH (c)-[:SPEAKS]->(l:Language)
                WITH c, skills, experiences, educations, collect(l.name) AS languages

                OPTIONAL MATCH (c)-[:HAS_CERTIFICATION]->(ct:Certification)
                WITH c, skills, experiences, educations, languages, collect(ct.name) AS certifications

                OPTIONAL MATCH (c)-[:HAS_PROJECT]->(p:Project)
                WITH c, skills, experiences, educations, languages, certifications, collect({
                    name: p.name,
                    description: p.description,
                    role: p.role,
                    start_date: p.start_date,
                    end_date: p.end_date,
                    url: p.url,
                    confidence: p.confidence
                }) AS raw_projects
                WITH c, skills, experiences, educations, languages, certifications,
                     [x IN raw_projects WHERE x.name IS NOT NULL] AS projects

                RETURN
                    c.name AS name,
                    c.email AS email,
                    c.phone AS phone,
                    c.location AS location,
                    c.summary AS summary,
                    c.id AS id,
                    skills,
                    experiences,
                    educations,
                    languages,
                    certifications,
                    projects
            """)
            return [record.data() for record in result]

    # ── Ana skorlama ──────────────────────────────────────────────────

    def _score_candidate(self, candidate: Dict, query: QuerySpec) -> Dict[str, Any]:
        """
        Score only criteria that the user actually supplied.

        Empty filters do not award points. The weighted score is normalized by
        the active criteria weight, so a small query and a detailed query both
        produce an interpretable 0-100 score.
        """
        weights = {
            "must_skills": 0.30,
            "nice_skills": 0.10,
            "seniority": 0.15,
            "title": 0.10,
            "experience": 0.10,
            "education": 0.08,
            "education_institution": 0.08,
            "location": 0.07,
            "languages": 0.05,
            "certifications": 0.05,
        }

        active_criteria = []
        reasons = []

        def add_criterion(name: str, score_detail: Tuple[float, str]) -> None:
            score, detail = score_detail
            active_criteria.append((name, weights[name], score))
            if detail:
                reasons.append(detail)

        if query.must_have_skills:
            add_criterion("must_skills", self._score_must_skills(candidate, query.must_have_skills))

        if query.nice_to_have_skills:
            add_criterion("nice_skills", self._score_nice_skills(candidate, query.nice_to_have_skills))

        if query.seniority:
            add_criterion("seniority", self._score_seniority(candidate, query.seniority))

        if query.title:
            add_criterion("title", self._score_title(candidate, query.title))

        if query.min_experience_years and query.min_experience_years > 0:
            add_criterion(
                "experience",
                self._score_experience_years(candidate, query.min_experience_years),
            )

        if query.education_level:
            add_criterion("education", self._score_education(candidate, query.education_level))

        if query.education_institutions:
            add_criterion(
                "education_institution",
                self._score_education_institution(candidate, query.education_institutions),
            )

        if query.locations:
            add_criterion("location", self._score_location(candidate, query.locations))

        if query.languages:
            add_criterion("languages", self._score_languages(candidate, query.languages))

        if query.must_have_certifications:
            add_criterion(
                "certifications",
                self._score_certifications(candidate, query.must_have_certifications),
            )

        if active_criteria:
            active_weight = sum(weight for _, weight, _ in active_criteria)
            weighted_sum = sum(score * weight for _, weight, score in active_criteria)
            total = (weighted_sum / active_weight) * 100
            score_breakdown = {
                name: round((score * weight / active_weight) * 100, 1)
                for name, weight, score in active_criteria
            }
        else:
            total = 50.0
            score_breakdown = {"baseline": 50.0}

        must_score = next(
            (score for name, _, score in active_criteria if name == "must_skills"),
            None,
        )
        if must_score == 0:
            total = 0.0
            score_breakdown["must_have_gate"] = 0.0
            hard_gate_failed = True
        elif must_score is not None and must_score < 0.30:
            total *= must_score
            score_breakdown["must_have_gate"] = round(must_score * 100, 1)
            hard_gate_failed = False
        else:
            hard_gate_failed = False

        skill_names = [s["name"] for s in candidate["skills"] if s.get("name")]

        return {
            "name": candidate["name"],
            "email": candidate["email"],
            "candidate_id": candidate.get("id"),
            "location": candidate["location"],
            "summary": candidate.get("summary"),
            "skills": skill_names,
            "experience_count": len(candidate["experiences"]),
            "total_score": round(total, 1),
            "score_breakdown": score_breakdown,
            "reasons": reasons,
            "_hard_gate_failed": hard_gate_failed,
        }

    # ── Kriter fonksiyonları ──────────────────────────────────────────

    def _score_must_skills(self, candidate: Dict, must_skills: List[str]) -> Tuple[float, str]:
        """Zorunlu yetenek eşleştirmesi (case-insensitive, Türkçe uyumlu)"""
        if not must_skills:
            return 1.0, None

        cand_skills = {_normalize_turkish(s["name"]) for s in candidate["skills"] if s.get("name")}
        matched = [skill for skill in must_skills if _skill_matches(skill, cand_skills)]
        matched_set = set(matched)
        missing = [skill for skill in must_skills if skill not in matched_set]

        score = len(matched) / len(must_skills)
        detail = f"Zorunlu yetenekler: {len(matched)}/{len(must_skills)}"
        if matched:
            detail += f" ✓[{', '.join(matched)}]"
        if missing:
            detail += f" ✗[{', '.join(missing)}]"
        return score, detail

    def _score_nice_skills(self, candidate: Dict, nice_skills: List[str]) -> Tuple[float, str]:
        """Tercih edilen yetenekler (bonus)"""
        if not nice_skills:
            return 1.0, None

        cand_skills = {_normalize_turkish(s["name"]) for s in candidate["skills"] if s.get("name")}
        matched = [skill for skill in nice_skills if _skill_matches(skill, cand_skills)]
        score = len(matched) / len(nice_skills)

        if matched:
            return score, f"Bonus yetenekler: ✓ {', '.join(matched)}"
        return score, f"Bonus yetenekler: eşleşme yok"

    def _score_seniority(self, candidate: Dict, required: Optional[Seniority]) -> Tuple[float, str]:
        """
        Kıdem seviyesi uyumu.
        Tam eşleşme en iyi, ±1 kademe kabul edilebilir, 2+ fark uyumsuz.
        Lead adayı Junior pozisyona uygun DEĞİL, Junior adayı Lead'e de uygun DEĞİL.
        """
        if not required:
            return 1.0, None

        required_level = SENIORITY_MAP.get(required.value, 2)
        candidate_level = self._detect_seniority(candidate)
        diff = candidate_level - required_level

        if diff == 0:
            score, label = 1.0, "✓ tam uyum"
        elif diff == 1:
            score, label = 0.6, "biraz üst kıdem"
        elif diff == -1:
            score, label = 0.5, "biraz alt kıdem"
        else:
            score, label = 0.1, "uyumsuz"

        detail = f"Kıdem: {label} (aday: {candidate_level}, aranan: {required_level})"
        return score, detail

    def _detect_seniority(self, candidate: Dict) -> int:
        """Adayın deneyimlerindeki en yüksek kıdem seviyesini çıkarır"""
        max_level = 1

        for exp in candidate.get("experiences", []):
            role = _normalize_turkish(exp.get("role") or "")

            matched = False
            for level_name, keywords in SENIORITY_KEYWORDS.items():
                if any(kw in role for kw in keywords):
                    max_level = max(max_level, SENIORITY_MAP[level_name])
                    matched = True
                    break

            if not matched:
                max_level = max(max_level, 2)

        return max_level

    def _score_title(self, candidate: Dict, title: Optional[str]) -> Tuple[float, str]:
        """Pozisyon unvanı eşleştirmesi — adayın deneyimlerindeki role_title ile karşılaştırır"""
        if not title:
            return 1.0, None

        title_terms = _expanded_terms(title, TITLE_ALIASES)
        title_words = set().union(*(term.split() for term in title_terms)) if title_terms else set()

        best_score = 0.0
        best_role = ""

        for exp in candidate.get("experiences", []):
            role = exp.get("role") or ""
            role_terms = _expanded_terms(role, TITLE_ALIASES)
            role_norm = _normalize_match_text(role)
            role_words = set().union(*(term.split() for term in role_terms)) if role_terms else set(role_norm.split())

            if title_terms & role_terms or any(
                title_term in role_term or role_term in title_term
                for title_term in title_terms
                for role_term in role_terms
                if len(title_term) >= 4 and len(role_term) >= 4
            ):
                best_score = 1.0
                best_role = role
                break

            if title_words and role_words:
                overlap = len(title_words & role_words) / len(title_words)
                if overlap > best_score:
                    best_score = overlap
                    best_role = role

        if best_score >= 0.8:
            return best_score, f"Pozisyon: ✓ '{best_role}' eşleşti"
        elif best_score > 0:
            return best_score, f"Pozisyon: kısmi eşleşme '{best_role}'"
        return 0.0, f"Pozisyon: '{title}' eşleşmedi"

    def _score_experience_years(self, candidate: Dict, min_years: Optional[int]) -> Tuple[float, str]:
        """Toplam deneyim yılı kontrolü"""
        if min_years is None:
            return 1.0, None

        total_years = self._calculate_total_experience(candidate)

        if min_years == 0:
            return 1.0, f"Deneyim: ✓ {total_years} yıl (min yok)"

        if total_years >= min_years:
            score = 1.0
        elif total_years >= min_years * 0.7:
            score = 0.6
        else:
            score = 0.2

        return score, f"Deneyim: {total_years} yıl (min {min_years})"

    def _calculate_total_experience(self, candidate: Dict) -> int:
        """Deneyim sürelerinden toplam yıl hesaplar"""
        total_months = 0
        month_map = {
            "oca": 1, "sub": 2, "mar": 3, "nis": 4, "may": 5, "haz": 6,
            "tem": 7, "agu": 8, "eyl": 9, "eki": 10, "kas": 11, "ara": 12,
            "jan": 1, "feb": 2, "apr": 4, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }

        for exp in candidate.get("experiences", []):
            start = exp.get("start_date") or ""
            end = exp.get("end_date") or ""

            start_months = self._parse_date_to_months(start, month_map)

            if exp.get("is_current") or not end:
                end_months = 2026 * 12 + 5
            else:
                end_months = self._parse_date_to_months(end, month_map)

            if start_months and end_months:
                total_months += max(0, end_months - start_months)

        return total_months // 12

    def _parse_date_to_months(self, date_str: str, month_map: Dict) -> Optional[int]:
        """'Şub 2022' → ay sayısı (yıl*12 + ay)"""
        if not date_str:
            return None
        parts = _normalize_turkish(date_str).split()
        if len(parts) == 2:
            month = month_map.get(parts[0][:3], 0)
            try:
                year = int(parts[1])
                return year * 12 + month
            except ValueError:
                return None
        return None

    def _score_education(self, candidate: Dict, required: Optional[Degree]) -> Tuple[float, str]:
        """Eğitim seviyesi kontrolü"""
        if not required:
            return 1.0, None

        required_level = DEGREE_MAP.get(required.value, 1)
        candidate_level = self._detect_education_level(candidate)

        if candidate_level >= required_level:
            return 1.0, f"Eğitim: ✓ (seviye {candidate_level} ≥ {required_level})"
        return 0.3, f"Eğitim yetersiz: seviye {candidate_level} < {required_level}"

    def _detect_education_level(self, candidate: Dict) -> int:
        """Adayın en yüksek eğitim seviyesini belirler"""
        max_level = 0
        degree_keywords = {
            "phd": ["phd", "doktora", "doctorate"],
            "msc": ["msc", "master", "yuksek lisans", "m.sc", "mba"],
            "bsc": ["bsc", "lisans", "bachelor", "b.sc", "muhendislik", "engineering"],
        }

        for edu in candidate.get("educations", []):
            degree = _normalize_turkish(edu.get("degree") or "")
            for level_name, keywords in degree_keywords.items():
                if any(kw in degree for kw in keywords):
                    max_level = max(max_level, DEGREE_MAP[level_name])
                    break

        return max_level if max_level > 0 else 1

    def _score_education_institution(self, candidate: Dict, institutions: List[str]) -> Tuple[float, str]:
        """Okul/kurum adi eslestirmesi. Orn: ODTU, Marmara, Bogazici."""
        if not institutions:
            return 1.0, None

        candidate_institutions = [
            edu.get("institution") or ""
            for edu in candidate.get("educations", [])
            if edu.get("institution")
        ]
        candidate_norms = set()
        for name in candidate_institutions:
            candidate_norms.update(_expanded_terms(name, INSTITUTION_ALIASES))
        matched = []
        missing = []

        for institution in institutions:
            institution_terms = _expanded_terms(institution, INSTITUTION_ALIASES)
            is_match = bool(institution_terms & candidate_norms) or any(
                institution_norm in candidate_name or candidate_name in institution_norm
                for institution_norm in institution_terms
                for candidate_name in candidate_norms
                if len(institution_norm) >= 4 and len(candidate_name) >= 4
            )
            if not is_match:
                try:
                    from rapidfuzz import fuzz
                    is_match = any(
                        fuzz.ratio(institution_norm, candidate_name) > 78
                        for institution_norm in institution_terms
                        for candidate_name in candidate_norms
                    )
                except Exception:
                    is_match = False

            if is_match:
                matched.append(institution)
            else:
                missing.append(institution)

        score = len(matched) / len(institutions)
        detail = f"Egitim kurumu: {len(matched)}/{len(institutions)}"
        if matched:
            detail += f" ✓ {', '.join(matched)}"
        if missing:
            detail += f" ✗ {', '.join(missing)}"
        return score, detail

    def _score_location(self, candidate: Dict, locations: List[str]) -> Tuple[float, str]:
        """Lokasyon eşleştirmesi (Türkçe karakter uyumlu)"""
        if not locations:
            return 1.0, None

        cand_loc = _normalize_turkish(candidate.get("location") or "")
        for loc in locations:
            if _normalize_turkish(loc) in cand_loc:
                return 1.0, f"Lokasyon: ✓ {loc}"

        return 0.0, f"Lokasyon uyumsuz: aday '{candidate.get('location')}', aranan '{', '.join(locations)}'"

    def _score_languages(self, candidate: Dict, languages) -> Tuple[float, str]:
        """Dil gereksinimi kontrolü — KG'deki Language düğümlerinden arar"""
        if not languages:
            return 1.0, None

        cand_langs = " ".join(
            _normalize_turkish(l) for l in candidate.get("languages", [])
        )

        matched = []
        missing = []
        for lang_req in languages:
            code = _normalize_turkish(lang_req.code)
            if self._language_matches(code, cand_langs):
                matched.append(lang_req.code)
            else:
                missing.append(lang_req.code)

        total = len(languages)
        score = len(matched) / total if total > 0 else 0

        detail = f"Diller: {len(matched)}/{total}"
        if matched:
            detail += f" ✓[{', '.join(matched)}]"
        if missing:
            detail += f" ✗[{', '.join(missing)}]"
        return score, detail

    def _language_matches(self, query_lang: str, candidate_text: str) -> bool:
        """Dil eşleştirme: alias tablosu + rapidfuzz fuzzy match"""
        # 1. Direkt eşleşme
        if query_lang in candidate_text:
            return True

        # 2. Alias tablosu (Türkçe↔İngilizce↔ISO kodu)
        aliases = LANG_ALIASES.get(query_lang, [])
        if any(alias in candidate_text for alias in aliases):
            return True

        # 3. rapidfuzz fuzzy match (son çare)
        try:
            from rapidfuzz import fuzz
            for word in candidate_text.split():
                if len(word) > 3 and fuzz.partial_ratio(query_lang, word) > 80:
                    return True
        except Exception:
            pass

        return False

    def _score_certifications(self, candidate: Dict, required_certs: List[str]) -> Tuple[float, str]:
        """Sertifika eşleştirmesi — KG'deki Certification düğümlerinden arar"""
        if not required_certs:
            return 1.0, None

        # Hem skill'lerden hem certification'lardan ara
        cand_certs = {_normalize_turkish(c) for c in candidate.get("certifications", [])}
        cand_skills = {_normalize_turkish(s["name"]) for s in candidate["skills"] if s.get("name")}
        all_cand = cand_certs | cand_skills

        matched = []
        missing = []
        for cert in required_certs:
            cert_norm = _normalize_turkish(cert)
            if any(cert_norm in c for c in all_cand):
                matched.append(cert)
            else:
                missing.append(cert)

        score = len(matched) / len(required_certs)

        if matched:
            return score, f"Sertifikalar: ✓ {', '.join(matched)}"
        return score, f"Sertifikalar: eksik [{', '.join(required_certs)}]"
    
    def _build_query_text(self, query: QuerySpec) -> str:
        parts = []
        if query.title:
            parts.append(query.title)
        if query.must_have_skills:
            parts.append(", ".join(query.must_have_skills))
        if query.nice_to_have_skills:
            parts.append(", ".join(query.nice_to_have_skills))
        if query.education_institutions:
            parts.append("Education institutions: " + ", ".join(query.education_institutions))
        if query.free_text:
            parts.append(query.free_text)
        return ". ".join(parts)

    def _rrf_merge(self, scored: List[Dict], graph_ranked: Dict, vector_ranked: Dict, k: int = 60) -> List[Dict]:
        """Reciprocal Rank Fusion — graf ve vektör sıralamalarını birleştirir"""
        rrf_scores = {}
        for name, rank in graph_ranked.items():
            rrf_scores[name] = rrf_scores.get(name, 0) + 1.0 / (k + rank)
        for name, rank in vector_ranked.items():
            rrf_scores[name] = rrf_scores.get(name, 0) + 1.0 / (k + rank)

        # Orijinal skorları RRF ile ağırlıkla
        for candidate in scored:
            name = candidate["name"]
            rrf = rrf_scores.get(name, 0)
            graph_score = candidate["total_score"]
            # %70 graf, %30 vektör
            candidate["total_score"] = round(graph_score * 0.7 + rrf * 3000 * 0.3, 1)
            candidate["score_breakdown"]["vector_rrf"] = round(rrf * 3000, 1)

        scored.sort(key=lambda x: x["total_score"], reverse=True)
        return scored
