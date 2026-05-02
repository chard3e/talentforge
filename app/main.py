from fastapi import FastAPI, UploadFile, File, HTTPException
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import tempfile
import os
from typing import List, Dict

from app.core.config import get_settings
from app.core.database import get_neo4j_driver, close_neo4j_driver
from app.extraction.pipeline import CVProcessingPipeline
from app.schemas.cv_extraction import CVExtraction
from app.schemas.query import QuerySpec
from app.query.matcher import CandidateMatcher

settings = get_settings()

# Logging ayarları
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
pipeline = CVProcessingPipeline()
matcher = CandidateMatcher(get_neo4j_driver())

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlangıç ve kapanış işlemleri"""
    logger.info("🚀 TalentForge başlatılıyor...")
    get_neo4j_driver()
    logger.info("✅ Neo4j bağlantısı hazır")
    yield
    close_neo4j_driver()
    logger.info("👋 TalentForge kapatılıyor...")

app = FastAPI(
    title="TalentForge",
    description="LLM-Driven Knowledge Graph for AI-Powered HR Candidate Matching System",
    version="0.1.0",
    lifespan=lifespan
)

@app.get("/")
async def root():
    return {
        "message": "🚀 TalentForge API is running successfully!",
        "status": "healthy",
        "environment": settings.ENV,
        "docs_url": "/docs",
        "neo4j": "Connected ✅"
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "neo4j": "connected",
        "environment": settings.ENV
    }

@app.post("/upload-cv", response_model=CVExtraction)
async def upload_cv(file: UploadFile = File(...)):
    """
    CV dosyası yükle ve yapılandırılmış bilgi çıkar + KG'ye yaz.
    Desteklenen formatlar: PDF, DOCX
    """
    allowed_extensions = {".pdf", ".docx"}
    file_ext = Path(file.filename).suffix.lower()
    
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Desteklenmeyen dosya türü. Sadece PDF ve DOCX kabul edilir."
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as temp_file:
        temp_path = Path(temp_file.name)
        content = await file.read()
        temp_file.write(content)

    try:
        result = pipeline.process(temp_path)
        
        if result is None:
            raise HTTPException(
                status_code=500,
                detail="CV işlenirken hata oluştu. Lütfen tekrar deneyin."
            )
        
        return result

    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        if temp_path.exists():
            os.unlink(temp_path)

@app.post("/search-candidates", response_model=List[Dict])
async def search_candidates(query: QuerySpec):
    """
    İK sorgusuna göre en uygun adayları getir.
    """
    try:
        results = matcher.search(query, limit=10)
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)