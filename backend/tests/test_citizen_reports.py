import app.main as main_module
from app.models import (
    Complaint,
    ComplaintAssessment,
    ComplaintAttachment,
    ComplaintLocationEvidence,
)


PNG_CONTENT = b"\x89PNG\r\n\x1a\n" + b"test-image"
MP4_CONTENT = b"\x00\x00\x00\x18ftypisom" + b"test-video"
OGG_CONTENT = b"OggS" + b"test-audio"


def report_fields(**overrides):
    fields = {
        "title": "Large pothole near the crossing",
        "description": "A large pothole is creating a dangerous road hazard near the crossing.",
        "category": "Roads & pavements",
        "severity": "Low",
        "address": "Private address that should not be public",
        "ward": "Ward 18",
        "latitude": "12.9716",
        "longitude": "77.6136",
    }
    return {**fields, **overrides}


def test_citizen_can_submit_report_with_validated_media_and_advisory_triage(
    api, auth_headers, monkeypatch, tmp_path
):
    client, test_session, _ = api
    monkeypatch.setattr(main_module.settings, "complaint_upload_path", str(tmp_path))

    response = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(
            location_accuracy_meters="12.5",
            location_captured_at="2026-03-20T09:30:00Z",
        ),
        files=[
            ("files", ("road.png", PNG_CONTENT, "image/png")),
            ("files", ("clip.mp4", MP4_CONTENT, "video/mp4")),
            ("files", ("voice.ogg", OGG_CONTENT, "audio/ogg")),
        ],
    )

    assert response.status_code == 201
    complaint = response.json()
    assert complaint["category"] == "Roads & pavements"
    assert complaint["severity"] == "Low"
    assert complaint["assessment"]["suggested_category"] == "Roads & pavements"
    assert complaint["assessment"]["suggested_severity"] == "High"
    assert complaint["assessment"]["suggested_department"] == "Public Works"
    assert complaint["location_accuracy_meters"] == 12.5
    assert complaint["location_captured_at"].startswith("2026-03-20T09:30:00")
    assert "preliminary recommendation" in complaint["assessment"]["rationale"]
    with test_session() as db:
        attachments = db.query(ComplaintAttachment).filter_by(complaint_id=complaint["id"]).all()
        location_evidence = db.get(ComplaintLocationEvidence, complaint["id"])
        assert {item.original_name for item in attachments} == {"road.png", "clip.mp4", "voice.ogg"}
        assert all((tmp_path / item.storage_key).read_bytes() for item in attachments)
        assert location_evidence is not None
        assert location_evidence.accuracy_meters == 12.5

    metadata = client.get(
        f"/api/complaints/{complaint['id']}/attachments",
        headers=auth_headers["citizen"],
    )
    assert metadata.status_code == 200
    assert len(metadata.json()) == 3
    download = client.get(
        f"/api/complaint-attachments/{metadata.json()[0]['id']}",
        headers=auth_headers["citizen"],
    )
    assert download.status_code == 200


def test_report_requires_gps_accuracy_and_capture_time_together(api, auth_headers):
    client, _, _ = api

    response = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(location_accuracy_meters="12.5"),
    )

    assert response.status_code == 422


def test_media_upload_rejects_mismatched_signature_without_creating_report(api, auth_headers):
    client, test_session, _ = api

    response = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
        files=[("files", ("not-a-png.png", b"not an image", "image/png"))],
    )

    assert response.status_code == 415
    with test_session() as db:
        assert db.query(Complaint).count() == 0


def test_media_upload_enforces_per_file_size_limit(api, auth_headers, monkeypatch):
    client, test_session, _ = api
    monkeypatch.setattr(main_module, "MAX_COMPLAINT_ATTACHMENT_BYTES", len(PNG_CONTENT) - 1)

    response = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
        files=[("files", ("road.png", PNG_CONTENT, "image/png"))],
    )

    assert response.status_code == 413
    with test_session() as db:
        assert db.query(Complaint).count() == 0


def test_attachment_download_is_scoped_to_complaint_access(api, auth_headers, monkeypatch, tmp_path):
    client, _, _ = api
    monkeypatch.setattr(main_module.settings, "complaint_upload_path", str(tmp_path))
    created = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
        files=[("files", ("road.png", PNG_CONTENT, "image/png"))],
    )
    attachment_id = client.get(
        f"/api/complaints/{created.json()['id']}/attachments",
        headers=auth_headers["citizen"],
    ).json()[0]["id"]

    unauthorized = client.get(
        f"/api/complaint-attachments/{attachment_id}",
        headers=auth_headers["other_citizen"],
    )

    assert unauthorized.status_code == 404


def test_public_dashboard_exposes_redacted_reports_and_real_status_counts(api, auth_headers):
    client, _, _ = api
    created = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
    )
    assert created.status_code == 201

    response = client.get("/api/public/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["counts"]["total_reports"] == 1
    assert payload["counts"]["open"] == 1
    assert payload["by_category"] == {"Roads & pavements": 1}
    public_report = payload["complaints"][0]
    assert public_report["reference"] == created.json()["reference"]
    assert "citizen_id" not in public_report
    assert "address" not in public_report
    assert public_report["title"] == "Roads & pavements issue"
    assert public_report["ward"] == "Ward 18"
    assert public_report["latitude"] == 12.97
    assert public_report["longitude"] == 77.61


def test_possible_duplicate_is_flagged_but_not_merged(api, auth_headers):
    client, _, _ = api
    first = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
    )
    second = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["other_citizen"],
        data=report_fields(
            title="Large pothole beside crossing",
            description="A large pothole is a dangerous road hazard beside the crossing.",
            latitude="12.9717",
        ),
    )

    assert first.status_code == second.status_code == 201
    assert second.json()["assessment"]["duplicate_references"] == [first.json()["reference"]]
    assert second.json()["id"] != first.json()["id"]


def test_citizen_feedback_is_only_allowed_once_after_official_closure(api, auth_headers):
    client, test_session, _ = api
    created = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(),
    )
    complaint_id = created.json()["id"]

    before_closure = client.post(
        f"/api/complaints/{complaint_id}/feedback",
        headers=auth_headers["citizen"],
        json={"rating": 5, "comment": "Resolved well"},
    )
    assert before_closure.status_code == 409

    with test_session() as db:
        complaint = db.get(Complaint, complaint_id)
        complaint.official_status = "OFFICIALLY_COMPLETED"
        db.commit()

    forbidden = client.post(
        f"/api/complaints/{complaint_id}/feedback",
        headers=auth_headers["other_citizen"],
        json={"rating": 5, "comment": "Not my report"},
    )
    submitted = client.post(
        f"/api/complaints/{complaint_id}/feedback",
        headers=auth_headers["citizen"],
        json={"rating": 4, "comment": "The repair was completed well."},
    )
    duplicate = client.post(
        f"/api/complaints/{complaint_id}/feedback",
        headers=auth_headers["citizen"],
        json={"rating": 5, "comment": "Second attempt"},
    )
    retrieved = client.get(
        f"/api/complaints/{complaint_id}/feedback",
        headers=auth_headers["citizen"],
    )

    assert forbidden.status_code == 404
    assert submitted.status_code == 201
    assert submitted.json()["rating"] == 4
    assert duplicate.status_code == 409
    assert retrieved.status_code == 200
    assert retrieved.json()["comment"] == "The repair was completed well."


def test_officer_can_confirm_or_override_triage_before_assignment(api, auth_headers):
    client, test_session, _ = api
    created = client.post(
        "/api/complaints/with-evidence",
        headers=auth_headers["citizen"],
        data=report_fields(
            title="Smoke pollution near homes",
            description="Heavy smoke and chemical odor are affecting nearby homes.",
        ),
    )
    complaint_id = created.json()["id"]
    assert created.json()["assessment"]["suggested_category"] == "Pollution & environment"

    decision = client.post(
        f"/api/complaints/{complaint_id}/triage",
        headers=auth_headers["officer"],
        json={
            "category": "Pollution & environment",
            "severity": "High",
            "reason": "Officer confirmed the environment department routing.",
        },
    )

    assert decision.status_code == 200
    assert decision.json()["category"] == "Pollution & environment"
    assert decision.json()["department"] == "Environment"
    assert decision.json()["severity"] == "High"
    with test_session() as db:
        assessment = db.query(ComplaintAssessment).filter_by(complaint_id=complaint_id).one()
        assert assessment.reviewed_by == "officer-test"
        assert assessment.override_reason == "Officer confirmed the environment department routing."
        assert assessment.reviewed_at is not None
