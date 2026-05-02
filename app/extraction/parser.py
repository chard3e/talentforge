from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class CVParser:
    """CV dosyalarını parse eden temel sınıf (pdfplumber + python-docx)"""

    def __init__(self):
        logger.info("✅ CVParser initialized (pdfplumber + python-docx)")

    def parse(self, file_path: str | Path) -> Dict[str, Any]:
        """
        CV dosyasını parse eder.
        PDF için pdfplumber, DOCX için python-docx kullanılır.
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"CV dosyası bulunamadı: {file_path}")

        logger.info(f"📄 Parsing CV: {file_path.name}")

        try:
            if file_path.suffix.lower() == ".pdf":
                return self._parse_pdf(file_path)
            elif file_path.suffix.lower() == ".docx":
                return self._parse_docx(file_path)
            else:
                raise ValueError(f"Desteklenmeyen dosya türü: {file_path.suffix}")

        except Exception as e:
            logger.error(f"Parsing error: {e}")
            raise

    def _parse_pdf(self, file_path: Path) -> Dict[str, Any]:
        """PDF dosyalarını pdfplumber ile parse eder"""
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)

            full_text = "\n\n".join(pages_text)

        return {
            "file_name": file_path.name,
            "file_type": "pdf",
            "raw_text": full_text[:15000],  # çok uzun metinleri kısalt
            "total_pages": len(pages_text),
            "status": "success",
            "parser": "pdfplumber"
        }

    def _parse_docx(self, file_path: Path) -> Dict[str, Any]:
        """DOCX dosyalarını python-docx ile parse eder"""
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        full_text = "\n\n".join(paragraphs)

        return {
            "file_name": file_path.name,
            "file_type": "docx",
            "raw_text": full_text[:15000],
            "total_paragraphs": len(paragraphs),
            "status": "success",
            "parser": "python-docx"
        }