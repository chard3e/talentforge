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

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────────

SENIORITY_MAP = {"junior": 1, "mid": 2, "senior": 3, "lead": 4}

DEGREE_MAP = {"bsc": 1, "msc": 2, "phd": 3}

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


# ── Ana sınıf ─────────────────────────────────────────────────────────

class CandidateMatcher:
    """İK sorgusuna göre adayları çok kriterli skorlama ile bulan matcher."""

    def __init__(self, driver: Driver):
        self.driver = driver

    def search(self, query: QuerySpec, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Adayları çok kriterli skorlama ile bulur ve sıralar.
        Her aday için skor kırılımı ve açıklama (reasons) döner.
        """
        candidates = self._fetch_candidates()

        if not candidates:
            logger.warning("⚠️ KG'de aday bulunamadı")
            return []

        scored = []
        for candidate in candidates:
            result = self._score_candidate(candidate, query)
            if result["total_score"] > 0:
                scored.append(result)

        scored.sort(key=lambda x: x["total_score"], reverse=True)

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
                }) AS skills

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

                RETURN
                    c.name AS name,
                    c.email AS email,
                    c.phone AS phone,
                    c.location AS location,
                    c.summary AS summary,
                    skills,
                    experiences,
                    educations,
                    languages,
                    certifications
            """)
            return [record.data() for record in result]

    # ── Ana skorlama ──────────────────────────────────────────────────

    def _score_candidate(self, candidate: Dict, query: QuerySpec) -> Dict[str, Any]:
        """Her kriter için ayrı skor hesaplar ve birleştirir"""
        scores = {}
        reasons = []

        criteria = [
            ("must_skills",    0.30, self._score_must_skills(candidate, query.must_have_skills)),
            ("nice_skills",    0.10, self._score_nice_skills(candidate, query.nice_to_have_skills)),
            ("seniority",      0.15, self._score_seniority(candidate, query.seniority)),
            ("title",          0.10, self._score_title(candidate, query.title)),
            ("experience",     0.10, self._score_experience_years(candidate, query.min_experience_years)),
            ("education",      0.08, self._score_education(candidate, query.education_level)),
            ("location",       0.07, self._score_location(candidate, query.locations)),
            ("languages",      0.05, self._score_languages(candidate, query.languages)),
            ("certifications", 0.05, self._score_certifications(candidate, query.must_have_certifications)),
        ]

        for name, weight, (score, detail) in criteria:
            scores[name] = score * weight
            if detail:
                reasons.append(detail)

        total = sum(scores.values())
        skill_names = [s["name"] for s in candidate["skills"] if s.get("name")]

        return {
            "name": candidate["name"],
            "email": candidate["email"],
            "location": candidate["location"],
            "summary": candidate.get("summary"),
            "skills": skill_names,
            "experience_count": len(candidate["experiences"]),
            "total_score": round(total * 100, 1),
            "score_breakdown": {k: round(v * 100, 1) for k, v in scores.items()},
            "reasons": reasons,
        }

    # ── Kriter fonksiyonları ──────────────────────────────────────────

    def _score_must_skills(self, candidate: Dict, must_skills: List[str]) -> Tuple[float, str]:
        """Zorunlu yetenek eşleştirmesi (case-insensitive, Türkçe uyumlu)"""
        if not must_skills:
            return 1.0, None

        cand_skills = {_normalize_turkish(s["name"]) for s in candidate["skills"] if s.get("name")}
        matched = [s for s in must_skills if _normalize_turkish(s) in cand_skills]
        missing = [s for s in must_skills if _normalize_turkish(s) not in cand_skills]

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
        matched = [s for s in nice_skills if _normalize_turkish(s) in cand_skills]
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

        title_norm = _normalize_turkish(title)
        title_words = set(title_norm.split())

        best_score = 0.0
        best_role = ""

        for exp in candidate.get("experiences", []):
            role = exp.get("role") or ""
            role_norm = _normalize_turkish(role)
            role_words = set(role_norm.split())

            if title_norm in role_norm or role_norm in title_norm:
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