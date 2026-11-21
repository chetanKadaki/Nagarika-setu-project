import base64
import binascii
import re
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_EVIDENCE_IMAGE_BYTES = 900 * 1024


def normalize_email_address(value: str) -> str:
    normalized = value.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=180)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email_address(value)


class GoogleLoginRequest(BaseModel):
    credential: str = Field(min_length=100, max_length=8192)

    @field_validator("credential")
    @classmethod
    def normalize_credential(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("A Google credential is required.")
        return normalized


class CitizenRegistrationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=180)
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)
    phone_number: str = Field(min_length=7, max_length=24)
    terms_accepted: bool

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Enter your full name.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email_address(value)

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        normalized = re.sub(r"[ .()-]", "", value.strip())
        if not re.fullmatch(r"\+?[0-9]{7,20}", normalized):
            raise ValueError("Enter a valid phone number.")
        return normalized

    @model_validator(mode="after")
    def validate_registration(self) -> "CitizenRegistrationRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        if not self.terms_accepted:
            raise ValueError("Accept the terms and conditions to register.")
        return self


class ComplaintCreate(BaseModel):
    title: str = Field(min_length=8, max_length=180)
    description: str = Field(min_length=12, max_length=4000)
    category: Literal[
        "Roads & pavements",
        "Water & drainage",
        "Street lighting",
        "Waste management",
        "Pollution & environment",
    ]
    severity: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    address: str = Field(min_length=4, max_length=240)
    ward: str = Field(min_length=2, max_length=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_accuracy_meters: float | None = Field(default=None, ge=0, le=100000)
    location_captured_at: datetime | None = None

    @model_validator(mode="after")
    def validate_location_evidence(self) -> "ComplaintCreate":
        if (self.location_accuracy_meters is None) != (self.location_captured_at is None):
            raise ValueError("Provide both GPS accuracy and capture time, or neither.")
        return self


class AssignmentRequest(BaseModel):
    engineer_id: str
    verifier_id: str


class EngineerRegistrationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=180)
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)
    phone_number: str = Field(min_length=7, max_length=24)
    terms_accepted: bool
    department: str = Field(min_length=2, max_length=100)
    registration_number: str = Field(min_length=2, max_length=100)
    skills: list[str] = Field(min_length=1, max_length=20)
    application_note: str = Field(min_length=10, max_length=2000)

    @field_validator("name", "department", "application_note")
    @classmethod
    def normalize_application_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        minimum = 10 if info.field_name == "application_note" else 2
        if len(normalized) < minimum:
            raise ValueError("Provide the required application details.")
        return normalized

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) < 2:
            raise ValueError("Enter a valid professional registration number.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email_address(value)

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        normalized = re.sub(r"[ .()-]", "", value.strip())
        if not re.fullmatch(r"\+?[0-9]{7,20}", normalized):
            raise ValueError("Enter a valid phone number.")
        return normalized

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(skill.strip() for skill in values if skill.strip()))
        if not normalized:
            raise ValueError("Add at least one engineering skill.")
        if any(len(skill) > 80 for skill in normalized):
            raise ValueError("Each engineering skill must be 80 characters or fewer.")
        return normalized

    @model_validator(mode="after")
    def validate_registration(self) -> "EngineerRegistrationRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        if not self.terms_accepted:
            raise ValueError("Accept the terms and conditions to apply.")
        return self


class EngineerRegistrationUpdateRequest(BaseModel):
    department: str = Field(min_length=2, max_length=100)
    registration_number: str = Field(min_length=2, max_length=100)
    skills: list[str] = Field(min_length=1, max_length=20)
    application_note: str = Field(min_length=10, max_length=2000)

    @field_validator("department", "application_note")
    @classmethod
    def normalize_application_text(cls, value: str, info: ValidationInfo) -> str:
        normalized = value.strip()
        minimum = 10 if info.field_name == "application_note" else 2
        if len(normalized) < minimum:
            raise ValueError("Provide the required application details.")
        return normalized

    @field_validator("registration_number")
    @classmethod
    def normalize_registration_number(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) < 2:
            raise ValueError("Enter a valid professional registration number.")
        return normalized

    @field_validator("skills")
    @classmethod
    def normalize_skills(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(skill.strip() for skill in values if skill.strip()))
        if not normalized:
            raise ValueError("Add at least one engineering skill.")
        if any(len(skill) > 80 for skill in normalized):
            raise ValueError("Each engineering skill must be 80 characters or fewer.")
        return normalized


class EngineerRegistrationDecisionRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(min_length=8, max_length=2000)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("Provide a review reason of at least 8 characters.")
        return normalized


class WorkUpdateRequest(BaseModel):
    note: str = Field(min_length=5, max_length=2000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5:
            raise ValueError("Provide a work update of at least 5 characters.")
        return normalized

    @model_validator(mode="after")
    def validate_coordinates(self) -> "WorkUpdateRequest":
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Provide both latitude and longitude, or neither.")
        return self


class LiveWorkLocationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class SchemeTaskCreate(BaseModel):
    scheme_title: Literal[
        "Pradhan Mantri Awas Yojana – Urban 2.0",
        "PM Street Vendor’s AtmaNirbhar Nidhi",
        "Swachh Bharat Mission – Urban",
        "Ayushman Bharat PM-JAY",
    ]
    title: str = Field(min_length=5, max_length=180)
    description: str = Field(min_length=10, max_length=2000)
    department: str = Field(min_length=2, max_length=100)
    required_skills: list[str] = Field(min_length=1, max_length=20)
    engineer_id: str = Field(min_length=1, max_length=40)

    @field_validator("scheme_title", "title", "description", "department")
    @classmethod
    def normalize_task_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("This field cannot be blank.")
        return normalized

    @field_validator("required_skills")
    @classmethod
    def normalize_required_skills(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(skill.strip() for skill in values if skill.strip()))
        if not normalized:
            raise ValueError("Add at least one required engineer skill.")
        if any(len(skill) > 80 for skill in normalized):
            raise ValueError("Each required skill must be 80 characters or fewer.")
        return normalized


class SchemeTaskProgressRequest(BaseModel):
    note: str = Field(min_length=5, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_progress_note(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5:
            raise ValueError("Provide a progress update of at least 5 characters.")
        return normalized


class SchemeTaskCompletionRequest(BaseModel):
    note: str = Field(min_length=10, max_length=2000)

    @field_validator("note")
    @classmethod
    def normalize_completion_note(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("Provide a completion note of at least 10 characters.")
        return normalized


class WorkSubmissionRequest(BaseModel):
    work_details: str = Field(min_length=10, max_length=4000)
    completion_notes: str = Field(min_length=10, max_length=2000)
    before_evidence: str = Field(min_length=1, max_length=1_500_000)
    after_evidence: str = Field(min_length=1, max_length=1_500_000)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    captured_at: datetime
    location_accuracy_meters: float | None = Field(default=None, ge=0, le=100000)
    location_captured_at: datetime | None = None

    @model_validator(mode="after")
    def validate_location_evidence(self) -> "WorkSubmissionRequest":
        if (self.location_accuracy_meters is None) != (self.location_captured_at is None):
            raise ValueError("Provide both GPS accuracy and capture time, or neither.")
        return self

    @field_validator("before_evidence", "after_evidence")
    @classmethod
    def validate_evidence(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Provide an evidence reference or photo.")
        if not normalized.startswith("data:"):
            if len(normalized) > 400:
                raise ValueError("Evidence references must be 400 characters or fewer.")
            return normalized
        prefix = "data:image/jpeg;base64,"
        if not normalized.startswith(prefix):
            raise ValueError("Evidence images must be JPEG data URLs.")
        try:
            image_bytes = base64.b64decode(normalized[len(prefix):], validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Evidence image data is invalid.") from None
        if (
            len(image_bytes) > MAX_EVIDENCE_IMAGE_BYTES
            or not image_bytes.startswith(b"\xff\xd8\xff")
        ):
            raise ValueError("Evidence must be a valid JPEG image no larger than 900 KB.")
        return normalized


class VerificationDecisionRequest(BaseModel):
    decision: str
    reason: str = Field(min_length=8, max_length=2000)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("Provide a review reason of at least 8 characters.")
        return normalized


class ComplaintAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    suggested_category: str
    suggested_severity: str
    suggested_department: str
    summary: str
    rationale: str
    confidence: float
    duplicate_references: list[str]
    rules_version: str
    created_at: datetime


class AssignedEngineerResponse(BaseModel):
    id: str
    name: str
    department: str
    registration_number: str
    skills: list[str]


class ComplaintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference: str
    title: str
    description: str
    category: str
    severity: str
    official_status: str
    engineer_work_status: str
    verification_status: str
    ward: str
    address: str
    latitude: float
    longitude: float
    location_accuracy_meters: float | None = None
    location_captured_at: datetime | None = None
    department: str
    engineer_id: str | None
    verifier_id: str | None
    is_demo: bool
    created_at: datetime
    assessment: ComplaintAssessmentResponse | None = None
    assigned_engineer: AssignedEngineerResponse | None = None


class ComplaintAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_name: str
    content_type: str
    size_bytes: int
    uploaded_at: datetime


class ComplaintFeedbackCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        return value.strip()


class ComplaintFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: int
    comment: str
    submitted_at: datetime


class ComplaintTriageDecisionRequest(BaseModel):
    category: Literal[
        "Roads & pavements",
        "Water & drainage",
        "Street lighting",
        "Waste management",
        "Pollution & environment",
    ]
    severity: Literal["Critical", "High", "Medium", "Low"]
    reason: str = Field(min_length=8, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_review_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 8:
            raise ValueError("Provide a triage review reason of at least 8 characters.")
        return normalized


class PublicComplaintResponse(BaseModel):
    reference: str
    title: str
    category: str
    severity: str
    official_status: str
    engineer_work_status: str
    verification_status: str
    ward: str
    latitude: float
    longitude: float
    department: str
    created_at: datetime


class PublicDashboardResponse(BaseModel):
    counts: dict[str, int]
    by_category: dict[str, int]
    complaints: list[PublicComplaintResponse]


class ChatRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    language: str = "English"


class EmailAddressRequest(BaseModel):
    email: str = Field(min_length=6, max_length=180)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email_address(value)


class OneTimeTokenRequest(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class PasswordResetRequest(OneTimeTokenRequest):
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(min_length=12, max_length=128)

    @model_validator(mode="after")
    def passwords_match(self) -> "PasswordResetRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class InvitationAcceptRequest(PasswordResetRequest):
    phone_number: str = Field(min_length=7, max_length=24)
    terms_accepted: bool

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        normalized = re.sub(r"[ .()-]", "", value.strip())
        if not re.fullmatch(r"\+?[0-9]{7,20}", normalized):
            raise ValueError("Enter a valid phone number.")
        return normalized

    @model_validator(mode="after")
    def accepts_terms(self) -> "InvitationAcceptRequest":
        if not self.terms_accepted:
            raise ValueError("Accept the terms and conditions to activate this account.")
        return self


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    phone_number: str = Field(min_length=7, max_length=24)
    address: str = Field(default="", max_length=240)
    ward: str = Field(default="", max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Enter your full name.")
        return normalized

    @field_validator("phone_number")
    @classmethod
    def normalize_phone_number(cls, value: str) -> str:
        normalized = re.sub(r"[ .()-]", "", value.strip())
        if not re.fullmatch(r"\+?[0-9]{7,20}", normalized):
            raise ValueError("Enter a valid phone number.")
        return normalized

    @field_validator("address", "ward")
    @classmethod
    def normalize_optional_location(cls, value: str) -> str:
        return value.strip()


class OfficialInvitationRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=6, max_length=180)
    role: Literal["officer", "verifier"]
    employee_id: str = Field(min_length=2, max_length=100)
    designation: str = Field(min_length=2, max_length=120)
    department: str = Field(min_length=2, max_length=100)
    jurisdiction: str = Field(min_length=2, max_length=180)

    @field_validator("name", "employee_id", "designation", "department", "jurisdiction")
    @classmethod
    def normalize_official_fields(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Provide the required official details.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email_address(value)


class AccountStatusRequest(BaseModel):
    active: bool
