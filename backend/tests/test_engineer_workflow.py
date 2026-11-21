from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import URL, create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    Complaint,
    ComplaintAssignment,
    EngineerProfile,
    LiveWorkLocation,
    SchemeTask,
    User,
    WorkUpdate,
)
from app.seed import seed_demo_data


def register_engineer(client, auth_mailbox, email="new-engineer@example.test"):
    password = "a-secure-engineer-password"
    response = client.post(
        "/api/engineers/register",
        json={
            "name": "New Engineer",
            "email": email,
            "password": password,
            "confirm_password": password,
            "phone_number": "+15550102030",
            "terms_accepted": True,
            "department": "Public Works",
            "registration_number": f"REG-{email.split('@')[0]}",
            "skills": ["Road repair", "  ", "Road repair"],
            "application_note": "Registered engineer application for road works.",
        },
    )
    assert response.status_code == 202
    verified = client.post(
        "/api/auth/verify-email",
        json={"token": auth_mailbox[("verification", email)]},
    )
    assert verified.status_code == 200
    login = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200
    return login.json()


def create_scheme_task(client, officer_headers, engineer_id):
    return client.post(
        "/api/scheme-tasks",
        headers=officer_headers,
        json={
            "scheme_title": "Swachh Bharat Mission – Urban",
            "title": "Repair the public waste collection point",
            "description": "Restore the waste collection point and improve safe access.",
            "department": "Public Works",
            "required_skills": ["road repair"],
            "engineer_id": engineer_id,
        },
    )


def test_engineer_registration_requires_officer_approval_before_assignment(
    api, auth_headers, assigned_complaint, auth_mailbox
):
    client, test_session, users = api
    application = register_engineer(client, auth_mailbox)
    applicant_id = application["user"]["id"]
    applicant_headers = {
        "Authorization": f"Bearer {application['access_token']}",
    }

    assert application["user"]["role"] == "engineer_pending"
    assert client.get("/api/complaints", headers=applicant_headers).status_code == 403
    assert client.get("/api/dashboard", headers=applicant_headers).status_code == 403
    assert client.get(
        "/api/engineers/registrations",
        headers=auth_headers["citizen"],
    ).status_code == 403

    blocked_assignment = client.post(
        f"/api/complaints/{assigned_complaint}/assign",
        headers=auth_headers["officer"],
        json={"engineer_id": applicant_id, "verifier_id": users["verifier"].id},
    )
    assert blocked_assignment.status_code == 422

    queue = client.get("/api/engineers/registrations", headers=auth_headers["officer"])
    assert [item["user_id"] for item in queue.json()] == [applicant_id]
    decision = client.post(
        f"/api/engineers/registrations/{applicant_id}/decision",
        headers=auth_headers["officer"],
        json={"decision": "APPROVED", "reason": "Credentials checked by department staff."},
    )
    assert decision.status_code == 200
    assert client.get("/api/engineers/registrations", headers=auth_headers["officer"]).json() == []
    assert any(item["id"] == applicant_id for item in client.get(
        "/api/engineers", headers=auth_headers["officer"]
    ).json())

    assignment = client.post(
        f"/api/complaints/{assigned_complaint}/assign",
        headers=auth_headers["officer"],
        json={"engineer_id": applicant_id, "verifier_id": users["verifier"].id},
    )
    assert assignment.status_code == 200
    assigned_engineer = assignment.json()["assigned_engineer"]
    assert assigned_engineer == {
        "id": applicant_id,
        "name": "New Engineer",
        "department": "Public Works",
        "registration_number": "REG-NEW-ENGINEER",
        "skills": ["Road repair"],
    }
    with test_session() as db:
        profile = db.get(EngineerProfile, applicant_id)
        assert profile is not None
        assert profile.registration_status == "APPROVED"
        assert db.scalar(
            select(func.count()).select_from(ComplaintAssignment).where(
                ComplaintAssignment.complaint_id == assigned_complaint
            )
        ) == 1


def test_officer_assignment_is_filtered_and_enforced_by_engineer_eligibility(
    api, auth_headers, assigned_complaint
):
    client, test_session, users = api
    path = f"/api/complaints/{assigned_complaint}/eligible-engineers"

    eligible = client.get(path, headers=auth_headers["officer"])
    assert eligible.status_code == 200
    assert [engineer["id"] for engineer in eligible.json()] == [users["engineer"].id]
    assert client.get(path, headers=auth_headers["citizen"]).status_code == 403

    for department, skills in [
        ("Public Works", ["Street lighting"]),
        ("Electrical", ["Road repair"]),
    ]:
        with test_session() as db:
            profile = db.get(EngineerProfile, users["engineer"].id)
            assert profile is not None
            profile.department = department
            profile.skills = skills
            db.commit()

        assert client.get(path, headers=auth_headers["officer"]).json() == []
        assignment = client.post(
            f"/api/complaints/{assigned_complaint}/assign",
            headers=auth_headers["officer"],
            json={"engineer_id": users["engineer"].id, "verifier_id": users["verifier"].id},
        )
        assert assignment.status_code == 422
        assert "department and skills match" in assignment.json()["detail"]


def test_new_report_is_routed_to_its_category_department(api, auth_headers):
    client, _, _ = api
    response = client.post(
        "/api/complaints",
        headers=auth_headers["citizen"],
        json={
            "title": "Low water pressure",
            "description": "Water pressure has been low on several nearby streets.",
            "category": "Water & drainage",
            "severity": "Medium",
            "address": "Main Street near the public park",
            "ward": "Ward 1",
            "latitude": 12.97,
            "longitude": 77.64,
        },
    )

    assert response.status_code == 201
    assert response.json()["department"] == "Water Supply"


def test_engineer_work_updates_track_start_progress_and_are_role_scoped(
    api, auth_headers, assigned_complaint
):
    client, test_session, _ = api
    with test_session() as db:
        complaint = db.get(Complaint, assigned_complaint)
        assert complaint is not None
        complaint.engineer_work_status = "NOT_STARTED"
        db.commit()

    started = client.post(
        f"/api/complaints/{assigned_complaint}/work/start",
        headers=auth_headers["engineer"],
        json={"note": "Crew arrived and inspected the road.", "latitude": 12.97, "longitude": 77.64},
    )
    assert started.status_code == 200
    progress = client.post(
        f"/api/complaints/{assigned_complaint}/work/progress",
        headers=auth_headers["engineer"],
        json={"note": "Damaged asphalt has been removed."},
    )
    assert progress.status_code == 200

    history = client.get(
        f"/api/complaints/{assigned_complaint}/work/history",
        headers=auth_headers["citizen"],
    )
    assert history.status_code == 404
    history = client.get(
        f"/api/complaints/{assigned_complaint}/work/history",
        headers=auth_headers["other_citizen"],
    )
    assert history.status_code == 200
    assert [event["event_type"] for event in history.json()] == ["WORK_STARTED", "PROGRESS_UPDATE"]
    assert all("latitude" not in event and "longitude" not in event for event in history.json())
    with test_session() as db:
        assert db.scalar(
            select(func.count()).select_from(WorkUpdate).where(
                WorkUpdate.complaint_id == assigned_complaint
            )
        ) == 2
    assert client.post(
        f"/api/complaints/{assigned_complaint}/work/start",
        headers=auth_headers["engineer"],
        json={"note": "Trying to start again."},
    ).status_code == 409


def test_officer_assigns_scheme_work_by_eligibility_and_public_listing_redacts_ids(
    api, auth_headers
):
    client, _, users = api
    eligible = client.get(
        "/api/scheme-tasks/eligible-engineers",
        headers=auth_headers["officer"],
        params={"department": "Public Works", "required_skills": "road repair"},
    )
    assert eligible.status_code == 200
    assert [item["id"] for item in eligible.json()] == [users["engineer"].id]
    assert client.get(
        "/api/scheme-tasks/eligible-engineers",
        headers=auth_headers["officer"],
        params={"department": "Water Supply", "required_skills": "road repair"},
    ).json() == []

    assigned = create_scheme_task(client, auth_headers["officer"], users["engineer"].id)
    assert assigned.status_code == 201
    task = assigned.json()
    assert task["scheme_title"] == "Swachh Bharat Mission – Urban"
    assert task["assigned_engineer"] == {
        "id": users["engineer"].id,
        "name": users["engineer"].name,
        "department": "Public Works",
        "registration_number": "ENG-TEST-001",
        "skills": ["Road maintenance"],
    }

    engineer_tasks = client.get("/api/scheme-tasks", headers=auth_headers["engineer"])
    assert [item["id"] for item in engineer_tasks.json()] == [task["id"]]
    public_task = client.get("/api/public/scheme-tasks").json()[0]
    assert public_task["assigned_engineer"]["name"] == users["engineer"].name
    assert "id" not in public_task["assigned_engineer"]
    assert "updates" not in public_task
    assert "progress_note" not in public_task
    assert client.post(
        "/api/scheme-tasks",
        headers=auth_headers["citizen"],
        json={
            "scheme_title": "Public scheme",
            "title": "Task for residents",
            "description": "This request should not create officer work.",
            "department": "Public Works",
            "required_skills": ["road repair"],
            "engineer_id": users["engineer"].id,
        },
    ).status_code == 403
    assert client.post(
        "/api/scheme-tasks",
        headers=auth_headers["officer"],
        json={
            "scheme_title": "Public scheme",
            "title": "Water system task",
            "description": "This task does not match the engineer's department.",
            "department": "Water Supply",
            "required_skills": ["road repair"],
            "engineer_id": users["engineer"].id,
        },
    ).status_code == 422


def test_scheme_task_progress_and_live_location_are_role_scoped_and_cleared_on_completion(
    api, auth_headers
):
    client, test_session, users = api
    task_response = create_scheme_task(client, auth_headers["officer"], users["engineer"].id)
    assert task_response.status_code == 201
    task_id = task_response.json()["id"]

    started = client.post(
        f"/api/scheme-tasks/{task_id}/start",
        headers=auth_headers["engineer"],
    )
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"
    progress = client.post(
        f"/api/scheme-tasks/{task_id}/progress",
        headers=auth_headers["engineer"],
        json={"note": "The collection point has been cleared."},
    )
    assert progress.status_code == 200
    assert progress.json()["updates"][-1]["event_type"] == "PROGRESS_UPDATE"

    location = client.post(
        f"/api/scheme-tasks/{task_id}/location",
        headers=auth_headers["engineer"],
        json={"latitude": 12.97, "longitude": 77.64},
    )
    assert location.status_code == 200
    assert client.get("/api/work/live-locations", headers=auth_headers["engineer"]).status_code == 403
    assert client.get("/api/work/live-locations", headers=auth_headers["citizen"]).status_code == 403
    locations = client.get("/api/work/live-locations", headers=auth_headers["officer"])
    assert locations.status_code == 200
    assert len(locations.json()) == 1
    assert locations.json()[0]["assigned_engineer"]["name"] == users["engineer"].name
    assert locations.json()[0]["scheme_title"] == "Swachh Bharat Mission – Urban"
    with test_session() as db:
        assert db.scalar(
            select(func.count()).select_from(LiveWorkLocation).where(
                LiveWorkLocation.scheme_task_id == task_id
            )
        ) == 1

    completed = client.post(
        f"/api/scheme-tasks/{task_id}/complete",
        headers=auth_headers["engineer"],
        json={"note": "The collection point is restored and ready for public use."},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert client.get("/api/work/live-locations", headers=auth_headers["officer"]).json() == []
    assert client.post(
        f"/api/scheme-tasks/{task_id}/location",
        headers=auth_headers["engineer"],
        json={"latitude": 12.97, "longitude": 77.64},
    ).status_code == 409
    with test_session() as db:
        assert db.get(SchemeTask, task_id).status == "COMPLETED"
        assert db.scalar(
            select(func.count()).select_from(LiveWorkLocation).where(
                LiveWorkLocation.scheme_task_id == task_id
            )
        ) == 0


def test_complaint_live_location_is_officer_only_and_removed_on_submission(
    api, auth_headers, assigned_complaint, work_payload
):
    client, test_session, users = api
    location = client.post(
        f"/api/complaints/{assigned_complaint}/work/location",
        headers=auth_headers["engineer"],
        json={"latitude": 12.97, "longitude": 77.64},
    )
    assert location.status_code == 200
    assert client.get("/api/work/live-locations", headers=auth_headers["citizen"]).status_code == 403
    officer_locations = client.get("/api/work/live-locations", headers=auth_headers["officer"])
    assert len(officer_locations.json()) == 1
    assert officer_locations.json()[0]["assigned_engineer"]["name"] == users["engineer"].name

    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    assert submitted.status_code == 200
    assert client.get("/api/work/live-locations", headers=auth_headers["officer"]).json() == []
    with test_session() as db:
        assert db.scalar(
            select(func.count()).select_from(LiveWorkLocation).where(
                LiveWorkLocation.complaint_id == assigned_complaint
            )
        ) == 0


@pytest.mark.parametrize(
    ("latitude", "distance_flag"),
    [(12.9718, False), (12.9817, True)],
)
def test_verification_queue_includes_gps_accuracy_distance_and_review_flag(
    api, auth_headers, assigned_complaint, work_payload, latitude, distance_flag
):
    client, _, _ = api
    work_payload.update(
        latitude=latitude,
        location_accuracy_meters=8.5,
        location_captured_at="2026-01-15T10:29:00Z",
    )
    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    assert submitted.status_code == 200

    queue = client.get("/api/verification/queue", headers=auth_headers["verifier"])
    unauthorized_queue = client.get(
        "/api/verification/queue", headers=auth_headers["other_verifier"]
    )

    assert queue.status_code == 200
    assert unauthorized_queue.json() == []
    submission = queue.json()[0]["submission"]
    assert submission["location_accuracy_meters"] == 8.5
    assert submission["location_captured_at"].startswith("2026-01-15T10:29:00")
    assert submission["distance_from_complaint_meters"] > 10
    assert submission["distance_review_flag"] is distance_flag


def test_work_submission_requires_accuracy_and_capture_time_together(
    api, auth_headers, assigned_complaint, work_payload
):
    client, _, _ = api
    work_payload["location_accuracy_meters"] = 8.5

    response = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )

    assert response.status_code == 422


def test_live_location_feed_expires_records_older_than_90_seconds(api, auth_headers):
    client, test_session, users = api
    task_response = create_scheme_task(client, auth_headers["officer"], users["engineer"].id)
    task_id = task_response.json()["id"]
    assert client.post(
        f"/api/scheme-tasks/{task_id}/start",
        headers=auth_headers["engineer"],
    ).status_code == 200
    assert client.post(
        f"/api/scheme-tasks/{task_id}/location",
        headers=auth_headers["engineer"],
        json={"latitude": 12.97, "longitude": 77.64},
    ).status_code == 200

    with test_session() as db:
        location = db.scalar(
            select(LiveWorkLocation).where(LiveWorkLocation.scheme_task_id == task_id)
        )
        assert location is not None
        location.updated_at = datetime.now(timezone.utc) - timedelta(seconds=89)
        db.commit()
    assert len(client.get("/api/work/live-locations", headers=auth_headers["officer"]).json()) == 1

    with test_session() as db:
        location = db.scalar(
            select(LiveWorkLocation).where(LiveWorkLocation.scheme_task_id == task_id)
        )
        assert location is not None
        location.updated_at = datetime.now(timezone.utc) - timedelta(seconds=91)
        db.commit()
    assert client.get("/api/work/live-locations", headers=auth_headers["officer"]).json() == []
    with test_session() as db:
        assert db.scalar(
            select(func.count()).select_from(LiveWorkLocation).where(
                LiveWorkLocation.scheme_task_id == task_id
            )
        ) == 0


def test_work_history_includes_engineer_submission_photos(
    api, auth_headers, assigned_complaint, work_payload
):
    client, _, users = api
    work_payload["before_evidence"] = "data:image/jpeg;base64,/9j/2Q=="
    work_payload["after_evidence"] = "data:image/jpeg;base64,/9j/2Q=="

    submitted = client.post(
        f"/api/complaints/{assigned_complaint}/work/submit",
        headers=auth_headers["engineer"],
        json=work_payload,
    )
    assert submitted.status_code == 200

    history = client.get(
        f"/api/complaints/{assigned_complaint}/work/history",
        headers=auth_headers["other_citizen"],
    )
    submission_events = [
        event
        for event in history.json()
        if event["event_type"] == "SUBMITTED_FOR_VERIFICATION"
    ]

    assert history.status_code == 200
    assert len(submission_events) == 1
    assert submission_events[0]["actor"] == users["engineer"].name
    assert submission_events[0]["before_evidence"] == work_payload["before_evidence"]
    assert submission_events[0]["after_evidence"] == work_payload["after_evidence"]
    assert submission_events[0]["attempt_number"] == 1
    assert "latitude" not in submission_events[0]
    assert "longitude" not in submission_events[0]


def test_rejected_application_cannot_access_complaints(api, auth_headers, auth_mailbox):
    client, _, _ = api
    application = register_engineer(client, auth_mailbox)
    applicant_id = application["user"]["id"]
    rejected = client.post(
        f"/api/engineers/registrations/{applicant_id}/decision",
        headers=auth_headers["officer"],
        json={"decision": "REJECTED", "reason": "Registration credentials could not be verified."},
    )
    assert rejected.status_code == 200
    assert client.get(
        "/api/engineers/me/registration",
        headers={"Authorization": f"Bearer {application['access_token']}"},
    ).json()["registration_status"] == "REJECTED"
    assert client.get(
        "/api/complaints",
        headers={"Authorization": f"Bearer {application['access_token']}"},
    ).status_code == 403
    resubmitted = client.put(
        "/api/engineers/me/registration",
        headers={"Authorization": f"Bearer {application['access_token']}"},
        json={
            "department": "Public Works",
            "registration_number": "REG-UPDATED-001",
            "skills": ["Road repair"],
            "application_note": "Updated credentials and engineering work scope.",
        },
    )
    assert resubmitted.status_code == 200
    assert resubmitted.json()["registration_status"] == "PENDING"
    assert client.get(
        "/api/engineers/registrations",
        headers=auth_headers["officer"],
    ).json()[0]["user_id"] == applicant_id


def test_demo_seed_backfills_engineer_profile_and_assignment_history():
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=":memory:"),
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with test_session() as db:
            seed_demo_data(db)
            complaint = db.get(Complaint, "cp-2048")
            assert complaint is not None
            db.execute(
                delete(ComplaintAssignment).where(
                    ComplaintAssignment.complaint_id == complaint.id
                )
            )
            complaint.verifier_id = None
            db.commit()

            seed_demo_data(db)

            profile = db.get(EngineerProfile, "engineer-01")
            complaint = db.get(Complaint, "cp-2048")
            assert profile is not None
            assert profile.registration_status == "APPROVED"
            assert complaint is not None
            assert complaint.verifier_id == "verifier-01"
            assert db.scalar(
                select(func.count()).select_from(ComplaintAssignment).where(
                    ComplaintAssignment.complaint_id == complaint.id
                )
            ) == 1
            assert db.get(User, "engineer-01") is not None
    finally:
        engine.dispose()
