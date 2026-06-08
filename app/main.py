from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import tempfile
import os
import hashlib
import mimetypes
import json
import uuid
from typing import List, Dict
from jose import JWTError, jwt
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.core.storage import upload_cv as r2_upload, download_cv as r2_download, delete_cv as r2_delete

from app.core.config import get_settings
from app.core.database import get_neo4j_driver, close_neo4j_driver
from app.core.postgres import get_db, init_db
from app.core.security import ALGORITHM, create_access_token, hash_password, verify_password
from app.extraction.pipeline import CVProcessingPipeline
from app.schemas.cv_extraction import CVExtraction
from app.models.postgres import (
    CandidateCVProfile,
    CandidateProfile,
    Conversation,
    HRProfile,
    JobApplication,
    JobPost,
    Message,
    Organization,
    SavedSearch,
    Shortlist,
    User,
)
from app.schemas.auth import (
    ApplicationCreateRequest,
    JobCreateRequest,
    LoginRequest,
    RegisterRequest,
    SavedSearchCreateRequest,
    ShortlistCreateRequest,
)
from app.schemas.query import QuerySpec
from app.query.matcher import CandidateMatcher
from app.query.job_matching import job_post_to_query_spec

settings = get_settings()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pipeline: CVProcessingPipeline | None = None
matcher: CandidateMatcher | None = None
STAGED_CVS: dict[str, dict] = {}
security = HTTPBearer()


def get_pipeline() -> CVProcessingPipeline:
    global pipeline
    if pipeline is None:
        pipeline = CVProcessingPipeline()
    return pipeline


def get_matcher() -> CandidateMatcher:
    global matcher
    if matcher is None:
        matcher = CandidateMatcher(get_neo4j_driver())
    return matcher

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 TalentForge başlatılıyor...")
    try:
        init_db()
        logger.info("PostgreSQL tablolari hazir")
    except Exception as e:
        logger.warning(f"PostgreSQL tablolari hazirlanamadi: {e}")
    try:
        get_neo4j_driver()
        logger.info("Neo4j baglantisi hazir")
    except Exception as e:
        logger.warning(f"Neo4j hazir degil; PostgreSQL/API akislari calismaya devam edecek: {e}")
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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request, exc):
    logger.error(f"Database error: {exc}")
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "PostgreSQL baglantisi zaman asimina dustu. Supabase direct connection "
                "yerine pooler connection string kullanman gerekebilir."
            )
        },
    )


def serialize_user(user: User) -> dict:
    profile = None
    if user.role == "hr" and user.hr_profile:
        profile = {
            "title": user.hr_profile.title,
            "department": user.hr_profile.department,
        }
    if user.role == "candidate" and user.candidate_profile:
        profile = {
            "school": user.candidate_profile.school,
            "profession": user.candidate_profile.profession,
            "experience_years": user.candidate_profile.experience_years,
            "location": user.candidate_profile.location,
            "neo4j_candidate_id": user.candidate_profile.neo4j_candidate_id,
        }

    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "status": user.status,
        "organization": {
            "id": user.organization.id,
            "name": user.organization.name,
            "domain": user.organization.domain,
        }
        if user.organization
        else None,
        "profile": profile,
    }


def serialize_job(job: JobPost, application: JobApplication | None = None) -> dict:
    application_count = len(job.applications) if job.applications is not None else 0
    return {
        "id": job.id,
        "title": job.title,
        "description": job.description,
        "location": job.location,
        "seniority": job.seniority,
        "min_experience_years": job.min_experience_years,
        "must_have_skills": job.must_have_skills,
        "nice_to_have_skills": job.nice_to_have_skills,
        "status": job.status,
        "organization": job.organization.name if job.organization else None,
        "application_count": application_count,
        "application": serialize_application(application) if application else None,
    }


def query_spec_from_job(job: JobPost) -> QuerySpec:
    return job_post_to_query_spec(job)


def candidate_neo4j_ids(candidate: CandidateProfile | None) -> list[str]:
    if not candidate:
        return []
    ids = [profile.neo4j_candidate_id for profile in candidate.cv_profiles if profile.neo4j_candidate_id]
    if candidate.neo4j_candidate_id:
        ids.append(candidate.neo4j_candidate_id)
    return list(dict.fromkeys(ids))


def resolve_candidate_neo4j_ids(candidate: CandidateProfile | None, db: Session) -> list[str]:
    """Return Neo4j candidate ids for a member, repairing old/missing PG links when possible."""
    ids = candidate_neo4j_ids(candidate)
    if ids or not candidate or not candidate.user:
        return ids

    email = (candidate.user.email or "").strip().lower()
    full_name = (candidate.user.full_name or "").strip().lower()
    if not email and not full_name:
        return []

    try:
        with get_neo4j_driver().session() as session:
            records = session.run(
                """
                MATCH (c:Candidate)
                WHERE ($email <> '' AND toLower(coalesce(c.email, '')) = $email)
                   OR ($name <> '' AND toLower(coalesce(c.name, '')) = $name)
                RETURN c.id AS id,
                       c.cv_original_name AS file_name,
                       c.summary AS summary
                LIMIT 8
                """,
                email=email,
                name=full_name,
            )
            resolved = [dict(record) for record in records if record["id"]]
    except Exception as e:
        logger.warning(f"Aday Neo4j id cozumleme basarisiz: {e}")
        return []

    for item in resolved:
        cv_id = item["id"]
        if cv_id not in ids:
            ids.append(cv_id)
        exists = (
            db.query(CandidateCVProfile)
            .filter(CandidateCVProfile.neo4j_candidate_id == cv_id)
            .first()
        )
        if not exists:
            db.add(
                CandidateCVProfile(
                    candidate_profile_id=candidate.id,
                    neo4j_candidate_id=cv_id,
                    file_name=item.get("file_name"),
                    title=candidate.profession,
                    summary=item.get("summary"),
                )
            )

    existing_owner = None
    if ids:
        existing_owner = (
            db.query(CandidateProfile)
            .filter(
                CandidateProfile.neo4j_candidate_id == ids[0],
                CandidateProfile.id != candidate.id,
            )
            .first()
        )
    if ids and not candidate.neo4j_candidate_id and not existing_owner:
        candidate.neo4j_candidate_id = ids[0]
        db.add(candidate)
    if ids:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    return list(dict.fromkeys(ids))


def serialize_application(application: JobApplication) -> dict:
    candidate = application.candidate
    candidate_neo4j_id = None
    if candidate:
        candidate_neo4j_id = candidate.neo4j_candidate_id or next(
            (profile.neo4j_candidate_id for profile in candidate.cv_profiles if profile.neo4j_candidate_id),
            None,
        )
    return {
        "id": application.id,
        "status": application.status,
        "match_score": application.match_score,
        "match_breakdown": application.match_breakdown,
        "cover_letter": application.cover_letter,
        "candidate": {
            "id": candidate.id,
            "neo4j_candidate_id": candidate_neo4j_id,
            "name": candidate.user.full_name if candidate and candidate.user else None,
            "email": candidate.user.email if candidate and candidate.user else None,
            "school": candidate.school if candidate else None,
            "profession": candidate.profession if candidate else None,
            "experience_years": candidate.experience_years if candidate else None,
            "location": candidate.location if candidate else None,
        }
        if candidate
        else None,
        "job": {
            "id": application.job_post.id,
            "title": application.job_post.title,
            "organization": application.job_post.organization.name
            if application.job_post.organization
            else None,
            "location": application.job_post.location,
            "description": application.job_post.description,
            "seniority": application.job_post.seniority,
            "min_experience_years": application.job_post.min_experience_years,
            "must_have_skills": application.job_post.must_have_skills,
            "nice_to_have_skills": application.job_post.nice_to_have_skills,
        },
    }


def match_application_to_job(
    application: JobApplication,
    db: Session,
    persist: bool = True,
) -> JobApplication:
    job = application.job_post
    candidate = application.candidate
    if not job or not candidate:
        return application
    if application.match_score is not None and application.match_breakdown:
        return application
    candidate_ids = set(resolve_candidate_neo4j_ids(candidate, db))
    if not candidate_ids:
        return application

    try:
        matches = get_matcher().search(query_spec_from_job(job), limit=100)
    except Exception as e:
        logger.warning(f"Basvuru matcher skoru hesaplanamadi ({application.id}): {e}")
        return application

    candidate_match = next(
        (match for match in matches if match.get("candidate_id") in candidate_ids),
        None,
    )
    if not candidate_match:
        return application

    application.match_score = candidate_match.get("total_score")
    application.match_breakdown = {
        "score_breakdown": candidate_match.get("score_breakdown") or {},
        "reasons": candidate_match.get("reasons") or [],
        "matched_candidate_id": candidate_match.get("candidate_id"),
    }
    if persist:
        db.add(application)
        db.commit()
        db.refresh(application)
    return application


def serialize_saved_search(saved_search: SavedSearch) -> dict:
    query_spec = saved_search.query_spec or {}
    return {
        "id": saved_search.id,
        "title": saved_search.name,
        "name": saved_search.name,
        "mode": query_spec.get("mode") or "categorical",
        "parsed": query_spec.get("parsed"),
        "payload": query_spec.get("payload"),
        "candidates": query_spec.get("candidates", []),
        "created_at": saved_search.created_at.isoformat() if saved_search.created_at else None,
    }


def serialize_shortlist(shortlist: Shortlist) -> dict:
    notes = shortlist.notes or ""
    name = None
    reason = notes
    if notes.startswith("{"):
        try:
            import json
            data = json.loads(notes)
            name = data.get("candidate_name")
            reason = data.get("reason") or ""
        except Exception:
            pass
    return {
        "id": shortlist.id,
        "candidate_id": shortlist.neo4j_candidate_id,
        "candidate_name": name,
        "name": name or shortlist.neo4j_candidate_id,
        "score": shortlist.score,
        "reasons": [reason] if reason else [],
        "stage": shortlist.stage,
        "created_at": shortlist.created_at.isoformat() if shortlist.created_at else None,
    }


def candidate_membership(db: Session, neo4j_candidate_id: str | None) -> dict:
    if not neo4j_candidate_id:
        return {
            "talentforge_member": False,
            "candidate_user_id": None,
            "member_label": "TalentForge uyesi degil",
        }

    cv_profile = (
        db.query(CandidateCVProfile)
        .filter(CandidateCVProfile.neo4j_candidate_id == neo4j_candidate_id)
        .first()
    )
    profile = cv_profile.candidate_profile if cv_profile else None
    if profile is None:
        profile = (
            db.query(CandidateProfile)
            .filter(CandidateProfile.neo4j_candidate_id == neo4j_candidate_id)
            .first()
        )

    if not profile:
        return {
            "talentforge_member": False,
            "candidate_user_id": None,
            "member_label": "TalentForge uyesi degil",
        }

    return {
        "talentforge_member": True,
        "candidate_user_id": profile.user_id,
        "candidate_profile_id": profile.id,
        "member_label": "TalentForge uyesi",
    }


def enrich_candidate_membership(results: list[dict], db: Session) -> list[dict]:
    enriched = []
    for result in results:
        candidate_id = result.get("candidate_id") or result.get("id")
        enriched.append({**result, **candidate_membership(db, candidate_id)})
    return enriched


def conversation_unread_count(conversation: Conversation, current_user: User, db: Session) -> int:
    return (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.sender_user_id != current_user.id,
            Message.read_at.is_(None),
        )
        .count()
    )


def serialize_message(message: Message) -> dict:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_user_id": message.sender_user_id,
        "body": message.body,
        "read_at": message.read_at.isoformat() if message.read_at else None,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def serialize_conversation(conversation: Conversation, current_user: User, db: Session) -> dict:
    other_user_id = (
        conversation.candidate_user_id if current_user.id == conversation.hr_user_id else conversation.hr_user_id
    )
    other_user = db.get(User, other_user_id)
    last_message = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            ~Message.body.startswith("İlan bağlamı:"),
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    return {
        "id": conversation.id,
        "hr_user_id": conversation.hr_user_id,
        "candidate_user_id": conversation.candidate_user_id,
        "candidate_neo4j_id": conversation.candidate_neo4j_id,
        "other_user": {
            "id": other_user.id,
            "name": other_user.full_name,
            "email": other_user.email,
            "role": other_user.role,
        } if other_user else None,
        "last_message": serialize_message(last_message) if last_message else None,
        "unread_count": conversation_unread_count(conversation, current_user, db),
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
    }


def _email_domain(email: str) -> str:
    return email.split("@", 1)[1].lower()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Oturum gecersiz") from exc

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanici bulunamadi")
    return user


def require_role(user: User, role: str) -> None:
    if user.role != role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu islem icin yetkin yok")


def _compute_file_hash(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _find_local_cv_by_hash(file_hash: str | None) -> Path | None:
    if not file_hash:
        return None
    cv_dir = Path("data/cvs")
    if not cv_dir.exists():
        return None
    for file_path in sorted([*cv_dir.glob("*.pdf"), *cv_dir.glob("*.docx")]):
        try:
            if _compute_file_hash(file_path) == file_hash:
                return file_path
        except OSError:
            continue
    return None

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


@app.post("/auth/register")
async def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = str(payload.company_email or payload.email).lower() if payload.role == "hr" else str(payload.email).lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="Bu e-posta ile kayitli kullanici var")

    organization = None
    if payload.role == "hr":
        company_email = str(payload.company_email or payload.email).lower()
        domain = _email_domain(company_email)
        organization = db.query(Organization).filter(Organization.domain == domain).first()
        if not organization:
            organization = Organization(
                name=payload.company_name or domain,
                domain=domain,
            )
            db.add(organization)
            db.flush()

    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        organization_id=organization.id if organization else None,
    )
    db.add(user)
    db.flush()

    if payload.role == "hr":
        db.add(HRProfile(user_id=user.id, title=payload.position))
    else:
        db.add(
            CandidateProfile(
                user_id=user.id,
                school=payload.school,
                profession=payload.profession,
                experience_years=payload.experience_years,
                location=payload.location,
            )
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Kayit olusturulamadi") from exc

    db.refresh(user)
    token = create_access_token(user.id, {"role": user.role})
    return {"access_token": token, "token_type": "bearer", "user": serialize_user(user)}


@app.post("/auth/login")
async def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = str(payload.email).lower()
    user = db.query(User).filter(func.lower(User.email) == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-posta veya sifre hatali")

    token = create_access_token(user.id, {"role": user.role})
    return {"access_token": token, "token_type": "bearer", "user": serialize_user(user)}


@app.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return serialize_user(current_user)


@app.get("/dashboard")
async def dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "hr":
        org_id = current_user.organization_id
        active_jobs = db.query(JobPost).filter(JobPost.organization_id == org_id).count() if org_id else 0
        applications = (
            db.query(JobApplication)
            .join(JobPost)
            .filter(JobPost.organization_id == org_id)
            .count()
            if org_id
            else 0
        )
        shortlist_count = (
            db.query(Shortlist).filter(Shortlist.organization_id == org_id).count()
            if org_id
            else 0
        )
        saved_search_count = (
            db.query(SavedSearch).filter(SavedSearch.organization_id == org_id).count()
            if org_id
            else 0
        )
        return {
            "user": serialize_user(current_user),
            "saved_searches": saved_search_count,
            "metrics": {
                "active_jobs": active_jobs,
                "applications": applications,
                "shortlist": shortlist_count,
                "average_score": 0,
            },
        }

    candidate = current_user.candidate_profile
    applications = (
        db.query(JobApplication).filter(JobApplication.candidate_profile_id == candidate.id).count()
        if candidate
        else 0
    )
    jobs = db.query(JobPost).filter(JobPost.status == "published").count()
    return {
        "user": serialize_user(current_user),
        "metrics": {
            "profile_completion": 70,
            "matching_jobs": jobs,
            "applications": applications,
            "feedback": 0,
        },
    }


@app.get("/jobs")
async def list_jobs(
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "hr":
        jobs = (
            db.query(JobPost)
            .filter(JobPost.organization_id == current_user.organization_id)
            .order_by(JobPost.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {"jobs": [serialize_job(job) for job in jobs]}

    candidate = current_user.candidate_profile
    applied_by_job_id = {}
    if candidate:
        applications = (
            db.query(JobApplication)
            .filter(JobApplication.candidate_profile_id == candidate.id)
            .all()
        )
        applied_by_job_id = {application.job_post_id: application for application in applications}

    jobs = (
        db.query(JobPost)
        .filter(JobPost.status == "published")
        .order_by(JobPost.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"jobs": [serialize_job(job, applied_by_job_id.get(job.id)) for job in jobs]}


@app.get("/candidate/recommendations")
async def candidate_recommendations(
    limit: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "candidate")
    candidate = current_user.candidate_profile
    candidate_ids = set(resolve_candidate_neo4j_ids(candidate, db))
    if not candidate or not candidate_ids:
        return {"recommendations": []}

    applications = (
        db.query(JobApplication)
        .filter(JobApplication.candidate_profile_id == candidate.id)
        .all()
    )
    applied_by_job_id = {application.job_post_id: application for application in applications}

    jobs = (
        db.query(JobPost)
        .filter(JobPost.status == "published")
        .order_by(JobPost.created_at.desc())
        .all()
    )
    recommendations = []
    matcher = get_matcher()
    for job in jobs:
        query_spec = query_spec_from_job(job)
        try:
            matches = matcher.search(query_spec, limit=100)
        except Exception as e:
            logger.warning(f"Aday ilan onerisi hesaplanamadi ({job.id}): {e}")
            matches = []
        candidate_match = next(
            (match for match in matches if match.get("candidate_id") in candidate_ids),
            None,
        )
        if not candidate_match:
            continue
        recommendations.append({
            "job": serialize_job(job, applied_by_job_id.get(job.id)),
            "match_score": candidate_match.get("total_score"),
            "score_breakdown": candidate_match.get("score_breakdown") or {},
            "reasons": candidate_match.get("reasons") or [],
            "matched_candidate_id": candidate_match.get("candidate_id"),
        })

    recommendations.sort(key=lambda item: item.get("match_score") or 0, reverse=True)
    return {"recommendations": recommendations[:limit]}


@app.post("/jobs")
async def create_job(
    payload: JobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="Ilan olusturmak icin sirket baglantisi gerekli")

    job = JobPost(
        organization_id=current_user.organization_id,
        created_by_user_id=current_user.id,
        title=payload.title,
        description=payload.description,
        location=payload.location,
        seniority=payload.seniority,
        min_experience_years=payload.min_experience_years,
        must_have_skills=payload.must_have_skills,
        nice_to_have_skills=payload.nice_to_have_skills,
        status=payload.status,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job": serialize_job(job)}


@app.get("/jobs/{job_id}")
async def job_detail(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.get(JobPost, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")
    if current_user.role == "hr" and job.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")
    if current_user.role == "candidate" and job.status != "published":
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")
    return {"job": serialize_job(job)}


@app.delete("/jobs/{job_id}")
async def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    job = db.get(JobPost, job_id)
    if not job or job.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")
    db.delete(job)
    db.commit()
    return {"deleted": True, "job_id": job_id}


@app.get("/jobs/{job_id}/applications")
async def job_applications(
    job_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    job = db.get(JobPost, job_id)
    if not job or job.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")
    applications = (
        db.query(JobApplication)
        .filter(JobApplication.job_post_id == job.id)
        .order_by(JobApplication.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    applications = [match_application_to_job(application, db) for application in applications]
    return {"applications": [serialize_application(application) for application in applications]}


@app.post("/jobs/{job_id}/apply")
async def apply_to_job(
    job_id: str,
    payload: ApplicationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "candidate")
    candidate = current_user.candidate_profile
    if not candidate:
        raise HTTPException(status_code=400, detail="Aday profili bulunamadi")

    job = db.get(JobPost, job_id)
    if not job or job.status != "published":
        raise HTTPException(status_code=404, detail="Ilan bulunamadi")

    existing = (
        db.query(JobApplication)
        .filter(
            JobApplication.job_post_id == job.id,
            JobApplication.candidate_profile_id == candidate.id,
        )
        .first()
    )
    if existing:
        existing = match_application_to_job(existing, db)
        return {"application": serialize_application(existing)}

    application = JobApplication(
        job_post_id=job.id,
        candidate_profile_id=candidate.id,
        status="submitted",
        match_score=None,
        match_breakdown={
            "mode": "loose_job_match",
            "note": "Ilan-basvuru uyumluluk skoru matcher servisi baglaninca hesaplanacak.",
        },
        cover_letter=payload.cover_letter,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    application = match_application_to_job(application, db)
    return {"application": serialize_application(application)}


@app.get("/applications/me")
async def my_applications(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "candidate")
    candidate = current_user.candidate_profile
    if not candidate:
        return {"applications": []}
    applications = (
        db.query(JobApplication)
        .filter(JobApplication.candidate_profile_id == candidate.id)
        .order_by(JobApplication.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    applications = [match_application_to_job(application, db) for application in applications]
    return {"applications": [serialize_application(application) for application in applications]}


@app.get("/saved-searches")
async def list_saved_searches(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    if not current_user.organization_id:
        return {"saved_searches": []}
    searches = (
        db.query(SavedSearch)
        .filter(SavedSearch.organization_id == current_user.organization_id)
        .order_by(SavedSearch.created_at.desc())
        .all()
    )
    return {"saved_searches": [serialize_saved_search(search) for search in searches]}


@app.post("/saved-searches")
async def create_saved_search(
    payload: SavedSearchCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="Kayıtlı arama için şirket bağlantısı gerekli")
    saved_search = SavedSearch(
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        name=payload.name,
        query_spec=payload.query_spec,
    )
    db.add(saved_search)
    db.commit()
    db.refresh(saved_search)
    return {"saved_search": serialize_saved_search(saved_search)}


@app.delete("/saved-searches/{saved_search_id}")
async def delete_saved_search(
    saved_search_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    saved_search = db.get(SavedSearch, saved_search_id)
    if not saved_search or saved_search.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Kayıtlı arama bulunamadı")
    db.delete(saved_search)
    db.commit()
    return {"deleted": True}


@app.get("/shortlists")
async def list_shortlists(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    if not current_user.organization_id:
        return {"shortlists": []}
    shortlists = (
        db.query(Shortlist)
        .filter(Shortlist.organization_id == current_user.organization_id)
        .order_by(Shortlist.created_at.desc())
        .all()
    )
    return {"shortlists": [serialize_shortlist(item) for item in shortlists]}


@app.post("/shortlists")
async def create_shortlist(
    payload: ShortlistCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="Aday kaydetmek için şirket bağlantısı gerekli")
    existing = (
        db.query(Shortlist)
        .filter(
            Shortlist.organization_id == current_user.organization_id,
            Shortlist.neo4j_candidate_id == payload.neo4j_candidate_id,
        )
        .first()
    )
    notes = json.dumps(
        {
            "candidate_name": payload.candidate_name,
            "reason": payload.notes,
        },
        ensure_ascii=False,
    )
    if existing:
        existing.score = payload.score
        existing.notes = notes
        existing.stage = "saved"
        db.commit()
        db.refresh(existing)
        return {"shortlist": serialize_shortlist(existing)}

    shortlist = Shortlist(
        organization_id=current_user.organization_id,
        neo4j_candidate_id=payload.neo4j_candidate_id,
        stage="saved",
        score=payload.score,
        notes=notes,
    )
    db.add(shortlist)
    db.commit()
    db.refresh(shortlist)
    return {"shortlist": serialize_shortlist(shortlist)}


@app.delete("/shortlists/{shortlist_id}")
async def delete_shortlist(
    shortlist_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    shortlist = db.get(Shortlist, shortlist_id)
    if not shortlist or shortlist.organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Kaydedilen aday bulunamadı")
    db.delete(shortlist)
    db.commit()
    return {"deleted": True}

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
        result = get_pipeline().process(temp_path)

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


@app.post("/preview-cv")
async def preview_cv(file: UploadFile = File(...)):
    """CV'yi işler ama Neo4j/R2 kaydı yapmadan aday onboarding önizlemesi döner."""
    allowed_extensions = {".pdf", ".docx"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(status_code=400, detail="Desteklenmeyen dosya türü. Sadece PDF ve DOCX kabul edilir.")

    staged_dir = Path(tempfile.gettempdir()) / "talentforge_staged_cvs"
    staged_dir.mkdir(parents=True, exist_ok=True)
    token = str(uuid.uuid4())
    staged_path = staged_dir / f"{token}{file_ext}"
    staged_path.write_bytes(await file.read())

    try:
        result = get_pipeline().extract_only(staged_path)
        if result is None:
            raise HTTPException(status_code=500, detail="CV işlenirken hata oluştu. Lütfen tekrar deneyin.")
        result["stage_token"] = token
        result["original_name"] = file.filename
        STAGED_CVS[token] = {
            "path": str(staged_path),
            "original_name": file.filename,
            "extraction": result,
            "file_hash": result.get("file_hash"),
        }
        return result
    except HTTPException:
        if staged_path.exists():
            os.unlink(staged_path)
        raise
    except Exception as e:
        if staged_path.exists():
            os.unlink(staged_path)
        logger.error(f"Preview upload error: {e}")
        raise HTTPException(status_code=500, detail="CV işlenirken hata oluştu. Lütfen tekrar deneyin.")


@app.post("/commit-cvs")
async def commit_cvs(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Önizlenen CV'leri Devam et sonrasında Neo4j/R2'ye kaydeder."""
    tokens = payload.get("tokens") or []
    if not isinstance(tokens, list) or not tokens:
        raise HTTPException(status_code=400, detail="Kaydedilecek CV bulunamadı.")

    committed = []
    for token in tokens:
        staged = STAGED_CVS.get(str(token))
        if not staged:
            continue
        staged_path = Path(staged["path"])
        extraction_data = dict(staged["extraction"])
        for key in ("stage_token", "original_name", "preview_only", "file_hash"):
            extraction_data.pop(key, None)
        extraction = CVExtraction.model_validate(extraction_data)
        cv_id = get_pipeline().commit_extraction(extraction, file_hash=staged.get("file_hash"))
        if cv_id:
            object_name = None
            try:
                object_name = r2_upload(cv_id, staged_path, staged["original_name"])
                with get_neo4j_driver().session() as session:
                    session.run("""
                        MATCH (c:Candidate {id: $id})
                        SET c.cv_object_name = $object_name,
                            c.cv_original_name = $original_name
                    """, id=cv_id, object_name=object_name, original_name=staged["original_name"])
            except Exception as e:
                logger.warning(f"R2 yükleme başarısız (commit tamamlandı): {e}")
            committed.append({
                "stage_token": token,
                "cv_id": cv_id,
                "candidate_name": extraction.candidate_name,
                "original_name": staged["original_name"],
                "cv_object_name": object_name,
                "cv_available": bool(object_name),
            })
            if current_user.role == "candidate" and current_user.candidate_profile:
                cv_profile = (
                    db.query(CandidateCVProfile)
                    .filter(CandidateCVProfile.neo4j_candidate_id == cv_id)
                    .first()
                )
                if not cv_profile:
                    cv_profile = CandidateCVProfile(
                        candidate_profile_id=current_user.candidate_profile.id,
                        neo4j_candidate_id=cv_id,
                        file_name=staged["original_name"],
                        title=extraction.experiences[0].role_title if extraction.experiences else None,
                        summary=extraction.summary,
                    )
                    db.add(cv_profile)
                if not current_user.candidate_profile.neo4j_candidate_id:
                    current_user.candidate_profile.neo4j_candidate_id = cv_id
                    db.add(current_user.candidate_profile)
                db.commit()
        if staged_path.exists():
            os.unlink(staged_path)
        STAGED_CVS.pop(str(token), None)

    return {"committed": committed}

@app.get("/download-cv/{candidate_id}")
async def download_cv(candidate_id: str):
    """Aday CV dosyasını R2'den indirir"""
    with get_neo4j_driver().session() as session:
        record = session.run("""
            MATCH (c:Candidate {id: $id})
            RETURN c.cv_object_name AS object_name,
                   c.cv_original_name AS original_name,
                   c.file_hash AS file_hash
        """, id=candidate_id).single()

    if not record:
        raise HTTPException(status_code=404, detail="CV dosyası bulunamadı")

    if not record["object_name"]:
        local_cv = _find_local_cv_by_hash(record["file_hash"])
        if not local_cv:
            raise HTTPException(status_code=404, detail="CV dosyası bulunamadı")
        return Response(
            content=local_cv.read_bytes(),
            media_type=mimetypes.guess_type(local_cv.name)[0] or "application/octet-stream",
            headers={
                "Content-Disposition":
                    f"attachment; filename=\"{record['original_name'] or local_cv.name}\""
            },
        )

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


@app.delete("/candidate-cvs/{candidate_id}")
async def delete_candidate_cv(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Adayın seçtiği CV profilini Neo4j/R2/PostgreSQL izleriyle siler."""
    object_name = None
    with get_neo4j_driver().session() as session:
        record = session.run("""
            MATCH (c:Candidate {id: $id})
            RETURN c.cv_object_name AS object_name
        """, id=candidate_id).single()
        if not record:
            raise HTTPException(status_code=404, detail="CV profili bulunamadı")
        object_name = record["object_name"]

        session.run("""
            MATCH (c:Candidate {id: $id})
            OPTIONAL MATCH (c)-[:HAS_EXPERIENCE]->(e:Experience)
            OPTIONAL MATCH (c)-[:HAS_EDUCATION]->(ed:Education)
            OPTIONAL MATCH (c)-[:HAS_PROJECT]->(p:Project)
            WITH c, collect(DISTINCT e) + collect(DISTINCT ed) + collect(DISTINCT p) AS owned_nodes
            FOREACH (n IN owned_nodes | DETACH DELETE n)
            DETACH DELETE c
        """, id=candidate_id)

    if object_name:
        try:
            r2_delete(object_name)
        except Exception as e:
            logger.warning(f"R2 silme başarısız: {e}")

    cv_profile = (
        db.query(CandidateCVProfile)
        .filter(CandidateCVProfile.neo4j_candidate_id == candidate_id)
        .first()
    )
    profile = cv_profile.candidate_profile if cv_profile else (
        db.query(CandidateProfile)
        .filter(CandidateProfile.neo4j_candidate_id == candidate_id)
        .first()
    )
    if profile:
        db.query(JobApplication).filter(JobApplication.candidate_profile_id == profile.id).delete()
        if profile.neo4j_candidate_id == candidate_id:
            profile.neo4j_candidate_id = None
        db.add(profile)
        if cv_profile:
            db.delete(cv_profile)
        db.commit()

    return {"deleted": True, "candidate_id": candidate_id}


@app.get("/candidates/{candidate_id}")
async def candidate_detail(candidate_id: str, db: Session = Depends(get_db)):
    """Aday detayını popup/detay ekranı için döner"""
    with get_neo4j_driver().session() as session:
        record = session.run("""
            MATCH (c:Candidate {id: $id})

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
            }) AS raw_experiences
            WITH c, skills, [x IN raw_experiences WHERE x.role IS NOT NULL OR x.company IS NOT NULL] AS experiences

            OPTIONAL MATCH (c)-[:HAS_EDUCATION]->(ed:Education)-[:AT_INSTITUTION]->(i:Institution)
            WITH c, skills, experiences, collect({
                degree: ed.degree,
                field: ed.field,
                institution: i.name,
                gpa: ed.gpa
            }) AS raw_educations
            WITH c, skills, experiences, [x IN raw_educations WHERE x.degree IS NOT NULL OR x.institution IS NOT NULL] AS educations

            OPTIONAL MATCH (c)-[:SPEAKS]->(l:Language)
            WITH c, skills, experiences, educations, [x IN collect(l.name) WHERE x IS NOT NULL] AS languages

            OPTIONAL MATCH (c)-[:HAS_CERTIFICATION]->(ct:Certification)
            WITH c, skills, experiences, educations, languages, [x IN collect(ct.name) WHERE x IS NOT NULL] AS certifications

            OPTIONAL MATCH (c)-[:HAS_PROJECT]->(p:Project)
            WITH c, skills, experiences, educations, languages, certifications, collect({
                name: p.name,
                description: p.description,
                role: p.role,
                start_date: p.start_date,
                end_date: p.end_date,
                url: p.url,
                evidence_text: p.evidence_text,
                confidence: p.confidence
            }) AS raw_projects
            WITH c, skills, experiences, educations, languages, certifications,
                 [x IN raw_projects WHERE x.name IS NOT NULL] AS projects

            RETURN
                c.id AS id,
                c.name AS name,
                c.email AS email,
                c.phone AS phone,
                c.location AS location,
                c.summary AS summary,
                c.file_hash AS file_hash,
                c.cv_object_name AS cv_object_name,
                c.cv_original_name AS cv_original_name,
                skills,
                experiences,
                educations,
                projects,
                languages,
                certifications
        """, id=candidate_id).single()

    if not record:
        raise HTTPException(status_code=404, detail="Aday bulunamadi")

    data = record.data()
    data["cv_available"] = bool(data.get("cv_object_name") or _find_local_cv_by_hash(data.get("file_hash")))
    if data.get("file_hash"):
        data["file_hash_short"] = f"{data['file_hash'][:10]}..."
    data.update(candidate_membership(db, candidate_id))
    return data


@app.post("/search-candidates", response_model=List[Dict])
async def search_candidates(query: QuerySpec, db: Session = Depends(get_db)):
    """İK sorgusuna göre en uygun adayları getir"""
    try:
        results = get_matcher().search(query, limit=10)
        return enrich_candidate_membership(results, db)
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
    

_nl_parser = None

def get_nl_parser():
    global _nl_parser
    if _nl_parser is None:
        from app.query.nl_parser import NLQueryParser
        _nl_parser = NLQueryParser()
    return _nl_parser

@app.post("/nl-search")
async def nl_search(body: dict, db: Session = Depends(get_db)):
    """
    Doğal dil sorgusu → QuerySpec → Aday arama
    Body: {"query": "5 yıl Python deneyimi olan senior backend developer"}
    """
    nl_text = body.get("query", "").strip()
    if not nl_text:
        raise HTTPException(status_code=400, detail="query alanı boş olamaz")

    try:
        query_spec = get_nl_parser().parse(nl_text)
        results = enrich_candidate_membership(get_matcher().search(query_spec, limit=10), db)
        return {
            "parsed_query": query_spec.model_dump(),
            "results": results,
        }
    except Exception as e:
        logger.error(f"NL search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/messages")
async def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "hr":
        query = db.query(Conversation).filter(Conversation.hr_user_id == current_user.id)
    else:
        query = db.query(Conversation).filter(Conversation.candidate_user_id == current_user.id)
    conversations = query.order_by(
        Conversation.last_message_at.desc().nullslast(),
        Conversation.created_at.desc(),
    ).all()
    serialized = [serialize_conversation(conversation, current_user, db) for conversation in conversations]
    return {
        "conversations": serialized,
        "unread_count": sum(item["unread_count"] for item in serialized),
    }


@app.post("/messages/conversations")
async def create_or_get_conversation(
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_role(current_user, "hr")
    candidate_user_id = payload.get("candidate_user_id")
    if not candidate_user_id:
        raise HTTPException(status_code=400, detail="Aday kullanici bilgisi bulunamadi")
    candidate_user = db.get(User, candidate_user_id)
    if not candidate_user or candidate_user.role != "candidate":
        raise HTTPException(status_code=404, detail="Aday kullanici bulunamadi")

    created_conversation = False
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.hr_user_id == current_user.id,
            Conversation.candidate_user_id == candidate_user.id,
        )
        .first()
    )
    if not conversation:
        conversation = Conversation(
            hr_user_id=current_user.id,
            candidate_user_id=candidate_user.id,
            candidate_neo4j_id=payload.get("candidate_neo4j_id"),
        )
        db.add(conversation)
        db.flush()
        created_conversation = True

    initial_message = (payload.get("initial_message") or "").strip()
    if initial_message:
        existing_context = None
        if not created_conversation:
            existing_context = (
                db.query(Message)
                .filter(
                    Message.conversation_id == conversation.id,
                    Message.body == initial_message,
                )
                .first()
            )
        if not existing_context:
            message = Message(
                conversation_id=conversation.id,
                sender_user_id=current_user.id,
                body=initial_message,
            )
            conversation.last_message_at = func.now()
            db.add(message)
            db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return {"conversation": serialize_conversation(conversation, current_user, db)}


@app.get("/messages/{conversation_id}")
async def get_messages(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or current_user.id not in {conversation.hr_user_id, conversation.candidate_user_id}:
        raise HTTPException(status_code=404, detail="Konusma bulunamadi")
    db.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.sender_user_id != current_user.id,
        Message.read_at.is_(None),
    ).update({"read_at": func.now()}, synchronize_session=False)
    db.commit()
    messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            ~Message.body.startswith("İlan bağlamı:"),
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    return {
        "conversation": serialize_conversation(conversation, current_user, db),
        "messages": [serialize_message(message) for message in messages],
    }


@app.post("/messages/{conversation_id}")
async def send_message(
    conversation_id: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation = db.get(Conversation, conversation_id)
    if not conversation or current_user.id not in {conversation.hr_user_id, conversation.candidate_user_id}:
        raise HTTPException(status_code=404, detail="Konusma bulunamadi")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Mesaj bos olamaz")
    message = Message(
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        body=body,
    )
    conversation.last_message_at = func.now()
    db.add(message)
    db.add(conversation)
    db.commit()
    db.refresh(message)
    return {"message": serialize_message(message)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
