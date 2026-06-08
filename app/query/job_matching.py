import re
from typing import Any

from app.models.postgres import JobPost
from app.query.matcher import CandidateMatcher
from app.schemas.query import Degree, LanguageReq, QuerySpec, Seniority


CERT_PATTERNS = [
    (r"\biso\s*27001\b", "ISO 27001"),
    (r"\bckad\b", "CKAD"),
    (r"\bcka\b", "CKA"),
    (r"\baws certified\b|\baws saa\b|\bsolutions architect\b", "AWS Certified Solutions Architect"),
    (r"\bpmp\b", "PMP"),
    (r"\bitil\b", "ITIL"),
    (r"\bcipp/e\b|\bcippe\b", "IAPP CIPP/E"),
    (r"\bcissp\b", "CISSP"),
    (r"\bceh\b", "CEH"),
    (r"\bscrum master\b|\bpsm\b", "Professional Scrum Master"),
]

INSTITUTION_PATTERNS = [
    (r"\bodt[üu]\b|\borta dogu teknik\b|\borta doğu teknik\b|\bmetu\b", "ODTU"),
    (r"\bbo[gğ]azi[cç]i\b|\bbogazici\b|\bboun\b", "Bogazici Universitesi"),
    (r"\bit[üu]\b|\bistanbul teknik\b", "Istanbul Teknik Universitesi"),
    (r"\bmarmara\b", "Marmara Universitesi"),
    (r"\bbilgi [üu]niversitesi\b|\bistanbul bilgi\b", "Istanbul Bilgi Universitesi"),
    (r"\by[ıi]ld[ıi]z teknik\b|\bytu\b|\bytü\b", "Yildiz Teknik Universitesi"),
    (r"\bhacettepe\b", "Hacettepe Universitesi"),
]

LANGUAGE_PATTERNS = [
    (r"\bingilizce\b|\benglish\b", "English"),
    (r"\balmanca\b|\bgerman\b", "German"),
    (r"\bfrans[ıi]zca\b|\bfrench\b", "French"),
]


def _split_terms(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,;/\n]+", value) if item.strip()]


def _find_patterns(text: str, patterns: list[tuple[str, str]]) -> list[str]:
    found = []
    for pattern, value in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE) and value not in found:
            found.append(value)
    return found


def _education_level(text: str) -> Degree | None:
    if re.search(r"\bdoktora\b|\bphd\b", text, flags=re.IGNORECASE):
        return Degree.PHD
    if re.search(r"\byuksek lisans\b|\byüksek lisans\b|\bmaster\b|\bmsc\b|\bmba\b", text, flags=re.IGNORECASE):
        return Degree.MSC
    if re.search(r"\blisans\b|\bbachelor\b|\bbsc\b", text, flags=re.IGNORECASE):
        return Degree.BSC
    return None


def job_post_to_query_spec(job_post: JobPost) -> QuerySpec:
    seniority = None
    if job_post.seniority:
        try:
            seniority = Seniority(job_post.seniority.lower())
        except ValueError:
            seniority = None

    description = job_post.description or ""
    combined_text = " ".join(
        [
            job_post.title or "",
            description,
            job_post.location or "",
            " ".join(job_post.must_have_skills or []),
            " ".join(job_post.nice_to_have_skills or []),
        ]
    )
    locations = _split_terms(job_post.location)
    certifications = _find_patterns(combined_text, CERT_PATTERNS)
    institutions = _find_patterns(combined_text, INSTITUTION_PATTERNS)
    languages = [LanguageReq(code=code, min_level="B1") for code in _find_patterns(combined_text, LANGUAGE_PATTERNS)]
    return QuerySpec(
        title=job_post.title,
        seniority=seniority,
        must_have_skills=job_post.must_have_skills or [],
        nice_to_have_skills=job_post.nice_to_have_skills or [],
        min_experience_years=job_post.min_experience_years,
        locations=locations,
        languages=languages,
        education_level=_education_level(combined_text),
        education_institutions=institutions,
        must_have_certifications=certifications,
        free_text=job_post.description,
    )


def match_candidates_for_job(
    matcher: CandidateMatcher,
    job_post: JobPost,
    limit: int = 25,
    min_score: float = 18.0,
) -> list[dict[str, Any]]:
    query = job_post_to_query_spec(job_post)
    return matcher.search(
        query,
        limit=limit,
        min_score=min_score,
        apply_hard_gate=False,
    )
