"""
LLM ile CV'den yapılandırılmış bilgi çıkaran sınıf.
Few-shot + Chain-of-Thought + Semantic Inference prompt stratejisi kullanır.

Desteklenen backend'ler (.env'de tanımlı API key'e göre otomatik seçilir):
  Öncelik: GROQ_API_KEY > HF_TOKEN
"""

from typing import Optional
import logging
import os
import instructor
from openai import OpenAI
from dotenv import load_dotenv
from app.schemas.cv_extraction import CVExtraction
from app.extraction.prompts import SYSTEM_PROMPT, build_user_prompt

load_dotenv()

logger = logging.getLogger(__name__)


def _build_client():
    """
    .env'deki API key'e göre uygun backend'i seçer.
    Öncelik: GROQ_API_KEY > HF_TOKEN
    Döndürür: (instructor_client, model_name, backend_name)
    """
    groq_key = os.getenv("GROQ_API_KEY")
    hf_token = os.getenv("HF_TOKEN")

    if groq_key:
        model = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")
        client = instructor.from_openai(
            OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=groq_key,
            )
        )
        return client, model, "Groq"

    elif hf_token:
        model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        client = instructor.from_openai(
            OpenAI(
                base_url="https://router.huggingface.co/v1",
                api_key=hf_token,
            )
        )
        return client, model, "HuggingFace"

    else:
        raise ValueError(
            "LLM backend bulunamadı! "
            ".env dosyasında GROQ_API_KEY veya HF_TOKEN tanımlayın."
        )


class LLMExtractor:
    """
    LLM ile CV metninden yapılandırılmış bilgi çıkarır.

    Özellikler:
      - Few-shot + CoT prompt stratejisi
      - Dolaylı anlam çıkarımı (semantic inference)
      - Yetenek normalizasyonu (sinonim → standart form)
      - Instructor ile Pydantic modele zorunlu uyum
      - Placeholder tespiti ve temizleme
    """

    PLACEHOLDER_VALUES = {
        "company name", "job position", "university name",
        "department name", "high school name", "certificate name",
        "not specified", "belirtilmemiş", "n/a", "none",
    }

    def __init__(self):
        self.client, self.model, self.backend = _build_client()
        logger.info(
            f"✅ LLMExtractor initialized — backend: {self.backend}, model: {self.model}"
        )

    def extract(self, cv_text: str) -> Optional[CVExtraction]:
        """
        CV metninden yapılandırılmış bilgi çıkarır.

        Pipeline:
          1. Metin uzunluk kontrolü
          2. Few-shot + CoT prompt oluşturma
          3. LLM çağrısı (instructor ile yapısal çıktı)
          4. Post-processing (placeholder temizleme)

        Args:
            cv_text: Parse edilmiş CV ham metni

        Returns:
            CVExtraction Pydantic modeli veya hata durumunda None
        """
        if not cv_text or len(cv_text.strip()) < 50:
            logger.warning("⚠️ CV metni çok kısa, çıkarım yapılamıyor.")
            return None

        try:
            logger.info(f"🤖 LLM extraction started — {self.backend}/{self.model}")

            user_prompt = build_user_prompt(cv_text)

            extraction: CVExtraction = self.client.chat.completions.create(
                model=self.model,
                response_model=CVExtraction,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
                max_tokens=8192,
                max_retries=2,
            )

            # Post-processing: placeholder temizleme
            extraction = self._truncate_long_texts(extraction)
            extraction = self._deduplicate_skills(extraction)
            extraction = self._clean_placeholders(extraction)
            extraction = self._clean_placeholders(extraction)

            skill_count = len(extraction.skills)
            exp_count = len(extraction.experiences)
            edu_count = len(extraction.educations)
            logger.info(
                f"✅ LLM extraction completed — "
                f"{skill_count} skills, {exp_count} experiences, {edu_count} educations"
            )
            return extraction

        except Exception as e:
            logger.error(f"❌ LLM extraction error: {e}")
            return None
        

    def _clean_placeholders(self, extraction: CVExtraction) -> CVExtraction:
        """
        LLM çıktısındaki placeholder değerleri temizler.
        "Company Name", "University Name" gibi değerler → None / "Belirtilmemiş"
        """
        # İsim
        if extraction.candidate_name and \
           extraction.candidate_name.lower().strip() in self.PLACEHOLDER_VALUES:
            extraction.candidate_name = None

        # Deneyimler
        for exp in extraction.experiences:
            if exp.company_name.lower().strip() in self.PLACEHOLDER_VALUES:
                exp.company_name = "Belirtilmemiş"
            if exp.role_title.lower().strip() in self.PLACEHOLDER_VALUES:
                exp.role_title = "Belirtilmemiş"

        # Eğitimler
        for edu in extraction.educations:
            if edu.institution.lower().strip() in self.PLACEHOLDER_VALUES:
                edu.institution = "Belirtilmemiş"
            if edu.degree.lower().strip() in self.PLACEHOLDER_VALUES:
                edu.degree = "Belirtilmemiş"
            if edu.field.lower().strip() in self.PLACEHOLDER_VALUES:
                edu.field = "Belirtilmemiş"

        return extraction
    
    def _truncate_long_texts(self, extraction: CVExtraction) -> CVExtraction:
        for skill in extraction.skills:
            if skill.evidence_text and len(skill.evidence_text) > 150:
                skill.evidence_text = skill.evidence_text[:150].rsplit(" ", 1)[0]
        for exp in extraction.experiences:
            if exp.evidence_text and len(exp.evidence_text) > 500:
                exp.evidence_text = exp.evidence_text[:500].rsplit(" ", 1)[0]
        return extraction

    def _deduplicate_skills(self, extraction: CVExtraction) -> CVExtraction:
        seen = {}
        unique = []
        for skill in extraction.skills:
            key = skill.name.lower().strip()
            if key not in seen:
                seen[key] = True
                unique.append(skill)
        extraction.skills = unique
        return extraction