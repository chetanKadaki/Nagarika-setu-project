from collections.abc import AsyncGenerator, Callable
import hashlib
import io
import logging
import math
import re
import secrets
import smtplib
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pypdf import PdfReader
from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, SessionLocal, engine, ensure_user_timestamp_columns, get_db
from app.models import (
    Complaint,
    ComplaintAssignment,
    ComplaintAssessment,
    ComplaintAttachment,
    ComplaintFeedback,
    ComplaintLocationEvidence,
    EngineerProfile,
    EngineerRegistrationReview,
    AuthSession,
    CitizenProfile,
    EmailVerificationToken,
    LiveWorkLocation,
    LoginAttempt,
    LoginAuditLog,
    OfficerProfile,
    PasswordResetToken,
    SchemeTask,
    SchemeTaskUpdate,
    User,
    UserAuthentication,
    UserContactProfile,
    UserInvitation,
    VerificationReview,
    WorkSubmission,
    WorkSubmissionLocationEvidence,
    WorkUpdate,
)
from app.rag import ask_assistant, ingest_approved_document
from app.schemas import (
    AssignmentRequest,
    AssignedEngineerResponse,
    ChatRequest,
    ComplaintAssessmentResponse,
    ComplaintAttachmentResponse,
    ComplaintCreate,
    ComplaintFeedbackCreate,
    ComplaintFeedbackResponse,
    ComplaintResponse,
    ComplaintTriageDecisionRequest,
    CitizenRegistrationRequest,
    EmailAddressRequest,
    InvitationAcceptRequest,
    EngineerRegistrationDecisionRequest,
    EngineerRegistrationRequest,
    EngineerRegistrationUpdateRequest,
    GoogleLoginRequest,
    LoginRequest,
    LiveWorkLocationRequest,
    OfficialInvitationRequest,
    OneTimeTokenRequest,
    PasswordResetRequest,
    ProfileUpdateRequest,
    AccountStatusRequest,
    PublicDashboardResponse,
    SchemeTaskCompletionRequest,
    SchemeTaskCreate,
    SchemeTaskProgressRequest,
    VerificationDecisionRequest,
    WorkUpdateRequest,
    WorkSubmissionRequest,
    normalize_email_address,
)
from app.security import (
    create_session_access_token,
    get_current_user,
    hash_password,
    require_role,
    revoke_session_access_token,
    verify_google_id_token,
    verify_password,
    verify_unknown_user_password,
)
from app.auth_service import (
    EMAIL_VERIFICATION_TTL,
    INVITATION_TTL,
    PASSWORD_RESET_TTL,
    create_one_time_token,
    ensure_email_configured,
    send_invitation_email,
    send_password_reset_email,
    send_verification_email,
    token_digest,
)
from app.seed import seed_demo_data

logger = logging.getLogger(__name__)
MAX_SCHEME_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_COMPLAINT_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_COMPLAINT_ATTACHMENT_TOTAL_BYTES = 60 * 1024 * 1024
MAX_COMPLAINT_ATTACHMENTS = 5
MAX_SCHEME_PAGES = 250
MAX_EXTRACTED_CHARACTERS = 2_000_000
WORK_LOCATION_DISTANCE_REVIEW_THRESHOLD_METERS = 500
CATEGORY_DEPARTMENTS = {
    "Roads & pavements": "Public Works",
    "Water & drainage": "Water Supply",
    "Street lighting": "Electrical",
    "Waste management": "Solid Waste",
    "Pollution & environment": "Environment",
}
CATEGORY_SKILLS = {
    "Roads & pavements": ("road", "pavement", "civil", "infrastructure"),
    "Water & drainage": ("water", "drain", "plumb", "sanitation"),
    "Street lighting": ("electric", "lighting", "power"),
    "Waste management": ("waste", "sanitation", "solid"),
    "Pollution & environment": ("environment", "pollution", "air quality", "waste"),
}

TRIAGE_CATEGORY_TERMS = {
    "Roads & pavements": ("pothole", "road", "pavement", "sidewalk", "footpath", "crack"),
    "Water & drainage": ("water", "leak", "pipe", "drain", "sewer", "flood"),
    "Street lighting": ("streetlight", "street light", "lamp", "electric pole", "lighting"),
    "Waste management": ("garbage", "waste", "trash", "litter", "dump", "rubbish"),
    "Pollution & environment": ("pollution", "smoke", "odor", "odour", "air quality", "chemical", "noise"),
}
SEVERITY_TERMS = {
    "Critical": ("fire", "collapse", "collapsed", "live wire", "electric shock", "injured", "life-threatening"),
    "High": ("flood", "burst", "overflow", "unsafe", "severe", "major", "blocked", "large pothole"),
    "Low": ("minor", "small", "slight", "cosmetic"),
}
ALLOWED_COMPLAINT_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/mp4",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
}


def engineer_matches_complaint(profile: EngineerProfile, complaint: Complaint) -> bool:
    expected_department = CATEGORY_DEPARTMENTS.get(complaint.category)
    required_skills = CATEGORY_SKILLS.get(complaint.category, ())
    return (
        expected_department is not None
        and profile.department.strip().casefold() == expected_department.casefold()
        and any(
            keyword in skill.casefold()
            for skill in profile.skills
            for keyword in required_skills
        )
    )


def engineer_matches_scheme_task(
    profile: EngineerProfile,
    department: str,
    required_skills: list[str],
) -> bool:
    if profile.department.strip().casefold() != department.strip().casefold():
        return False
    for registered_skill in profile.skills:
        registered_normalized = registered_skill.strip().casefold()
        registered_words = {
            word for word in re.findall(r"[a-z0-9]+", registered_normalized) if len(word) >= 3
        }
        for required_skill in required_skills:
            required_normalized = required_skill.strip().casefold()
            if (
                required_normalized in registered_normalized
                or registered_normalized in required_normalized
            ):
                return True
            required_words = {
                word for word in re.findall(r"[a-z0-9]+", required_normalized) if len(word) >= 3
            }
            if registered_words.intersection(required_words):
                return True
    return False


def distance_between_points_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    earth_radius_meters = 6_371_000
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * earth_radius_meters * math.asin(math.sqrt(min(1.0, max(0.0, haversine))))


def scheme_task_response(db: Session, task: SchemeTask, public: bool = False) -> dict:
    engineer = db.get(User, task.engineer_id)
    profile = db.get(EngineerProfile, task.engineer_id)
    assigned_engineer = None
    if engineer is not None and profile is not None:
        assigned_engineer = {
            "name": engineer.name,
            "department": profile.department,
            "registration_number": profile.registration_number,
            "skills": profile.skills,
        }
        if not public:
            assigned_engineer["id"] = engineer.id
    response = {
        "id": task.id,
        "scheme_title": task.scheme_title,
        "title": task.title,
        "description": task.description,
        "department": task.department,
        "required_skills": task.required_skills,
        "status": task.status,
        "assigned_engineer": assigned_engineer,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }
    if not public:
        response["progress_note"] = task.progress_note
        response["updates"] = [
            {
                "event_type": update.event_type,
                "note": update.note,
                "actor": actor.name if (actor := db.get(User, update.actor_id)) else "NagarikSetu user",
                "created_at": update.created_at.isoformat(),
            }
            for update in db.scalars(
                select(SchemeTaskUpdate)
                .where(SchemeTaskUpdate.task_id == task.id)
                .order_by(SchemeTaskUpdate.created_at)
            )
        ]
    return response


def update_live_work_location(
    db: Session,
    engineer_id: str,
    latitude: float,
    longitude: float,
    *,
    complaint: Complaint | None = None,
    scheme_task: SchemeTask | None = None,
) -> LiveWorkLocation:
    location_query = select(LiveWorkLocation)
    if complaint is not None:
        location_query = location_query.where(LiveWorkLocation.complaint_id == complaint.id)
    elif scheme_task is not None:
        location_query = location_query.where(LiveWorkLocation.scheme_task_id == scheme_task.id)
    else:
        raise ValueError("A complaint or scheme task is required for a live location.")
    location = db.scalar(location_query)
    if location is None:
        location = LiveWorkLocation(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id if complaint else None,
            scheme_task_id=scheme_task.id if scheme_task else None,
            engineer_id=engineer_id,
            latitude=latitude,
            longitude=longitude,
        )
        db.add(location)
    else:
        location.engineer_id = engineer_id
        location.latitude = latitude
        location.longitude = longitude
        location.updated_at = datetime.now(timezone.utc)
    return location


def initialize_database() -> None:
    from app.config import validate_runtime_settings

    validate_runtime_settings()
    Base.metadata.create_all(bind=engine)
    ensure_user_timestamp_columns(engine)
    with SessionLocal() as db:
        _backfill_legacy_accounts(db)
    if settings.seed_demo_accounts and settings.environment.lower() != "production":
        with SessionLocal() as db:
            seed_demo_data(db)
            _backfill_legacy_accounts(db)


def _backfill_legacy_accounts(db: Session) -> None:
    for user in db.scalars(select(User)):
        if db.get(UserAuthentication, user.id) is None:
            db.add(
                UserAuthentication(
                    user_id=user.id,
                    email_verified=True,
                    account_status="ACTIVE",
                )
            )
    db.commit()


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    initialize_database()
    application.state.database_ready = True
    try:
        yield
    finally:
        application.state.database_ready = False


app = FastAPI(title="NagarikSetu API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",") if host.strip()],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def complaint_or_404(db: Session, complaint_id: str) -> Complaint:
    complaint = db.get(Complaint, complaint_id)
    if complaint is None:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    return complaint


def complaint_for_actor(db: Session, complaint_id: str, user: User) -> Complaint:
    complaint = complaint_or_404(db, complaint_id)
    if user.role == "officer":
        return complaint
    if user.role == "citizen" and complaint.citizen_id != user.id:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    if user.role == "engineer" and complaint.engineer_id != user.id:
        raise HTTPException(status_code=403, detail="This complaint is not assigned to you.")
    if user.role == "verifier" and complaint.verifier_id != user.id:
        raise HTTPException(status_code=403, detail="You are not the designated verifier.")
    if user.role in {"citizen", "engineer", "verifier"}:
        return complaint
    raise HTTPException(status_code=403, detail="Your account cannot access complaint records.")


def complaint_response(db: Session, complaint: Complaint) -> ComplaintResponse:
    response = ComplaintResponse.model_validate(complaint)
    updates = {}
    location_evidence = db.get(ComplaintLocationEvidence, complaint.id)
    if location_evidence is not None:
        updates.update(
            location_accuracy_meters=location_evidence.accuracy_meters,
            location_captured_at=location_evidence.captured_at,
        )
    assessment = db.scalar(
        select(ComplaintAssessment).where(ComplaintAssessment.complaint_id == complaint.id)
    )
    if assessment is not None:
        updates["assessment"] = ComplaintAssessmentResponse.model_validate(assessment)
    if complaint.engineer_id is not None:
        engineer = db.get(User, complaint.engineer_id)
        profile = db.get(EngineerProfile, complaint.engineer_id)
        if engineer is not None and profile is not None:
            updates["assigned_engineer"] = AssignedEngineerResponse(
                id=engineer.id,
                name=engineer.name,
                department=profile.department,
                registration_number=profile.registration_number,
                skills=profile.skills,
            )
    return response.model_copy(update=updates)


def _has_valid_attachment_signature(content_type: str, content: bytes) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if content_type in {"image/heic", "image/heif"}:
        return (
            len(content) >= 12
            and content[4:8] == b"ftyp"
            and content[8:12] in {b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1"}
        )
    if content_type in {"video/mp4", "video/quicktime", "audio/mp4"}:
        return len(content) >= 12 and content[4:8] == b"ftyp"
    if content_type in {"video/webm", "audio/webm"}:
        return content.startswith(b"\x1a\x45\xdf\xa3")
    if content_type == "audio/ogg":
        return content.startswith(b"OggS")
    if content_type == "audio/wav":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return content.startswith(b"ID3") or (
            len(content) >= 2 and content[0] == 0xFF and content[1] & 0xE0 == 0xE0
        )
    return False


async def prepare_complaint_attachments(
    files: list[UploadFile],
) -> list[tuple[str, str, bytes]]:
    if len(files) > MAX_COMPLAINT_ATTACHMENTS:
        raise HTTPException(
            status_code=413,
            detail=f"You can attach up to {MAX_COMPLAINT_ATTACHMENTS} files per report.",
        )

    prepared: list[tuple[str, str, bytes]] = []
    total_bytes = 0
    for upload in files:
        content = await upload.read(MAX_COMPLAINT_ATTACHMENT_BYTES + 1)
        if not content and not upload.filename:
            continue
        if len(content) > MAX_COMPLAINT_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Each attachment must be 20 MB or smaller.")
        total_bytes += len(content)
        if total_bytes > MAX_COMPLAINT_ATTACHMENT_TOTAL_BYTES:
            raise HTTPException(status_code=413, detail="Attachments must total 60 MB or less.")
        content_type = (upload.content_type or "").split(";", maxsplit=1)[0].strip().lower()
        if content_type not in ALLOWED_COMPLAINT_MIME_TYPES:
            raise HTTPException(status_code=415, detail="This attachment file type is not supported.")
        if not _has_valid_attachment_signature(content_type, content):
            raise HTTPException(
                status_code=415,
                detail="The attachment content does not match its declared file type.",
            )
        original_name = Path(upload.filename or "evidence").name.strip()[:255] or "evidence"
        prepared.append((original_name, content_type, content))
    return prepared


def _remove_saved_attachments(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not remove a partially saved complaint attachment.")


def recommend_complaint_assessment(
    db: Session,
    complaint: Complaint,
    payload: ComplaintCreate,
) -> ComplaintAssessment:
    report_text = f"{payload.title} {payload.description}".lower()
    suggested_category = payload.category
    category_match = False
    for category, terms in TRIAGE_CATEGORY_TERMS.items():
        if any(term in report_text for term in terms):
            suggested_category = category
            category_match = True
            break

    suggested_severity = payload.severity
    severity_match = False
    for severity in ("Critical", "High", "Low"):
        if any(term in report_text for term in SEVERITY_TERMS[severity]):
            suggested_severity = severity
            severity_match = True
            break

    words = set(re.findall(r"[a-z0-9]+", report_text))
    stop_words = {"about", "after", "along", "around", "near", "that", "there", "this", "with", "your"}
    words -= stop_words
    possible_duplicates: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    recent_complaints = db.scalars(
        select(Complaint)
        .where(
            Complaint.is_demo.is_(False),
            Complaint.created_at >= cutoff,
            Complaint.id != complaint.id,
            Complaint.official_status.not_in(("CLOSED", "OFFICIALLY_COMPLETED")),
        )
        .order_by(Complaint.created_at.desc())
        .limit(200)
    )
    for existing in recent_complaints:
        if existing.category != suggested_category:
            continue
        latitude_delta = math.radians(existing.latitude - payload.latitude)
        longitude_delta = math.radians(existing.longitude - payload.longitude)
        latitude_one = math.radians(payload.latitude)
        latitude_two = math.radians(existing.latitude)
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(latitude_one) * math.cos(latitude_two) * math.sin(longitude_delta / 2) ** 2
        )
        distance_meters = 6_371_000 * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))
        existing_words = set(re.findall(r"[a-z0-9]+", f"{existing.title} {existing.description}".lower()))
        existing_words -= stop_words
        overlap = len(words & existing_words) / max(1, len(words | existing_words))
        if distance_meters <= 200 and overlap >= 0.15:
            possible_duplicates.append(existing.reference)
            if len(possible_duplicates) == 5:
                break

    summary = re.split(r"(?<=[.!?])\s+", payload.description.strip(), maxsplit=1)[0][:500]
    rationale_parts = [
        "Suggested from report keywords; this is a preliminary recommendation, not an official decision."
    ]
    if category_match:
        rationale_parts.append("The issue category was inferred from the report text.")
    if severity_match:
        rationale_parts.append("The suggested severity was inferred from risk-related terms.")
    if possible_duplicates:
        rationale_parts.append("Nearby reports with similar text may describe the same issue.")
    return ComplaintAssessment(
        id=str(uuid.uuid4()),
        complaint_id=complaint.id,
        suggested_category=suggested_category,
        suggested_severity=suggested_severity,
        suggested_department=CATEGORY_DEPARTMENTS.get(suggested_category, "Pending triage"),
        summary=summary,
        rationale=" ".join(rationale_parts),
        confidence=0.75 if category_match or severity_match else 0.55,
        duplicate_references=possible_duplicates,
        rules_version="civicai-rule-triage-v1",
    )


def persist_complaint(
    payload: ComplaintCreate,
    db: Session,
    user: User,
    prepared_attachments: list[tuple[str, str, bytes]] | None = None,
) -> tuple[Complaint, ComplaintAssessment]:
    complaint = Complaint(
        id=str(uuid.uuid4()),
        reference=f"CP-{uuid.uuid4().hex[:10].upper()}",
        title=payload.title,
        description=payload.description,
        category=payload.category,
        severity=payload.severity,
        official_status="SUBMITTED",
        engineer_work_status="NOT_STARTED",
        verification_status="NOT_SUBMITTED",
        ward=payload.ward,
        address=payload.address,
        latitude=payload.latitude,
        longitude=payload.longitude,
        department=CATEGORY_DEPARTMENTS.get(payload.category, "Pending triage"),
        citizen_id=user.id,
    )
    assessment = recommend_complaint_assessment(db, complaint, payload)
    db.add(complaint)
    db.add(assessment)
    if payload.location_accuracy_meters is not None and payload.location_captured_at is not None:
        db.add(
            ComplaintLocationEvidence(
                complaint_id=complaint.id,
                accuracy_meters=payload.location_accuracy_meters,
                captured_at=payload.location_captured_at,
            )
        )
    stored_paths: list[Path] = []
    if prepared_attachments:
        storage_root = Path(settings.complaint_upload_path).resolve()
        try:
            storage_root.mkdir(parents=True, exist_ok=True)
            for original_name, content_type, content in prepared_attachments:
                storage_key = f"{uuid.uuid4().hex}.blob"
                path = storage_root / storage_key
                path.write_bytes(content)
                stored_paths.append(path)
                db.add(
                    ComplaintAttachment(
                        id=str(uuid.uuid4()),
                        complaint_id=complaint.id,
                        uploaded_by=user.id,
                        original_name=original_name,
                        storage_key=storage_key,
                        content_type=content_type,
                        size_bytes=len(content),
                        sha256=hashlib.sha256(content).hexdigest(),
                    )
                )
            db.commit()
        except OSError as error:
            db.rollback()
            _remove_saved_attachments(stored_paths)
            logger.exception("Could not store complaint attachments.")
            raise HTTPException(status_code=503, detail="Report evidence could not be stored.") from error
        except SQLAlchemyError as error:
            db.rollback()
            _remove_saved_attachments(stored_paths)
            logger.exception("Could not save complaint and attachment records.")
            raise HTTPException(status_code=503, detail="The report could not be saved.") from error
    else:
        try:
            db.commit()
        except SQLAlchemyError as error:
            db.rollback()
            logger.exception("Could not save a complaint record.")
            raise HTTPException(status_code=503, detail="The report could not be saved.") from error
    db.refresh(complaint)
    db.refresh(assessment)
    return complaint, assessment


@app.get("/api/health")
def health(request: Request) -> dict[str, str]:
    return {
        "status": "ok" if getattr(request.app.state, "database_ready", False) else "starting",
        "service": "NagarikSetu API",
    }


@app.post("/api/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    client_ip = request.client.host if request.client else ""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
    email_failures = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.email == payload.email,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.attempted_at >= cutoff,
        )
    ) or 0
    ip_failures = (
        db.scalar(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.ip_address == client_ip,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.attempted_at >= cutoff,
            )
        )
        or 0
    )
    if email_failures >= 10 or (client_ip and ip_failures >= 30):
        _record_login_attempt(db, request, payload.email, None, False)
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again in 15 minutes.",
        )

    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None:
        verify_unknown_user_password(payload.password)
        _record_login_attempt(db, request, payload.email, None, False)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not verify_password(payload.password, user.password_hash):
        _record_login_attempt(db, request, payload.email, user, False)
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")

    account = _get_or_create_authentication(db, user)
    if account.account_status != "ACTIVE":
        _record_login_attempt(db, request, payload.email, user, False)
        raise HTTPException(status_code=403, detail="This account is inactive. Contact an administrator.")
    if not account.email_verified:
        _record_login_attempt(db, request, payload.email, user, False)
        raise HTTPException(
            status_code=403,
            detail="Verify your email before signing in. You can request a new verification email.",
        )

    _record_login_attempt(db, request, payload.email, user, True)
    access_token = create_session_access_token(user, db)
    db.commit()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
    }


def _record_login_attempt(
    db: Session,
    request: Request,
    email: str,
    user: User | None,
    succeeded: bool,
) -> None:
    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")[:512]
    timestamp = datetime.now(timezone.utc)
    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.attempted_at < timestamp - timedelta(days=1)
        )
    )
    db.add(
        LoginAttempt(
            id=str(uuid.uuid4()),
            email=email,
            ip_address=ip_address,
            succeeded=succeeded,
            attempted_at=timestamp,
        )
    )
    db.add(
        LoginAuditLog(
            id=str(uuid.uuid4()),
            user_id=user.id if user else None,
            email=email,
            ip_address=ip_address,
            user_agent=user_agent,
            succeeded=succeeded,
            created_at=timestamp,
        )
    )
    db.commit()


def _get_or_create_authentication(db: Session, user: User) -> UserAuthentication:
    account = db.get(UserAuthentication, user.id)
    if account is None:
        account = UserAuthentication(
            user_id=user.id,
            email_verified=True,
            account_status="ACTIVE",
        )
        db.add(account)
        db.flush()
    return account


def _send_auth_email_or_raise(
    send_email: Callable[[str, str], None],
    email: str,
    token: str,
    operation: str,
) -> None:
    try:
        send_email(email, token)
    except (RuntimeError, OSError, smtplib.SMTPException) as error:
        logger.exception("Could not send %s email.", operation)
        raise HTTPException(
            status_code=503,
            detail=f"The {operation} email could not be sent. Check the SMTP configuration and try again.",
        ) from error


@app.post("/api/auth/google")
def google_login(payload: GoogleLoginRequest, db: Session = Depends(get_db)) -> dict:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured for this service.")
    claims = verify_google_id_token(payload.credential, settings.google_client_id)
    if claims.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="Google must confirm your email before sign-in.")
    email_claim = claims.get("email")
    if not isinstance(email_claim, str):
        raise HTTPException(status_code=401, detail="Google sign-in did not provide a valid email address.")
    try:
        email = normalize_email_address(email_claim)
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Google sign-in did not provide a valid email address.") from error
    if len(email) > 180:
        raise HTTPException(status_code=401, detail="Google sign-in did not provide a valid email address.")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        display_name = claims.get("name")
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = email.split("@", maxsplit=1)[0]
        user = User(
            id=str(uuid.uuid4()),
            name=display_name.strip()[:120],
            email=email,
            role="citizen",
            password_hash=hash_password(secrets.token_urlsafe(32)),
        )
        db.add(user)
        try:
            db.flush()
            db.add(
                UserAuthentication(
                    user_id=user.id,
                    email_verified=True,
                    account_status="ACTIVE",
                )
            )
            db.commit()
        except IntegrityError as error:
            db.rollback()
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                raise HTTPException(
                    status_code=503,
                    detail="A NagarikSetu account could not be created for this Google account.",
                ) from error
    account = _get_or_create_authentication(db, user)
    if account.account_status != "ACTIVE":
        raise HTTPException(status_code=403, detail="This account is inactive. Contact an administrator.")
    account.email_verified = True
    access_token = create_session_access_token(user, db)
    db.commit()
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "role": user.role},
    }


@app.post("/api/auth/register", status_code=201)
def register_citizen(
    payload: CitizenRegistrationRequest,
    db: Session = Depends(get_db),
) -> dict:
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account already uses this email.")
    try:
        ensure_email_configured()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    user = User(
        id=str(uuid.uuid4()),
        name=payload.name,
        email=payload.email,
        role="citizen",
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            UserAuthentication(
                user_id=user.id,
                email_verified=False,
                account_status="ACTIVE",
            )
        )
        db.add(CitizenProfile(user_id=user.id, phone_number=payload.phone_number))
        verification_token = create_one_time_token(
            db,
            EmailVerificationToken,
            user.id,
            EMAIL_VERIFICATION_TTL,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account already uses this email.") from None
    _send_auth_email_or_raise(send_verification_email, user.email, verification_token, "verification")
    return {"status": "verification_required", "message": "Check your email to verify your account."}


@app.post("/api/engineers/register", status_code=202)
def register_engineer(
    payload: EngineerRegistrationRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if db.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(status_code=409, detail="An account already uses this email.")
    try:
        ensure_email_configured()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    user = User(
        id=str(uuid.uuid4()),
        name=payload.name.strip(),
        email=payload.email,
        role="engineer_pending",
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    try:
        db.flush()
        db.add(
            EngineerProfile(
                user_id=user.id,
                department=payload.department.strip(),
                registration_number=payload.registration_number.strip(),
                skills=payload.skills,
                application_note=payload.application_note.strip(),
                registration_status="PENDING",
            )
        )
        db.add(
            UserAuthentication(
                user_id=user.id,
                email_verified=False,
                account_status="ACTIVE",
            )
        )
        db.add(UserContactProfile(user_id=user.id, phone_number=payload.phone_number))
        verification_token = create_one_time_token(
            db,
            EmailVerificationToken,
            user.id,
            EMAIL_VERIFICATION_TTL,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This email or engineer registration number is already in use.",
        ) from None
    _send_auth_email_or_raise(send_verification_email, user.email, verification_token, "verification")
    return {
        "status": "VERIFICATION_REQUIRED",
        "message": "Verify your email; your engineering application will then be available for officer review.",
    }


@app.post("/api/auth/verify-email")
def verify_email(payload: OneTimeTokenRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    token = db.get(EmailVerificationToken, token_digest(payload.token))
    now = datetime.now(timezone.utc)
    if token is None or token.used_at is not None or _token_expired(token.expires_at, now):
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")
    account = db.get(UserAuthentication, token.user_id)
    if account is None or account.account_status != "ACTIVE":
        raise HTTPException(status_code=400, detail="This verification link is invalid or expired.")
    token.used_at = now
    account.email_verified = True
    account.updated_at = now
    db.commit()
    return {"status": "verified", "message": "Email verified. You can now sign in."}


def _token_expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now


def _has_recent_auth_email(
    db: Session,
    token_model: type[EmailVerificationToken] | type[PasswordResetToken],
    user_id: str,
) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=1)
    return (
        db.scalar(
            select(token_model.token_hash)
            .where(
                token_model.user_id == user_id,
                token_model.created_at >= cutoff,
            )
            .limit(1)
        )
        is not None
    )


@app.post("/api/auth/resend-verification", status_code=202)
def resend_verification(
    payload: EmailAddressRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        ensure_email_configured()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is not None:
        account = db.get(UserAuthentication, user.id)
        if (
            account is not None
            and not account.email_verified
            and account.account_status == "ACTIVE"
            and not _has_recent_auth_email(db, EmailVerificationToken, user.id)
        ):
            verification_token = create_one_time_token(
                db,
                EmailVerificationToken,
                user.id,
                EMAIL_VERIFICATION_TTL,
            )
            db.commit()
            try:
                send_verification_email(user.email, verification_token)
            except (RuntimeError, OSError, smtplib.SMTPException):
                logger.exception("Could not send a verification email.")
    return {"message": "If the account needs verification, an email has been sent."}


@app.post("/api/auth/forgot-password", status_code=202)
def forgot_password(
    payload: EmailAddressRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        ensure_email_configured()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is not None:
        account = db.get(UserAuthentication, user.id)
        if (
            account is not None
            and account.account_status == "ACTIVE"
            and account.email_verified
            and not _has_recent_auth_email(db, PasswordResetToken, user.id)
        ):
            reset_token = create_one_time_token(
                db,
                PasswordResetToken,
                user.id,
                PASSWORD_RESET_TTL,
            )
            db.commit()
            try:
                send_password_reset_email(user.email, reset_token)
            except (RuntimeError, OSError, smtplib.SMTPException):
                logger.exception("Could not send a password-reset email.")
    return {"message": "If the account is eligible, password-reset instructions have been sent."}


@app.post("/api/auth/reset-password")
def reset_password(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    token = db.get(PasswordResetToken, token_digest(payload.token))
    now = datetime.now(timezone.utc)
    if token is None or token.used_at is not None or _token_expired(token.expires_at, now):
        raise HTTPException(status_code=400, detail="This password-reset link is invalid or expired.")
    user = db.get(User, token.user_id)
    account = db.get(UserAuthentication, token.user_id)
    if user is None or account is None or account.account_status != "ACTIVE":
        raise HTTPException(status_code=400, detail="This password-reset link is invalid or expired.")
    user.password_hash = hash_password(payload.password)
    token.used_at = now
    for session in db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
    ):
        session.revoked_at = now
    db.commit()
    return {"status": "password_updated", "message": "Password updated. Sign in with your new password."}


@app.post("/api/auth/logout")
def logout(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    authorization = request.headers.get("authorization", "").split()
    if len(authorization) != 2 or authorization[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="A valid sign-in is required.")
    revoke_session_access_token(authorization[1], user, db)
    return {"status": "signed_out"}


@app.get("/api/engineers/me/registration")
def my_engineer_registration(
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer_pending", "engineer")),
) -> dict:
    profile = db.get(EngineerProfile, user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Engineer application not found.")
    reviews = list(
        db.scalars(
            select(EngineerRegistrationReview)
            .where(EngineerRegistrationReview.engineer_id == user.id)
            .order_by(EngineerRegistrationReview.reviewed_at)
        )
    )
    return {
        "registration_status": profile.registration_status,
        "department": profile.department,
        "registration_number": profile.registration_number,
        "skills": profile.skills,
        "application_note": profile.application_note,
        "submitted_at": profile.submitted_at.isoformat(),
        "reviews": [
            {
                "decision": review.decision,
                "reason": review.reason,
                "reviewed_at": review.reviewed_at.isoformat(),
            }
            for review in reviews
        ],
    }


@app.put("/api/engineers/me/registration")
def resubmit_engineer_registration(
    payload: EngineerRegistrationUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer_pending")),
) -> dict[str, str]:
    profile = db.get(EngineerProfile, user.id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Engineer application not found.")
    if profile.registration_status != "REJECTED":
        raise HTTPException(status_code=409, detail="Only a rejected application can be resubmitted.")
    profile.department = payload.department.strip()
    profile.registration_number = payload.registration_number.strip()
    profile.skills = payload.skills
    profile.application_note = payload.application_note.strip()
    profile.registration_status = "PENDING"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This engineer registration number is already in use.",
        ) from None
    return {"registration_status": profile.registration_status}


@app.get(
    "/api/engineers/registrations",
    dependencies=[Depends(require_role("officer"))],
)
def list_engineer_registrations(db: Session = Depends(get_db)) -> list[dict]:
    profiles = db.scalars(
        select(EngineerProfile)
        .join(UserAuthentication, UserAuthentication.user_id == EngineerProfile.user_id)
        .where(EngineerProfile.registration_status == "PENDING")
        .where(UserAuthentication.email_verified.is_(True))
        .where(UserAuthentication.account_status == "ACTIVE")
        .order_by(EngineerProfile.submitted_at)
    )
    applications = []
    for profile in profiles:
        user = db.get(User, profile.user_id)
        if user is not None:
            applications.append(
                {
                    "user_id": user.id,
                    "name": user.name,
                    "email": user.email,
                    "department": profile.department,
                    "registration_number": profile.registration_number,
                    "skills": profile.skills,
                    "application_note": profile.application_note,
                    "submitted_at": profile.submitted_at.isoformat(),
                }
            )
    return applications


@app.post(
    "/api/engineers/registrations/{engineer_id}/decision",
    dependencies=[Depends(require_role("officer"))],
)
def decide_engineer_registration(
    engineer_id: str,
    payload: EngineerRegistrationDecisionRequest,
    db: Session = Depends(get_db),
    officer: User = Depends(require_role("officer")),
) -> dict[str, str]:
    user = db.get(User, engineer_id)
    profile = db.get(EngineerProfile, engineer_id)
    if user is None or profile is None:
        raise HTTPException(status_code=404, detail="Engineer application not found.")
    if profile.registration_status != "PENDING" or user.role != "engineer_pending":
        raise HTTPException(status_code=409, detail="This application has already been reviewed.")
    authentication = db.get(UserAuthentication, user.id)
    if authentication is None or not authentication.email_verified or authentication.account_status != "ACTIVE":
        raise HTTPException(status_code=409, detail="The engineer must verify an active email before review.")
    profile.registration_status = payload.decision
    if payload.decision == "APPROVED":
        user.role = "engineer"
    db.add(
        EngineerRegistrationReview(
            id=str(uuid.uuid4()),
            engineer_id=user.id,
            officer_id=officer.id,
            decision=payload.decision,
            reason=payload.reason,
        )
    )
    db.commit()
    return {"engineer_id": user.id, "registration_status": profile.registration_status}


@app.get(
    "/api/engineers",
    dependencies=[Depends(require_role("officer"))],
)
def list_approved_engineers(db: Session = Depends(get_db)) -> list[dict]:
    engineers = db.execute(
        select(User, EngineerProfile)
        .join(EngineerProfile, EngineerProfile.user_id == User.id)
        .where(EngineerProfile.registration_status == "APPROVED")
        .order_by(EngineerProfile.department, User.name)
    )
    return [
        {
            "id": user.id,
            "name": user.name,
            "department": profile.department,
            "registration_number": profile.registration_number,
            "skills": profile.skills,
        }
        for user, profile in engineers
    ]


@app.get(
    "/api/verification/officers",
    dependencies=[Depends(require_role("officer"))],
)
def list_verification_officers(db: Session = Depends(get_db)) -> list[dict[str, str]]:
    users = db.scalars(select(User).where(User.role == "verifier").order_by(User.name))
    return [{"id": user.id, "name": user.name, "email": user.email} for user in users]


@app.get(
    "/api/scheme-tasks/eligible-engineers",
    dependencies=[Depends(require_role("officer"))],
)
def list_scheme_task_eligible_engineers(
    department: str,
    required_skills: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    skills = [skill.strip() for skill in required_skills.split(",") if skill.strip()]
    if not department.strip() or not skills:
        raise HTTPException(status_code=422, detail="Choose a department and at least one required skill.")
    candidates = db.execute(
        select(User, EngineerProfile)
        .join(EngineerProfile, EngineerProfile.user_id == User.id)
        .where(
            User.role == "engineer",
            EngineerProfile.registration_status == "APPROVED",
        )
        .order_by(EngineerProfile.department, User.name)
    )
    return [
        {
            "id": engineer.id,
            "name": engineer.name,
            "department": profile.department,
            "registration_number": profile.registration_number,
            "skills": profile.skills,
        }
        for engineer, profile in candidates
        if engineer_matches_scheme_task(profile, department, skills)
    ]


@app.post("/api/scheme-tasks", status_code=201)
def create_scheme_task(
    payload: SchemeTaskCreate,
    db: Session = Depends(get_db),
    officer: User = Depends(require_role("officer")),
) -> dict:
    engineer = db.get(User, payload.engineer_id)
    profile = db.get(EngineerProfile, payload.engineer_id)
    if (
        engineer is None
        or engineer.role != "engineer"
        or profile is None
        or profile.registration_status != "APPROVED"
        or not engineer_matches_scheme_task(profile, payload.department, payload.required_skills)
    ):
        raise HTTPException(
            status_code=422,
            detail="Choose an approved engineer whose department and skills match this scheme task.",
        )
    task = SchemeTask(
        id=str(uuid.uuid4()),
        scheme_title=payload.scheme_title,
        title=payload.title,
        description=payload.description,
        department=payload.department,
        required_skills=payload.required_skills,
        engineer_id=engineer.id,
        assigned_by=officer.id,
    )
    db.add(task)
    db.add(
        SchemeTaskUpdate(
            id=str(uuid.uuid4()),
            task_id=task.id,
            actor_id=officer.id,
            event_type="ASSIGNED",
            note=f"Assigned to {engineer.name}.",
        )
    )
    db.commit()
    db.refresh(task)
    return scheme_task_response(db, task)


@app.get("/api/scheme-tasks")
def list_scheme_tasks(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    if user.role == "officer":
        query = select(SchemeTask).order_by(SchemeTask.created_at.desc())
    elif user.role == "engineer":
        query = (
            select(SchemeTask)
            .where(SchemeTask.engineer_id == user.id)
            .order_by(SchemeTask.created_at.desc())
        )
    else:
        raise HTTPException(status_code=403, detail="Your account cannot access scheme work.")
    return [scheme_task_response(db, task) for task in db.scalars(query)]


@app.get("/api/public/scheme-tasks")
def list_public_scheme_tasks(db: Session = Depends(get_db)) -> list[dict]:
    tasks = db.scalars(select(SchemeTask).order_by(SchemeTask.created_at.desc()))
    return [scheme_task_response(db, task, public=True) for task in tasks]


def scheme_task_for_engineer(db: Session, task_id: str, engineer: User) -> SchemeTask:
    task = db.get(SchemeTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scheme task not found.")
    if task.engineer_id != engineer.id:
        raise HTTPException(status_code=403, detail="This scheme task is not assigned to you.")
    return task


@app.post("/api/scheme-tasks/{task_id}/start")
def start_scheme_task(
    task_id: str,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict:
    task = scheme_task_for_engineer(db, task_id, engineer)
    if task.status != "ASSIGNED":
        raise HTTPException(status_code=409, detail="Only assigned scheme tasks can be started.")
    task.status = "IN_PROGRESS"
    task.progress_note = "Work started."
    db.add(
        SchemeTaskUpdate(
            id=str(uuid.uuid4()),
            task_id=task.id,
            actor_id=engineer.id,
            event_type="WORK_STARTED",
            note=task.progress_note,
        )
    )
    db.commit()
    db.refresh(task)
    return scheme_task_response(db, task)


@app.post("/api/scheme-tasks/{task_id}/progress")
def update_scheme_task_progress(
    task_id: str,
    payload: SchemeTaskProgressRequest,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict:
    task = scheme_task_for_engineer(db, task_id, engineer)
    if task.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Start the assigned scheme task before adding progress.")
    task.progress_note = payload.note
    task.updated_at = datetime.now(timezone.utc)
    db.add(
        SchemeTaskUpdate(
            id=str(uuid.uuid4()),
            task_id=task.id,
            actor_id=engineer.id,
            event_type="PROGRESS_UPDATE",
            note=payload.note,
        )
    )
    db.commit()
    db.refresh(task)
    return scheme_task_response(db, task)


@app.post("/api/scheme-tasks/{task_id}/complete")
def complete_scheme_task(
    task_id: str,
    payload: SchemeTaskCompletionRequest,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict:
    task = scheme_task_for_engineer(db, task_id, engineer)
    if task.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Start the assigned scheme task before completing it.")
    task.status = "COMPLETED"
    task.progress_note = payload.note
    task.updated_at = datetime.now(timezone.utc)
    db.add(
        SchemeTaskUpdate(
            id=str(uuid.uuid4()),
            task_id=task.id,
            actor_id=engineer.id,
            event_type="WORK_COMPLETED",
            note=payload.note,
        )
    )
    location = db.scalar(
        select(LiveWorkLocation).where(LiveWorkLocation.scheme_task_id == task.id)
    )
    if location is not None:
        db.delete(location)
    db.commit()
    db.refresh(task)
    return scheme_task_response(db, task)


@app.post("/api/scheme-tasks/{task_id}/location")
def update_scheme_task_location(
    task_id: str,
    payload: LiveWorkLocationRequest,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    task = scheme_task_for_engineer(db, task_id, engineer)
    if task.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Live location is available only while scheme work is active.")
    update_live_work_location(
        db,
        engineer.id,
        payload.latitude,
        payload.longitude,
        scheme_task=task,
    )
    db.commit()
    return {"task_id": task.id, "status": task.status}


@app.delete("/api/scheme-tasks/{task_id}/location")
def stop_scheme_task_location(
    task_id: str,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    task = scheme_task_for_engineer(db, task_id, engineer)
    location = db.scalar(
        select(LiveWorkLocation).where(LiveWorkLocation.scheme_task_id == task.id)
    )
    if location is not None:
        db.delete(location)
        db.commit()
    return {"task_id": task.id, "status": "LOCATION_SHARING_STOPPED"}


@app.get("/api/work/live-locations", dependencies=[Depends(require_role("officer"))])
def list_live_work_locations(db: Session = Depends(get_db)) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    response: list[dict] = []
    stale_locations: list[LiveWorkLocation] = []
    locations = db.scalars(
        select(LiveWorkLocation).order_by(LiveWorkLocation.updated_at.desc())
    )
    for location in locations:
        updated_at = location.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        if updated_at < cutoff:
            stale_locations.append(location)
            continue
        if location.complaint_id:
            complaint = db.get(Complaint, location.complaint_id)
            if complaint is None or complaint.engineer_work_status != "IN_PROGRESS":
                stale_locations.append(location)
                continue
            work_type = "complaint"
            work_id = complaint.id
            title = complaint.title
            reference = complaint.reference
            scheme_title = None
        else:
            task = db.get(SchemeTask, location.scheme_task_id)
            if task is None or task.status != "IN_PROGRESS":
                stale_locations.append(location)
                continue
            work_type = "scheme"
            work_id = task.id
            title = task.title
            reference = None
            scheme_title = task.scheme_title
        engineer = db.get(User, location.engineer_id)
        profile = db.get(EngineerProfile, location.engineer_id)
        if engineer is None or profile is None:
            stale_locations.append(location)
            continue
        response.append(
            {
                "work_type": work_type,
                "work_id": work_id,
                "title": title,
                "reference": reference,
                "scheme_title": scheme_title,
                "status": "IN_PROGRESS",
                "assigned_engineer": {
                    "id": engineer.id,
                    "name": engineer.name,
                    "department": profile.department,
                    "registration_number": profile.registration_number,
                    "skills": profile.skills,
                },
                "latitude": location.latitude,
                "longitude": location.longitude,
                "updated_at": updated_at.isoformat(),
            }
        )
    for location in stale_locations:
        db.delete(location)
    if stale_locations:
        db.commit()
    return response


@app.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"id": user.id, "name": user.name, "email": user.email, "role": user.role}


@app.get("/api/profile")
def get_profile(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    account = _get_or_create_authentication(db, user)
    citizen_profile = db.get(CitizenProfile, user.id)
    contact = db.get(UserContactProfile, user.id)
    profile: dict = {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "email_verified": account.email_verified,
        "account_status": account.account_status,
        "phone_number": (
            citizen_profile.phone_number
            if citizen_profile is not None
            else contact.phone_number if contact else ""
        ),
    }
    if citizen_profile is not None:
        profile["address"] = citizen_profile.address
        profile["ward"] = citizen_profile.ward
    if user.role in {"engineer", "engineer_pending"}:
        engineer = db.get(EngineerProfile, user.id)
        if engineer is not None:
            profile["official"] = {
                "department": engineer.department,
                "employee_id": engineer.registration_number,
                "designation": "Engineer",
                "jurisdiction": "",
                "registration_status": engineer.registration_status,
            }
    if user.role in {"officer", "verifier"}:
        officer = db.get(OfficerProfile, user.id)
        if officer is not None:
            profile["official"] = {
                "department": officer.department,
                "employee_id": officer.employee_id,
                "designation": officer.designation,
                "jurisdiction": officer.jurisdiction,
            }
    return profile


@app.put("/api/profile")
def update_profile(
    payload: ProfileUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    if user.role != "citizen":
        raise HTTPException(
            status_code=403,
            detail="Official account details can only be changed by an administrator.",
        )
    contact = db.get(CitizenProfile, user.id)
    if contact is None:
        contact = CitizenProfile(
            user_id=user.id,
            phone_number=payload.phone_number,
            address=payload.address,
            ward=payload.ward,
        )
        db.add(contact)
    else:
        contact.phone_number = payload.phone_number
        contact.address = payload.address
        contact.ward = payload.ward
        contact.updated_at = datetime.now(timezone.utc)
    user.name = payload.name
    db.commit()
    return {
        "name": user.name,
        "phone_number": contact.phone_number,
        "address": contact.address,
        "ward": contact.ward,
    }


@app.post("/api/auth/accept-invitation")
def accept_invitation(
    payload: InvitationAcceptRequest,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    invitation = db.get(UserInvitation, token_digest(payload.token))
    now = datetime.now(timezone.utc)
    if (
        invitation is None
        or invitation.used_at is not None
        or _token_expired(invitation.expires_at, now)
        or db.scalar(select(User.id).where(User.email == invitation.email)) is not None
    ):
        raise HTTPException(status_code=400, detail="This invitation is invalid or expired.")

    user = User(
        id=str(uuid.uuid4()),
        name=invitation.name,
        email=invitation.email,
        role=invitation.role,
        password_hash=hash_password(payload.password),
    )
    try:
        db.add(user)
        db.flush()
        db.add(
            UserAuthentication(
                user_id=user.id,
                email_verified=True,
                account_status="ACTIVE",
            )
        )
        db.add(UserContactProfile(user_id=user.id, phone_number=payload.phone_number))
        db.add(
            OfficerProfile(
                user_id=user.id,
                employee_id=invitation.employee_id,
                designation=invitation.designation,
                department=invitation.department,
                jurisdiction=invitation.jurisdiction,
            )
        )
        invitation.used_at = now
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The official account could not be created because its email or employee ID is already in use.",
        ) from None
    return {"status": "created", "message": "Official account created. You can now sign in."}


@app.post("/api/admin/invitations", status_code=201)
def create_official_invitation(
    payload: OfficialInvitationRequest,
    db: Session = Depends(get_db),
    administrator: User = Depends(require_role("admin")),
) -> dict[str, str]:
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(status_code=409, detail="An account already uses this email.")
    if db.scalar(
        select(OfficerProfile.user_id).where(OfficerProfile.employee_id == payload.employee_id)
    ) is not None:
        raise HTTPException(status_code=409, detail="This employee ID is already in use.")
    try:
        ensure_email_configured()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    for existing_invitation in db.scalars(
        select(UserInvitation).where(
            UserInvitation.email == payload.email,
            UserInvitation.used_at.is_(None),
        )
    ):
        db.delete(existing_invitation)
    token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        token_hash=token_digest(token),
        email=payload.email,
        name=payload.name,
        role=payload.role,
        employee_id=payload.employee_id,
        designation=payload.designation,
        department=payload.department,
        jurisdiction=payload.jurisdiction,
        created_by=administrator.id,
        expires_at=datetime.now(timezone.utc) + INVITATION_TTL,
    )
    db.add(invitation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This official invitation could not be created because the account data conflicts with an existing record.",
        ) from None
    _send_auth_email_or_raise(send_invitation_email, payload.email, token, "invitation")
    return {"status": "invited", "message": "An official invitation has been sent."}


@app.get("/api/admin/users", dependencies=[Depends(require_role("admin"))])
def list_accounts(db: Session = Depends(get_db)) -> list[dict]:
    accounts = []
    for user in db.scalars(select(User).order_by(User.name)):
        authentication = db.get(UserAuthentication, user.id)
        accounts.append(
            {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "account_status": authentication.account_status if authentication else "ACTIVE",
                "email_verified": authentication.email_verified if authentication else True,
            }
        )
    return accounts


@app.patch("/api/admin/users/{user_id}/status")
def set_account_status(
    user_id: str,
    payload: AccountStatusRequest,
    db: Session = Depends(get_db),
    administrator: User = Depends(require_role("admin")),
) -> dict[str, str]:
    if user_id == administrator.id and not payload.active:
        raise HTTPException(status_code=409, detail="You cannot deactivate your own administrator account.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    account = _get_or_create_authentication(db, user)
    account.account_status = "ACTIVE" if payload.active else "INACTIVE"
    account.updated_at = datetime.now(timezone.utc)
    if not payload.active:
        for session in db.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
        ):
            session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"user_id": user_id, "account_status": account.account_status}


@app.get("/api/complaints", response_model=list[ComplaintResponse])
def list_complaints(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ComplaintResponse]:
    query = select(Complaint).order_by(Complaint.created_at.desc())
    if user.role == "citizen":
        query = query.where(Complaint.citizen_id == user.id)
    elif user.role == "engineer":
        query = query.where(Complaint.engineer_id == user.id)
    elif user.role == "verifier":
        query = query.where(Complaint.verifier_id == user.id)
    elif user.role != "officer":
        raise HTTPException(status_code=403, detail="Your account cannot access complaint records.")
    return [complaint_response(db, complaint) for complaint in db.scalars(query)]


@app.get("/api/complaints/{complaint_id}", response_model=ComplaintResponse)
def get_complaint(
    complaint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintResponse:
    return complaint_response(db, complaint_for_actor(db, complaint_id, user))


@app.post("/api/complaints", response_model=ComplaintResponse, status_code=201)
def create_complaint(
    payload: ComplaintCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("citizen")),
) -> ComplaintResponse:
    complaint, assessment = persist_complaint(payload, db, user)
    return complaint_response(db, complaint).model_copy(
        update={"assessment": ComplaintAssessmentResponse.model_validate(assessment)}
    )


@app.post("/api/complaints/with-evidence", response_model=ComplaintResponse, status_code=201)
async def create_complaint_with_evidence(
    title: str = Form(..., min_length=8, max_length=180),
    description: str = Form(..., min_length=12, max_length=4000),
    category: str = Form(..., min_length=2, max_length=60),
    severity: str = Form("Medium"),
    address: str = Form(..., min_length=4, max_length=240),
    ward: str = Form(..., min_length=2, max_length=100),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    location_accuracy_meters: float | None = Form(default=None, ge=0, le=100000),
    location_captured_at: datetime | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("citizen")),
) -> ComplaintResponse:
    try:
        payload = ComplaintCreate(
            title=title,
            description=description,
            category=category,
            severity=severity,
            address=address,
            ward=ward,
            latitude=latitude,
            longitude=longitude,
            location_accuracy_meters=location_accuracy_meters,
            location_captured_at=location_captured_at,
        )
    except ValidationError as error:
        raise HTTPException(
            status_code=422,
            detail=error.errors(include_context=False),
        ) from error
    prepared_attachments = await prepare_complaint_attachments(files)
    complaint, assessment = persist_complaint(payload, db, user, prepared_attachments)
    return complaint_response(db, complaint).model_copy(
        update={"assessment": ComplaintAssessmentResponse.model_validate(assessment)}
    )


@app.get(
    "/api/complaints/{complaint_id}/attachments",
    response_model=list[ComplaintAttachmentResponse],
)
def list_complaint_attachments(
    complaint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ComplaintAttachment]:
    complaint_for_actor(db, complaint_id, user)
    attachments = db.scalars(
        select(ComplaintAttachment)
        .where(ComplaintAttachment.complaint_id == complaint_id)
        .order_by(ComplaintAttachment.uploaded_at)
    )
    return list(attachments)


@app.get("/api/complaint-attachments/{attachment_id}")
def download_complaint_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    attachment = db.get(ComplaintAttachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found.")
    complaint_for_actor(db, attachment.complaint_id, user)
    path = Path(settings.complaint_upload_path).resolve() / attachment.storage_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment file is no longer available.")
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_name,
    )


@app.get("/api/complaints/{complaint_id}/assessment", response_model=ComplaintAssessmentResponse)
def get_complaint_assessment(
    complaint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintAssessment:
    complaint_for_actor(db, complaint_id, user)
    assessment = db.scalar(
        select(ComplaintAssessment).where(ComplaintAssessment.complaint_id == complaint_id)
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="No triage recommendation is available.")
    return assessment


@app.post(
    "/api/complaints/{complaint_id}/triage",
    response_model=ComplaintResponse,
    dependencies=[Depends(require_role("officer"))],
)
def decide_complaint_triage(
    complaint_id: str,
    payload: ComplaintTriageDecisionRequest,
    db: Session = Depends(get_db),
    officer: User = Depends(require_role("officer")),
) -> ComplaintResponse:
    complaint = complaint_or_404(db, complaint_id)
    if complaint.engineer_id is not None or complaint.official_status in {
        "CLOSED",
        "OFFICIALLY_COMPLETED",
    }:
        raise HTTPException(status_code=409, detail="Triage can only be reviewed before assignment.")
    assessment = db.scalar(
        select(ComplaintAssessment).where(ComplaintAssessment.complaint_id == complaint.id)
    )
    if assessment is None:
        raise HTTPException(status_code=404, detail="No triage recommendation is available.")
    complaint.category = payload.category
    complaint.severity = payload.severity
    complaint.department = CATEGORY_DEPARTMENTS[payload.category]
    assessment.reviewed_by = officer.id
    assessment.override_reason = payload.reason
    assessment.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(complaint)
    db.refresh(assessment)
    return complaint_response(db, complaint)


@app.post(
    "/api/complaints/{complaint_id}/feedback",
    response_model=ComplaintFeedbackResponse,
    status_code=201,
)
def submit_complaint_feedback(
    complaint_id: str,
    payload: ComplaintFeedbackCreate,
    db: Session = Depends(get_db),
    citizen: User = Depends(require_role("citizen")),
) -> ComplaintFeedback:
    complaint = complaint_or_404(db, complaint_id)
    if complaint.citizen_id != citizen.id:
        raise HTTPException(status_code=404, detail="Complaint not found.")
    if complaint.official_status not in {"CLOSED", "OFFICIALLY_COMPLETED"}:
        raise HTTPException(status_code=409, detail="Feedback is available after official closure.")
    if db.scalar(
        select(ComplaintFeedback).where(ComplaintFeedback.complaint_id == complaint.id)
    ) is not None:
        raise HTTPException(status_code=409, detail="Feedback has already been submitted for this report.")
    feedback = ComplaintFeedback(
        id=str(uuid.uuid4()),
        complaint_id=complaint.id,
        citizen_id=citizen.id,
        rating=payload.rating,
        comment=payload.comment,
    )
    db.add(feedback)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Feedback has already been submitted for this report.",
        ) from error
    db.refresh(feedback)
    return feedback


@app.get(
    "/api/complaints/{complaint_id}/feedback",
    response_model=ComplaintFeedbackResponse,
)
def get_complaint_feedback(
    complaint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintFeedback:
    complaint = complaint_for_actor(db, complaint_id, user)
    if user.role not in {"citizen", "officer"}:
        raise HTTPException(status_code=403, detail="Feedback is only available to the reporting citizen and officers.")
    feedback = db.scalar(
        select(ComplaintFeedback).where(ComplaintFeedback.complaint_id == complaint.id)
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="No feedback has been submitted.")
    return feedback


@app.get("/api/dashboard")
def dashboard(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    query = select(Complaint).order_by(Complaint.created_at.desc())
    if user.role == "citizen":
        query = query.where(Complaint.citizen_id == user.id)
    elif user.role == "engineer":
        query = query.where(Complaint.engineer_id == user.id)
    elif user.role == "verifier":
        query = query.where(Complaint.verifier_id == user.id)
    elif user.role != "officer":
        raise HTTPException(status_code=403, detail="Your account cannot access complaint records.")
    complaints = list(db.scalars(query.limit(30)))
    active = [item for item in complaints if item.official_status not in {"CLOSED", "OFFICIALLY_COMPLETED"}]
    return {
        "counts": {
            "open": len(active),
            "awaiting_verification": sum(
                item.official_status == "AWAITING_VERIFICATION" for item in complaints
            ),
            "resolved": sum(
                item.official_status in {"CLOSED", "OFFICIALLY_COMPLETED"} for item in complaints
            ),
            "high_priority": sum(item.severity in {"Critical", "High"} for item in active),
        },
        "complaints": [complaint_response(db, item).model_dump(mode="json") for item in complaints],
    }


def public_report_summary(report: Complaint) -> dict:
    category = report.category if report.category in CATEGORY_DEPARTMENTS else "Other"
    severity = report.severity if report.severity in {"Critical", "High", "Medium", "Low"} else "Unrated"
    ward_match = re.match(r"(?i)^\s*ward\s+\d+\b", report.ward)
    return {
        "reference": report.reference,
        "title": f"{category} issue",
        "category": category,
        "severity": severity,
        "official_status": report.official_status,
        "engineer_work_status": report.engineer_work_status,
        "verification_status": report.verification_status,
        "ward": ward_match.group(0).strip().title() if ward_match else "General area",
        "latitude": round(report.latitude, 2),
        "longitude": round(report.longitude, 2),
        "department": CATEGORY_DEPARTMENTS.get(category, "Pending triage"),
        "created_at": report.created_at,
    }


@app.get("/api/public/dashboard", response_model=PublicDashboardResponse)
def public_dashboard(db: Session = Depends(get_db)) -> PublicDashboardResponse:
    public_reports = Complaint.is_demo.is_(False)
    status_counts = dict(
        db.execute(
            select(Complaint.official_status, func.count(Complaint.id))
            .where(public_reports)
            .group_by(Complaint.official_status)
        ).all()
    )
    raw_category_counts = dict(
        db.execute(
            select(Complaint.category, func.count(Complaint.id))
            .where(public_reports)
            .group_by(Complaint.category)
            .order_by(Complaint.category)
        ).all()
    )
    category_counts: dict[str, int] = {}
    for category, count in raw_category_counts.items():
        public_category = category if category in CATEGORY_DEPARTMENTS else "Other"
        category_counts[public_category] = category_counts.get(public_category, 0) + count
    total = sum(status_counts.values())
    resolved = status_counts.get("CLOSED", 0) + status_counts.get("OFFICIALLY_COMPLETED", 0)
    high_priority = db.scalar(
        select(func.count(Complaint.id)).where(
            public_reports,
            Complaint.severity.in_(("Critical", "High")),
            Complaint.official_status.not_in(("CLOSED", "OFFICIALLY_COMPLETED")),
        )
    ) or 0
    recent_reports = db.scalars(
        select(Complaint)
        .where(public_reports)
        .order_by(Complaint.created_at.desc())
        .limit(30)
    )
    return PublicDashboardResponse(
        counts={
            "total_reports": total,
            "open": total - resolved,
            "awaiting_verification": status_counts.get("AWAITING_VERIFICATION", 0),
            "resolved": resolved,
            "high_priority": high_priority,
        },
        by_category=category_counts,
        complaints=[public_report_summary(report) for report in recent_reports],
    )


@app.post(
    "/api/complaints/{complaint_id}/assign",
    response_model=ComplaintResponse,
    dependencies=[Depends(require_role("officer"))],
)
def assign_complaint(
    complaint_id: str,
    payload: AssignmentRequest,
    db: Session = Depends(get_db),
    officer: User = Depends(require_role("officer")),
) -> ComplaintResponse:
    complaint = complaint_or_404(db, complaint_id)
    if complaint.official_status in {"CLOSED", "OFFICIALLY_COMPLETED"}:
        raise HTTPException(status_code=409, detail="A completed complaint cannot be reassigned.")
    if complaint.verification_status == "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="A complaint awaiting verification cannot be reassigned.")
    engineer = db.get(User, payload.engineer_id)
    verifier = db.get(User, payload.verifier_id)
    profile = db.get(EngineerProfile, payload.engineer_id)
    if (
        engineer is None
        or engineer.role != "engineer"
        or profile is None
        or profile.registration_status != "APPROVED"
        or not engineer_matches_complaint(profile, complaint)
    ):
        raise HTTPException(
            status_code=422,
            detail="Choose an approved engineer whose department and skills match this report.",
        )
    if verifier is None or verifier.role != "verifier":
        raise HTTPException(status_code=422, detail="Choose a designated verification officer.")
    live_location = db.scalar(
        select(LiveWorkLocation).where(LiveWorkLocation.complaint_id == complaint.id)
    )
    if live_location is not None:
        db.delete(live_location)
    complaint.engineer_id = engineer.id
    complaint.verifier_id = verifier.id
    complaint.official_status = "ASSIGNED"
    complaint.engineer_work_status = "NOT_STARTED"
    complaint.verification_status = "NOT_SUBMITTED"
    db.add(
        ComplaintAssignment(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id,
            engineer_id=engineer.id,
            verifier_id=verifier.id,
            assigned_by=officer.id,
        )
    )
    db.commit()
    db.refresh(complaint)
    return complaint_response(db, complaint)


@app.get(
    "/api/complaints/{complaint_id}/eligible-engineers",
    dependencies=[Depends(require_role("officer"))],
)
def list_eligible_engineers(
    complaint_id: str,
    db: Session = Depends(get_db),
) -> list[dict]:
    complaint = complaint_or_404(db, complaint_id)
    eligible = db.execute(
        select(User, EngineerProfile)
        .join(EngineerProfile, EngineerProfile.user_id == User.id)
        .where(
            User.role == "engineer",
            EngineerProfile.registration_status == "APPROVED",
        )
        .order_by(EngineerProfile.department, User.name)
    )
    return [
        {
            "id": engineer.id,
            "name": engineer.name,
            "department": profile.department,
            "registration_number": profile.registration_number,
            "skills": profile.skills,
        }
        for engineer, profile in eligible
        if engineer_matches_complaint(profile, complaint)
    ]


@app.post("/api/complaints/{complaint_id}/work/start")
def start_work(
    complaint_id: str,
    payload: WorkUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    complaint = complaint_for_actor(db, complaint_id, user)
    if complaint.engineer_work_status not in {"NOT_STARTED", "REWORK_IN_PROGRESS"}:
        raise HTTPException(status_code=409, detail="Work can only be started for an assigned or rework case.")
    event_type = (
        "REWORK_STARTED"
        if complaint.engineer_work_status == "REWORK_IN_PROGRESS"
        else "WORK_STARTED"
    )
    complaint.engineer_work_status = "IN_PROGRESS"
    complaint.official_status = "IN_PROGRESS"
    db.add(
        WorkUpdate(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id,
            actor_id=user.id,
            event_type=event_type,
            note=payload.note,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    )
    db.commit()
    return {"complaint_id": complaint.id, "engineer_work_status": complaint.engineer_work_status}


@app.post("/api/complaints/{complaint_id}/work/progress")
def update_work_progress(
    complaint_id: str,
    payload: WorkUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    complaint = complaint_for_actor(db, complaint_id, user)
    if complaint.engineer_work_status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Start assigned work before adding a progress update.")
    db.add(
        WorkUpdate(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id,
            actor_id=user.id,
            event_type="PROGRESS_UPDATE",
            note=payload.note,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    )
    db.commit()
    return {"complaint_id": complaint.id, "engineer_work_status": complaint.engineer_work_status}


@app.post("/api/complaints/{complaint_id}/work/location")
def update_complaint_work_location(
    complaint_id: str,
    payload: LiveWorkLocationRequest,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    complaint = complaint_for_actor(db, complaint_id, engineer)
    if complaint.engineer_work_status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Live location is available only while complaint work is active.")
    update_live_work_location(
        db,
        engineer.id,
        payload.latitude,
        payload.longitude,
        complaint=complaint,
    )
    db.commit()
    return {"complaint_id": complaint.id, "status": complaint.engineer_work_status}


@app.delete("/api/complaints/{complaint_id}/work/location")
def stop_complaint_work_location(
    complaint_id: str,
    db: Session = Depends(get_db),
    engineer: User = Depends(require_role("engineer")),
) -> dict[str, str]:
    complaint = complaint_for_actor(db, complaint_id, engineer)
    location = db.scalar(
        select(LiveWorkLocation).where(LiveWorkLocation.complaint_id == complaint.id)
    )
    if location is not None:
        db.delete(location)
        db.commit()
    return {"complaint_id": complaint.id, "status": "LOCATION_SHARING_STOPPED"}


@app.get("/api/complaints/{complaint_id}/work/history")
def work_history(
    complaint_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    complaint = complaint_for_actor(db, complaint_id, user)
    events: list[dict] = []
    for assignment in db.scalars(
        select(ComplaintAssignment)
        .where(ComplaintAssignment.complaint_id == complaint.id)
        .order_by(ComplaintAssignment.assigned_at)
    ):
        assigned_by = db.get(User, assignment.assigned_by)
        engineer = db.get(User, assignment.engineer_id)
        verifier = db.get(User, assignment.verifier_id)
        events.append(
            {
                "event_type": "ASSIGNED",
                "note": f"Assigned to {engineer.name if engineer else 'engineer'}; verification officer: {verifier.name if verifier else 'unassigned'}.",
                "actor": assigned_by.name if assigned_by else "Department officer",
                "created_at": assignment.assigned_at.isoformat(),
            }
        )
    for update in db.scalars(
        select(WorkUpdate)
        .where(WorkUpdate.complaint_id == complaint.id)
        .order_by(WorkUpdate.created_at)
    ):
        if update.event_type == "SUBMITTED_FOR_VERIFICATION":
            continue
        actor = db.get(User, update.actor_id)
        event = {
            "event_type": update.event_type,
            "note": update.note,
            "actor": actor.name if actor else "NagarikSetu user",
            "created_at": update.created_at.isoformat(),
        }
        if user.role != "citizen":
            event.update(latitude=update.latitude, longitude=update.longitude)
        events.append(event)
    for submission in db.scalars(
        select(WorkSubmission)
        .where(WorkSubmission.complaint_id == complaint.id)
        .order_by(WorkSubmission.submitted_at)
    ):
        engineer = db.get(User, submission.engineer_id)
        event = {
            "event_type": "SUBMITTED_FOR_VERIFICATION",
            "note": submission.completion_notes,
            "actor": engineer.name if engineer else "Field engineer",
            "created_at": submission.submitted_at.isoformat(),
            "before_evidence": submission.before_evidence,
            "after_evidence": submission.after_evidence,
            "attempt_number": submission.attempt_number,
            "captured_at": submission.captured_at.isoformat(),
        }
        if user.role != "citizen":
            event.update(latitude=submission.latitude, longitude=submission.longitude)
        events.append(event)
    return sorted(events, key=lambda event: event["created_at"])


@app.post("/api/complaints/{complaint_id}/work/submit")
def submit_work(
    complaint_id: str,
    payload: WorkSubmissionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("engineer")),
) -> dict:
    complaint = complaint_for_actor(db, complaint_id, user)
    if not complaint.verifier_id:
        raise HTTPException(
            status_code=409,
            detail="A designated verification officer must be assigned before work is submitted.",
        )
    if complaint.engineer_work_status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Start or resume work before submitting it for verification.")
    if complaint.official_status in {"CLOSED", "OFFICIALLY_COMPLETED"}:
        raise HTTPException(status_code=409, detail="An officially completed complaint cannot be resubmitted.")
    submission = WorkSubmission(
        id=str(uuid.uuid4()),
        complaint_id=complaint.id,
        engineer_id=user.id,
        work_details=payload.work_details,
        completion_notes=payload.completion_notes,
        before_evidence=payload.before_evidence,
        after_evidence=payload.after_evidence,
        latitude=payload.latitude,
        longitude=payload.longitude,
        captured_at=payload.captured_at,
        attempt_number=len(complaint.submissions) + 1,
    )
    complaint.engineer_work_status = "SUBMITTED_FOR_VERIFICATION"
    complaint.verification_status = "PENDING_REVIEW"
    complaint.official_status = "AWAITING_VERIFICATION"
    db.add(submission)
    if (
        payload.location_accuracy_meters is not None
        and payload.location_captured_at is not None
    ):
        db.add(
            WorkSubmissionLocationEvidence(
                submission_id=submission.id,
                accuracy_meters=payload.location_accuracy_meters,
                captured_at=payload.location_captured_at,
            )
        )
    db.add(
        WorkUpdate(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id,
            actor_id=user.id,
            event_type="SUBMITTED_FOR_VERIFICATION",
            note=payload.completion_notes,
            latitude=payload.latitude,
            longitude=payload.longitude,
        )
    )
    live_location = db.scalar(
        select(LiveWorkLocation).where(LiveWorkLocation.complaint_id == complaint.id)
    )
    if live_location is not None:
        db.delete(live_location)
    db.commit()
    return {"submission_id": submission.id, "attempt_number": submission.attempt_number}


@app.get("/api/verification/queue")
def verification_queue(
    db: Session = Depends(get_db), user: User = Depends(require_role("verifier"))
) -> list[dict]:
    complaints = db.scalars(
        select(Complaint).where(
            Complaint.verifier_id == user.id,
            Complaint.verification_status == "PENDING_REVIEW",
        )
    )
    queue = []
    for complaint in complaints:
        submission = db.scalar(
            select(WorkSubmission)
            .where(WorkSubmission.complaint_id == complaint.id)
            .order_by(WorkSubmission.attempt_number.desc())
        )
        if submission:
            location_evidence = db.get(WorkSubmissionLocationEvidence, submission.id)
            distance_meters = distance_between_points_meters(
                complaint.latitude,
                complaint.longitude,
                submission.latitude,
                submission.longitude,
            )
            queue.append(
                {
                    "complaint": complaint_response(db, complaint).model_dump(mode="json"),
                    "submission": {
                        "id": submission.id,
                        "work_details": submission.work_details,
                        "completion_notes": submission.completion_notes,
                        "before_evidence": submission.before_evidence,
                        "after_evidence": submission.after_evidence,
                        "latitude": submission.latitude,
                        "longitude": submission.longitude,
                        "captured_at": submission.captured_at.isoformat(),
                        "location_accuracy_meters": (
                            location_evidence.accuracy_meters
                            if location_evidence is not None
                            else None
                        ),
                        "location_captured_at": (
                            location_evidence.captured_at.isoformat()
                            if location_evidence is not None
                            else None
                        ),
                        "distance_from_complaint_meters": round(distance_meters, 1),
                        "distance_review_flag": (
                            distance_meters
                            > WORK_LOCATION_DISTANCE_REVIEW_THRESHOLD_METERS
                        ),
                        "attempt_number": submission.attempt_number,
                    },
                }
            )
    return queue


@app.post("/api/verification/{submission_id}/decision")
def decide_verification(
    submission_id: str,
    payload: VerificationDecisionRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("verifier")),
) -> dict[str, str]:
    if payload.decision not in {"APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Decision must be APPROVED or REJECTED.")
    submission = db.get(WorkSubmission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Work submission not found.")
    complaint = complaint_or_404(db, submission.complaint_id)
    if complaint.verifier_id != user.id:
        raise HTTPException(status_code=403, detail="Only the designated verifier can decide this submission.")
    if user.id == submission.engineer_id:
        raise HTTPException(status_code=403, detail="An engineer cannot verify their own work.")
    if complaint.verification_status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="This submission is no longer awaiting review.")

    db.add(
        VerificationReview(
            id=str(uuid.uuid4()),
            submission_id=submission.id,
            complaint_id=complaint.id,
            officer_id=user.id,
            decision=payload.decision,
            reason=payload.reason,
        )
    )
    db.add(
        WorkUpdate(
            id=str(uuid.uuid4()),
            complaint_id=complaint.id,
            actor_id=user.id,
            event_type=f"VERIFICATION_{payload.decision}",
            note=payload.reason,
        )
    )
    if payload.decision == "APPROVED":
        complaint.verification_status = "APPROVED"
        complaint.engineer_work_status = "WORK_DONE"
        complaint.official_status = "OFFICIALLY_COMPLETED"
    else:
        complaint.verification_status = "REWORK_REQUIRED"
        complaint.engineer_work_status = "REWORK_IN_PROGRESS"
        complaint.official_status = "IN_PROGRESS"
    db.commit()
    return {
        "complaint_id": complaint.id,
        "decision": payload.decision,
        "official_status": complaint.official_status,
        "engineer_work_status": complaint.engineer_work_status,
        "verification_status": complaint.verification_status,
    }


@app.get("/api/assistant/documents")
def list_documents() -> list[dict[str, str]]:
    try:
        from app.rag import list_approved_documents

        return list_approved_documents()
    except Exception as error:
        logger.error("Scheme document lookup failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="The approved document library is unavailable. Try again shortly.",
        ) from error


@app.post(
    "/api/assistant/documents",
    status_code=201,
    dependencies=[Depends(require_role("officer"))],
)
async def upload_scheme_document(
    title: str = Form(min_length=1, max_length=180),
    source_url: str = Form(default="", max_length=2048),
    version: str = Form(default="1.0", max_length=80),
    file: UploadFile = File(...),
) -> dict:
    if file.content_type not in {"application/pdf", "text/plain"}:
        raise HTTPException(status_code=415, detail="Upload a PDF or plain-text scheme document.")
    contents = await file.read(MAX_SCHEME_UPLOAD_BYTES + 1)
    await file.close()
    if len(contents) > MAX_SCHEME_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Scheme documents must be smaller than 10 MB.")
    if not title.strip() or len(title) > 180 or len(version) > 80:
        raise HTTPException(status_code=422, detail="Document title or version is invalid.")
    if source_url:
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc or parsed_url.username:
            raise HTTPException(status_code=422, detail="Source URL must be a valid HTTP(S) URL.")
    try:
        if file.content_type == "application/pdf":
            if not contents.startswith(b"%PDF-"):
                raise HTTPException(status_code=415, detail="The uploaded file is not a valid PDF.")
            reader = PdfReader(io.BytesIO(contents))
            if reader.is_encrypted:
                raise HTTPException(status_code=422, detail="Encrypted PDFs are not supported.")
            if len(reader.pages) > MAX_SCHEME_PAGES:
                raise HTTPException(status_code=413, detail="PDFs may contain at most 250 pages.")
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n\n".join(
                f"[Page {index + 1}] {page_text}" for index, page_text in enumerate(pages)
            ).strip()
        else:
            text = contents.decode("utf-8").strip()
    except HTTPException:
        raise
    except Exception as error:
        logger.warning("Could not extract scheme document text: %s", type(error).__name__)
        raise HTTPException(status_code=422, detail="Could not read the uploaded document.") from error
    if not text:
        raise HTTPException(status_code=422, detail="No readable text was found in the document.")
    if len(text) > MAX_EXTRACTED_CHARACTERS:
        raise HTTPException(status_code=413, detail="Extracted document text exceeds the supported size.")
    source_id = hashlib.sha256(contents).hexdigest()
    try:
        chunk_count = ingest_approved_document(text, title, source_url, version, source_id)
    except Exception as error:
        logger.error("Scheme document indexing failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="Document indexing is unavailable. Check the local AI service and try again.",
        ) from error
    return {"title": title, "version": version, "chunks_indexed": chunk_count}


@app.post("/api/assistant/chat", dependencies=[Depends(get_current_user)])
def chat(
    payload: ChatRequest,
) -> dict:
    try:
        answer, sources = ask_assistant(payload.question, payload.language)
    except Exception as error:
        logger.error("Scheme assistant request failed: %s", type(error).__name__)
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again later.",
        ) from error
    return {
        "answer": answer,
        "sources": sources,
        "language": payload.language,
        "guidance_only": True,
    }
