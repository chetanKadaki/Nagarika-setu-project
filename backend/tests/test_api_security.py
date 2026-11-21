from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

import app.main as main_module
from app.models import (
    AuthSession,
    CitizenProfile,
    Complaint,
    EmailVerificationToken,
    LoginAuditLog,
    OfficerProfile,
    User,
    UserAuthentication,
    VerificationReview,
    WorkSubmission,
)


def test_private_endpoints_require_a_valid_bearer_token(api):
    client, _, _ = api

    assert client.get("/api/complaints").status_code == 401
    assert client.get(
        "/api/complaints", headers={"Authorization": "Bearer invalid.token"}
    ).status_code == 401


def test_approved_scheme_documents_are_public(api, monkeypatch):
    client, _, _ = api
    documents = [{"title": "Public housing scheme", "source_url": "https://example.test", "version": "2"}]
    monkeypatch.setattr("app.rag.list_approved_documents", lambda: documents)

    response = client.get("/api/assistant/documents")

    assert response.status_code == 200
    assert response.json() == documents


def test_api_responses_include_security_headers(api):
    client, _, _ = api
    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_upload_requires_officer_role_and_valid_pdf_signature(api, auth_headers):
    client, _, _ = api
    path = "/api/assistant/documents"
    citizen_response = client.post(
        path,
        headers=auth_headers["citizen"],
        data={"title": "Scheme notice", "version": "1.0"},
        files={"file": ("notice.pdf", b"%PDF-not-a-real-document", "application/pdf")},
    )
    invalid_pdf_response = client.post(
        path,
        headers=auth_headers["officer"],
        data={"title": "Scheme notice", "version": "1.0"},
        files={"file": ("notice.pdf", b"not a PDF", "application/pdf")},
    )

    assert citizen_response.status_code == 403
    assert invalid_pdf_response.status_code == 415


def test_upload_rejects_oversized_documents_before_indexing(api, auth_headers):
    client, _, _ = api
    response = client.post(
        "/api/assistant/documents",
        headers=auth_headers["officer"],
        data={"title": "Scheme notice", "version": "1.0"},
        files={
            "file": (
                "notice.txt",
                b"x" * (10 * 1024 * 1024 + 1),
                "text/plain",
            )
        },
    )

    assert response.status_code == 413


def test_upload_does_not_disclose_internal_ai_errors(api, auth_headers, monkeypatch):
    client, _, _ = api

    def fail_indexing(content: str, title: str, source_url: str, version: str, source_id: str):
        assert content and title and isinstance(source_url, str) and version and source_id
        raise RuntimeError("private provider details")

    monkeypatch.setattr(main_module, "ingest_approved_document", fail_indexing)
    response = client.post(
        "/api/assistant/documents",
        headers=auth_headers["officer"],
        data={"title": "Scheme notice", "version": "1.0"},
        files={"file": ("notice.txt", b"Approved scheme guidelines.", "text/plain")},
    )

    assert response.status_code == 503
    assert "private provider details" not in response.text


def test_assistant_does_not_disclose_internal_model_errors(api, auth_headers, monkeypatch):
    client, _, _ = api

    def fail_assistant(question: str, language: str):
        assert question and language
        raise RuntimeError("private model details")

    monkeypatch.setattr(main_module, "ask_assistant", fail_assistant)
    response = client.post(
        "/api/assistant/chat",
        headers=auth_headers["citizen"],
        json={"question": "How do I find the latest scheme guidance?"},
    )

    assert response.status_code == 503
    assert "private model details" not in response.text


def test_login_uses_same_error_for_unknown_user_and_wrong_password(api):
    client, _, _ = api
    unknown = client.post(
        "/api/auth/login",
        json={"email": "missing@example.test", "password": "valid-long-test-password"},
    )
    wrong_password = client.post(
        "/api/auth/login",
        json={"email": "citizen@example.test", "password": "valid-long-test-password"},
    )

    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


def test_login_normalizes_email_and_rejects_malformed_addresses(api):
    client, _, _ = api
    normalized = client.post(
        "/api/auth/login",
        json={"email": "  CITIZEN@example.test  ", "password": "citizen-test-password"},
    )
    malformed = client.post(
        "/api/auth/login",
        json={"email": "not-an-email", "password": "valid-long-test-password"},
    )

    assert normalized.status_code == 200
    assert malformed.status_code == 422


def test_google_login_requires_server_configuration(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(main_module.settings, "google_client_id", "")
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda *_: pytest.fail("Google credentials must not be checked when sign-in is disabled"),
    )

    response = client.post("/api/auth/google", json={"credential": "x" * 100})

    assert response.status_code == 503


def test_google_login_rejects_unverified_email(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(main_module.settings, "google_client_id", "test-google-client-id")
    monkeypatch.setattr(
        main_module,
        "verify_google_id_token",
        lambda *_: {
            "email": "new-citizen@example.test",
            "email_verified": False,
        },
    )

    response = client.post("/api/auth/google", json={"credential": "x" * 100})

    assert response.status_code == 401


def test_google_login_provisions_citizen_and_preserves_existing_role(api, monkeypatch):
    client, test_session, _ = api
    monkeypatch.setattr(main_module.settings, "google_client_id", "test-google-client-id")
    new_credential = "n" * 100
    engineer_credential = "e" * 100
    claims_by_credential = {
        new_credential: {
            "email": "  New-Citizen@example.test ",
            "email_verified": True,
            "name": "New Google Citizen",
        },
        engineer_credential: {
            "email": "ENGINEER@example.test",
            "email_verified": True,
            "name": "Changed Display Name",
        },
    }

    def verify_credential(credential, client_id):
        assert client_id == "test-google-client-id"
        return claims_by_credential[credential]

    monkeypatch.setattr(main_module, "verify_google_id_token", verify_credential)

    created = client.post("/api/auth/google", json={"credential": new_credential})
    existing = client.post("/api/auth/google", json={"credential": engineer_credential})
    repeated = client.post("/api/auth/google", json={"credential": new_credential})

    assert created.status_code == existing.status_code == repeated.status_code == 200
    assert created.json()["user"]["role"] == "citizen"
    assert created.json()["user"]["name"] == "New Google Citizen"
    assert existing.json()["user"]["role"] == "engineer"
    assert existing.json()["user"]["name"] == "Test Engineer"
    assert repeated.json()["user"]["id"] == created.json()["user"]["id"]
    with test_session() as db:
        assert db.scalar(select(User).where(User.email == "new-citizen@example.test")) is not None


def test_new_citizen_must_verify_email_before_signing_in(api, auth_mailbox):
    client, _, _ = api
    registration = {
        "name": "  New Citizen  ",
        "email": "  New.Citizen@example.test  ",
        "password": "a-unique-civicai-password",
        "confirm_password": "a-unique-civicai-password",
        "phone_number": "+1 (555) 010-2030",
        "terms_accepted": True,
    }

    created = client.post("/api/auth/register", json=registration)
    duplicate = client.post("/api/auth/register", json=registration)
    unverified_login = client.post(
        "/api/auth/login",
        json={
            "email": "new.citizen@example.test",
            "password": "a-unique-civicai-password",
        },
    )
    verification = client.post(
        "/api/auth/verify-email",
        json={"token": auth_mailbox[("verification", "new.citizen@example.test")]},
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "new.citizen@example.test", "password": "a-unique-civicai-password"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "verification_required"
    assert duplicate.status_code == 409
    assert unverified_login.status_code == 403
    assert verification.status_code == 200
    assert login.status_code == 200
    assert login.json()["user"]["email"] == "new.citizen@example.test"
    assert client.get(
        "/api/complaints",
        headers={"Authorization": f"Bearer {login.json()['access_token']}"},
    ).status_code == 200


def test_citizen_registration_requires_valid_email_and_strong_password(api):
    client, _, _ = api
    registration = {
        "name": "New Citizen",
        "password": "a-unique-civicai-password",
        "confirm_password": "a-unique-civicai-password",
        "phone_number": "+15550102030",
        "terms_accepted": True,
    }

    invalid_email = client.post(
        "/api/auth/register",
        json={**registration, "email": "not-an-email"},
    )
    weak_password = client.post(
        "/api/auth/register",
        json={
            **registration,
            "email": "new@example.test",
            "password": "short",
            "confirm_password": "short",
        },
    )

    assert invalid_email.status_code == 422
    assert weak_password.status_code == 422


def test_email_verification_token_expiry_is_enforced(api, auth_mailbox):
    client, test_session, _ = api
    response = client.post(
        "/api/auth/register",
        json={
            "name": "Expired Token",
            "email": "expired@example.test",
            "password": "valid-expiry-password",
            "confirm_password": "valid-expiry-password",
            "phone_number": "+15550102030",
            "terms_accepted": True,
        },
    )
    token = auth_mailbox[("verification", "expired@example.test")]
    with test_session() as db:
        token_record = db.get(EmailVerificationToken, main_module.token_digest(token))
        token_record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    expired = client.post("/api/auth/verify-email", json={"token": token})

    assert response.status_code == 201
    assert expired.status_code == 400


def test_password_reset_revokes_existing_sessions(api, auth_mailbox):
    client, test_session, _ = api
    registration = {
        "name": "Reset Citizen",
        "email": "reset@example.test",
        "password": "old-secure-password-123",
        "confirm_password": "old-secure-password-123",
        "phone_number": "+15550102030",
        "terms_accepted": True,
    }
    client.post("/api/auth/register", json=registration)
    client.post(
        "/api/auth/verify-email",
        json={"token": auth_mailbox[("verification", "reset@example.test")]},
    )
    first_login = client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": registration["password"]},
    )
    reset_requested = client.post(
        "/api/auth/forgot-password",
        json={"email": "reset@example.test"},
    )
    token = auth_mailbox[("reset", "reset@example.test")]
    changed = client.post(
        "/api/auth/reset-password",
        json={
            "token": token,
            "password": "new-secure-password-456",
            "confirm_password": "new-secure-password-456",
        },
    )
    repeated = client.post(
        "/api/auth/reset-password",
        json={
            "token": token,
            "password": "another-secure-password",
            "confirm_password": "another-secure-password",
        },
    )
    old_session = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {first_login.json()['access_token']}"},
    )
    new_login = client.post(
        "/api/auth/login",
        json={"email": "reset@example.test", "password": "new-secure-password-456"},
    )

    assert reset_requested.status_code == 202
    assert changed.status_code == 200
    assert repeated.status_code == 400
    assert old_session.status_code == 401
    assert new_login.status_code == 200
    with test_session() as db:
        assert db.scalar(select(AuthSession).where(AuthSession.user_id == new_login.json()["user"]["id"])) is not None


def test_logout_revokes_the_current_session(api):
    client, test_session, _ = api
    login = client.post(
        "/api/auth/login",
        json={"email": "citizen@example.test", "password": "citizen-test-password"},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.post("/api/auth/logout", headers=headers)
    current_user = client.get("/api/auth/me", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"status": "signed_out"}
    assert current_user.status_code == 401
    with test_session() as db:
        assert db.scalar(
            select(func.count(LoginAuditLog.id)).where(LoginAuditLog.email == "citizen@example.test")
        ) == 1


def test_official_account_requires_admin_invitation_and_is_role_scoped(api, auth_headers, auth_mailbox):
    client, test_session, _ = api
    invitation_data = {
        "name": "Invited Officer",
        "email": "invited-officer@example.test",
        "role": "verifier",
        "employee_id": "OFF-2026-01",
        "designation": "Verification Officer",
        "department": "Public Works",
        "jurisdiction": "Ward 1",
    }
    forbidden = client.post(
        "/api/admin/invitations",
        headers=auth_headers["citizen"],
        json=invitation_data,
    )
    invited = client.post(
        "/api/admin/invitations",
        headers=auth_headers["admin"],
        json=invitation_data,
    )
    token = auth_mailbox[("invitation", invitation_data["email"])]
    accepted = client.post(
        "/api/auth/accept-invitation",
        json={
            "token": token,
            "password": "invited-officer-password",
            "confirm_password": "invited-officer-password",
            "phone_number": "+15550102030",
            "terms_accepted": True,
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": invitation_data["email"], "password": "invited-officer-password"},
    )

    assert forbidden.status_code == 403
    assert invited.status_code == 201
    assert accepted.status_code == 200
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "verifier"
    with test_session() as db:
        official = db.scalar(select(User).where(User.email == invitation_data["email"]))
        assert official is not None
        assert db.get(OfficerProfile, official.id).employee_id == invitation_data["employee_id"]
        assert db.get(UserAuthentication, official.id).email_verified is True
        assert db.get(CitizenProfile, official.id) is None


def test_admin_can_deactivate_accounts_and_cannot_deactivate_self(api, auth_headers):
    client, _, users = api

    self_deactivation = client.patch(
        f"/api/admin/users/{users['admin'].id}/status",
        headers=auth_headers["admin"],
        json={"active": False},
    )
    deactivation = client.patch(
        f"/api/admin/users/{users['citizen'].id}/status",
        headers=auth_headers["admin"],
        json={"active": False},
    )
    blocked_login = client.post(
        "/api/auth/login",
        json={"email": "citizen@example.test", "password": "citizen-test-password"},
    )

    assert self_deactivation.status_code == 409
    assert deactivation.status_code == 200
    assert blocked_login.status_code == 403


def test_login_rate_limit_blocks_repeated_bad_passwords(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(main_module, "verify_password", lambda *_: False)

    responses = [
        client.post(
            "/api/auth/login",
            json={"email": "citizen@example.test", "password": "wrong-password"},
        )
        for _ in range(10)
    ]
    blocked = client.post(
        "/api/auth/login",
        json={"email": "citizen@example.test", "password": "wrong-password"},
    )

    assert all(response.status_code == 401 for response in responses)
    assert blocked.status_code == 429


def test_profile_updates_are_limited_to_citizen_personal_fields(api, auth_headers):
    client, test_session, users = api
    citizen_profile = client.get("/api/profile", headers=auth_headers["citizen"])
    updated = client.put(
        "/api/profile",
        headers=auth_headers["citizen"],
        json={
            "name": "Updated Citizen",
            "phone_number": "+15550102030",
            "address": "12 Example Road",
            "ward": "Ward 4",
        },
    )
    official_update = client.put(
        "/api/profile",
        headers=auth_headers["officer"],
        json={"name": "Changed Officer", "phone_number": "+15550102031"},
    )

    assert citizen_profile.status_code == 200
    assert citizen_profile.json()["email"] == "citizen@example.test"
    assert updated.status_code == 200
    assert official_update.status_code == 403
    with test_session() as db:
        citizen = db.get(User, users["citizen"].id)
        assert citizen.name == "Updated Citizen"
        profile = db.get(CitizenProfile, citizen.id)
        assert profile.phone_number == "+15550102030"
        assert profile.address == "12 Example Road"
        assert profile.ward == "Ward 4"


def test_citizens_cannot_read_other_citizens_complaints(api, auth_headers, assigned_complaint):
    client, _, _ = api
    response = client.get(
        f"/api/complaints/{assigned_complaint}",
        headers=auth_headers["citizen"],
    )

    assert response.status_code == 404


def test_citizens_can_read_their_own_complaints(api, auth_headers):
    client, test_session, users = api
    complaint = Complaint(
        id="citizen-owned",
        reference="CP-9003",
        title="Broken street light",
        description="The street light is not working.",
        category="Street lighting",
        severity="Medium",
        official_status="SUBMITTED",
        engineer_work_status="NOT_STARTED",
        verification_status="NOT_SUBMITTED",
        ward="Ward 1",
        address="Test Main Road, Bengaluru",
        latitude=12.9717,
        longitude=77.6406,
        department="Electrical",
        citizen_id=users["citizen"].id,
    )
    with test_session() as db:
        db.add(complaint)
        db.commit()
    response = client.get(
        "/api/complaints/citizen-owned",
        headers=auth_headers["citizen"],
    )

    assert response.status_code == 200
    assert response.json()["id"] == "citizen-owned"


def test_only_officers_can_assign_complaints(api, auth_headers, assigned_complaint):
    client, _, users = api
    response = client.post(
        f"/api/complaints/{assigned_complaint}/assign",
        headers=auth_headers["engineer"],
        json={
            "engineer_id": users["engineer"].id,
            "verifier_id": users["verifier"].id,
        },
    )

    assert response.status_code == 403


def test_assignment_requires_a_designated_verifier(api, auth_headers, assigned_complaint):
    client, _, users = api
    response = client.post(
        f"/api/complaints/{assigned_complaint}/assign",
        headers=auth_headers["officer"],
        json={
            "engineer_id": users["engineer"].id,
            "verifier_id": users["engineer"].id,
        },
    )

    assert response.status_code == 422


def test_work_submission_requires_a_designated_verifier(api, auth_headers, work_payload):
    client, test_session, users = api
    complaint = Complaint(
        id="unassigned-verifier",
        reference="CP-9002",
        title="Pothole needs repair",
        description="A deep pothole blocks the crossing.",
        category="Roads & pavements",
        severity="High",
        official_status="ASSIGNED",
        engineer_work_status="IN_PROGRESS",
        verification_status="NOT_SUBMITTED",
        ward="Ward 1",
        address="Test Main Road, Bengaluru",
        latitude=12.9717,
        longitude=77.6406,
        department="Public Works",
        citizen_id=users["citizen"].id,
        engineer_id=users["engineer"].id,
    )
    with test_session() as db:
        db.add(complaint)
        db.commit()

    response = client.post(
        "/api/complaints/unassigned-verifier/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )

    assert response.status_code == 409


def test_only_the_designated_verifier_can_review_work(
    api, auth_headers, assigned_complaint, work_payload
):
    client, _, _ = api
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    assert submitted.status_code == 200
    submission_id = submitted.json()["submission_id"]

    response = client.post(
        f"/api/verification/{submission_id}/decision",
        headers=auth_headers["other_verifier"],
        json={"decision": "APPROVED", "reason": "The work looks complete."},
    )

    assert response.status_code == 403


def test_engineer_cannot_approve_work(api, auth_headers, assigned_complaint, work_payload):
    client, _, _ = api
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )

    response = client.post(
        f"/api/verification/{submitted.json()['submission_id']}/decision",
        headers=auth_headers["engineer"],
        json={"decision": "APPROVED", "reason": "The work looks complete."},
    )

    assert response.status_code == 403


def test_rejection_requires_a_reason_and_preserves_history(
    api, auth_headers, assigned_complaint, work_payload
):
    client, test_session, _ = api
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    submission_id = submitted.json()["submission_id"]
    rejected = client.post(
        f"/api/verification/{submission_id}/decision",
        headers=auth_headers["verifier"],
        json={"decision": "REJECTED", "reason": "Photo evidence is not clear."},
    )

    assert rejected.status_code == 200
    assert rejected.json()["official_status"] == "IN_PROGRESS"
    started = client.post(
        f"/api/complaints/{assigned_complaint}/work/start",
        headers=auth_headers["engineer"],
        json={"note": "The requested repair work has resumed."},
    )
    assert started.status_code == 200
    rework = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    assert rework.status_code == 200
    with test_session() as db:
        assert db.scalar(
            select(func.count()).select_from(WorkSubmission).where(
                WorkSubmission.complaint_id == assigned_complaint
            )
        ) == 2
        assert db.scalar(
            select(func.count()).select_from(VerificationReview).where(
                VerificationReview.complaint_id == assigned_complaint
            )
        ) == 1


def test_officer_approval_is_required_before_official_completion(
    api, auth_headers, assigned_complaint, work_payload
):
    client, test_session, _ = api
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    decision = client.post(
        f"/api/verification/{submitted.json()['submission_id']}/decision",
        headers=auth_headers["verifier"],
        json={"decision": "APPROVED", "reason": "Evidence matches the completed repair."},
    )

    assert decision.status_code == 200
    assert decision.json()["official_status"] == "OFFICIALLY_COMPLETED"
    with test_session() as db:
        complaint = db.get(Complaint, assigned_complaint)
        assert complaint is not None
        assert complaint.verification_status == "APPROVED"
        assert complaint.official_status == "OFFICIALLY_COMPLETED"


def test_verification_decision_requires_a_nonempty_reason(
    api, auth_headers, assigned_complaint, work_payload
):
    client, _, _ = api
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    response = client.post(
        f"/api/verification/{submitted.json()['submission_id']}/decision",
        headers=auth_headers["verifier"],
        json={"decision": "APPROVED", "reason": ""},
    )

    assert response.status_code == 422


def test_engineer_cannot_submit_for_another_engineers_complaint(
    api, auth_headers, assigned_complaint, work_payload
):
    client, _, _ = api
    response = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["citizen"],
        json=work_payload,
    )

    assert response.status_code == 403
