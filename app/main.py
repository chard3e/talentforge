from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import Response
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import tempfile
import os
from typing import List, Dict
from app.core.storage import upload_cv as r2_upload, download_cv as r2_download

from app.core.config import get_settings
from app.core.database import get_neo4j_driver, close_neo4j_driver
from app.extraction.pipeline import CVProcessingPipeline
from app.schemas.query import QuerySpec
from app.query.matcher import CandidateMatcher

settings = get_settings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pipeline = CVProcessingPipeline()
matcher = CandidateMatcher(get_neo4j_driver())

@asynccontextmanager
async def lifespan(app: FastAPI):
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

@app.post("/upload-cv")
async def upload_cv(file: UploadFile = File(...)):
    """
    CV dosyası yükle → parse → LLM extraction → RAG doğrulama
    → KG yaz → Entity Resolution → Embedding → R2 yükle
    """
    allowed_extensions = {".pdf", ".docx"}
    file_ext = Path(file.filename).suffix.lower()

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="Desteklenmeyen dosya türü. Sadece PDF ve DOCX kabul edilir."
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

        # R2'ye yükle
        cv_id = result.get("cv_id")
        if cv_id:
            try:
                object_name = r2_upload(cv_id, temp_path, file.filename)
                with get_neo4j_driver().session() as session:
                    session.run("""
                        MATCH (c:Candidate {id: $id})
                        SET c.cv_object_name = $object_name,
                            c.cv_original_name = $original_name
                    """, id=cv_id, object_name=object_name,
                         original_name=file.filename)
            except Exception as e:
                logger.warning(f"⚠️ R2 yükleme başarısız (pipeline tamamlandı): {e}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail="CV işlenirken hata oluştu. Lütfen tekrar deneyin.")

    finally:
        if temp_path.exists():
            os.unlink(temp_path)

@app.get("/download-cv/{candidate_id}")
async def download_cv(candidate_id: str):
    """Aday CV dosyasını R2'den indirir"""
    with get_neo4j_driver().session() as session:
        record = session.run("""
            MATCH (c:Candidate {id: $id})
            RETURN c.cv_object_name AS object_name,
                   c.cv_original_name AS original_name
        """, id=candidate_id).single()

    if not record or not record["object_name"]:
        raise HTTPException(status_code=404, detail="CV dosyası bulunamadı")

    try:
        file_bytes = r2_download(record["object_name"])
    except Exception as e:
        logger.error(f"R2 download error: {e}")
        raise HTTPException(status_code=404, detail="CV dosyasına erişilemiyor")

    return Response(
        content=file_bytes,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition":
                f"attachment; filename=\"{record['original_name'] or 'cv.docx'}\""
        },
    )

@app.post("/search-candidates", response_model=List[Dict])
async def search_candidates(query: QuerySpec):
    """İK sorgusuna göre en uygun adayları getir"""
    try:
        results = matcher.search(query, limit=10)
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/resolve-entities")
async def resolve_entities():
    """KG'deki duplicate düğümleri birleştirir (Entity Resolution)"""
    try:
        from app.extraction.entity_resolver import EntityResolver
        resolver = EntityResolver(get_neo4j_driver())
        stats = resolver.resolve_all()
        return {"status": "success", "merged": stats}
    except Exception as e:
        logger.error(f"ER error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed-all")
async def embed_all():
    """Tüm adaylar için embedding üret"""
    try:
        from app.extraction.embedding_service import EmbeddingService
        svc = EmbeddingService(get_neo4j_driver())
        svc.ensure_vector_index()
        count = svc.embed_all_candidates()
        return {"status": "success", "embedded": count}
    except Exception as e:
        logger.error(f"Embed error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)