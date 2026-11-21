from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('citizen', 'engineer_pending', 'engineer', 'verifier', 'officer', 'admin')",
            name="ck_users_role",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(30), index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class EngineerProfile(Base):
    __tablename__ = "engineer_profiles"
    __table_args__ = (UniqueConstraint("registration_number", name="uq_engineer_registration_number"),)

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    department: Mapped[str] = mapped_column(String(100))
    registration_number: Mapped[str] = mapped_column(String(100))
    skills: Mapped[list[str]] = mapped_column(JSON)
    application_note: Mapped[str] = mapped_column(Text)
    registration_status: Mapped[str] = mapped_column(String(24), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class EngineerRegistrationReview(Base):
    __tablename__ = "engineer_registration_reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    officer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    reference: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(60))
    severity: Mapped[str] = mapped_column(String(20))
    official_status: Mapped[str] = mapped_column(String(40), index=True)
    engineer_work_status: Mapped[str] = mapped_column(String(40), default="NOT_STARTED")
    verification_status: Mapped[str] = mapped_column(String(40), default="NOT_SUBMITTED")
    ward: Mapped[str] = mapped_column(String(100))
    address: Mapped[str] = mapped_column(String(240))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    department: Mapped[str] = mapped_column(String(100))
    citizen_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    engineer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    verifier_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    submissions: Mapped[list["WorkSubmission"]] = relationship(
        back_populates="complaint", order_by="WorkSubmission.attempt_number"
    )


class ComplaintLocationEvidence(Base):
    __tablename__ = "complaint_location_evidence"

    complaint_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("complaints.id"), primary_key=True
    )
    accuracy_meters: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ComplaintAttachment(Base):
    __tablename__ = "complaint_attachments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), index=True)
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    original_name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(80), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ComplaintAssessment(Base):
    __tablename__ = "complaint_assessments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), unique=True, index=True)
    suggested_category: Mapped[str] = mapped_column(String(60))
    suggested_severity: Mapped[str] = mapped_column(String(20))
    suggested_department: Mapped[str] = mapped_column(String(100))
    summary: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    duplicate_references: Mapped[list[str]] = mapped_column(JSON, default=list)
    rules_version: Mapped[str] = mapped_column(String(40))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ComplaintFeedback(Base):
    __tablename__ = "complaint_feedback"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(
        ForeignKey("complaints.id"), unique=True, index=True
    )
    citizen_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ComplaintAssignment(Base):
    __tablename__ = "complaint_assignments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), index=True)
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verifier_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkUpdate(Base):
    __tablename__ = "work_updates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SchemeTask(Base):
    __tablename__ = "scheme_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    scheme_title: Mapped[str] = mapped_column(String(180), index=True)
    title: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(String(100))
    required_skills: Mapped[list[str]] = mapped_column(JSON)
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(30), default="ASSIGNED", index=True)
    progress_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SchemeTaskUpdate(Base):
    __tablename__ = "scheme_task_updates"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("scheme_tasks.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LiveWorkLocation(Base):
    __tablename__ = "live_work_locations"
    __table_args__ = (
        CheckConstraint(
            "(complaint_id IS NOT NULL AND scheme_task_id IS NULL) OR "
            "(complaint_id IS NULL AND scheme_task_id IS NOT NULL)",
            name="ck_live_work_location_one_target",
        ),
        UniqueConstraint("complaint_id", name="uq_live_location_complaint"),
        UniqueConstraint("scheme_task_id", name="uq_live_location_scheme_task"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str | None] = mapped_column(
        ForeignKey("complaints.id"), nullable=True, index=True
    )
    scheme_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("scheme_tasks.id"), nullable=True, index=True
    )
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WorkSubmission(Base):
    __tablename__ = "work_submissions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), index=True)
    engineer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    work_details: Mapped[str] = mapped_column(Text)
    completion_notes: Mapped[str] = mapped_column(Text)
    before_evidence: Mapped[str] = mapped_column(Text)
    after_evidence: Mapped[str] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempt_number: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    complaint: Mapped[Complaint] = relationship(back_populates="submissions")


class WorkSubmissionLocationEvidence(Base):
    __tablename__ = "work_submission_location_evidence"

    submission_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("work_submissions.id"), primary_key=True
    )
    accuracy_meters: Mapped[float] = mapped_column(Float)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VerificationReview(Base):
    __tablename__ = "verification_reviews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("work_submissions.id"), index=True)
    complaint_id: Mapped[str] = mapped_column(ForeignKey("complaints.id"), index=True)
    officer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UserAuthentication(Base):
    __tablename__ = "user_authentication"
    __table_args__ = (
        CheckConstraint(
            "account_status IN ('ACTIVE', 'INACTIVE')",
            name="ck_user_authentication_status",
        ),
    )

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    account_status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class UserContactProfile(Base):
    __tablename__ = "user_contact_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CitizenProfile(Base):
    __tablename__ = "citizen_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    phone_number: Mapped[str] = mapped_column(String(24))
    address: Mapped[str] = mapped_column(String(240), default="")
    ward: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OfficerProfile(Base):
    __tablename__ = "officer_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(100), unique=True)
    designation: Mapped[str] = mapped_column(String(120))
    department: Mapped[str] = mapped_column(String(100))
    jurisdiction: Mapped[str] = mapped_column(String(180))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LoginAuditLog(Base):
    __tablename__ = "login_audit_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(180), index=True)
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    user_agent: Mapped[str] = mapped_column(String(512), default="")
    succeeded: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(180), index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30))
    department: Mapped[str] = mapped_column(String(100), default="")
    employee_id: Mapped[str] = mapped_column(String(100), default="")
    designation: Mapped[str] = mapped_column(String(120), default="")
    jurisdiction: Mapped[str] = mapped_column(String(180), default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LoginAttempt(Base):
    __tablename__ = "login_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(180), index=True)
    ip_address: Mapped[str] = mapped_column(String(45), default="", index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
