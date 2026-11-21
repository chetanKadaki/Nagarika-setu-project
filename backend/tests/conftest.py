from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Complaint, EngineerProfile, User
from app.security import create_access_token, hash_password


@pytest.fixture(scope="session")
def password_hashes() -> dict[str, str]:
    return {
        "citizen": hash_password("citizen-test-password"),
        "other_citizen": hash_password("other-citizen-test-password"),
        "engineer": hash_password("engineer-test-password"),
        "verifier": hash_password("verifier-test-password"),
        "other_verifier": hash_password("other-verifier-test-password"),
        "officer": hash_password("officer-test-password"),
    }


@pytest.fixture
def api(
    password_hashes: dict[str, str],
) -> Generator[tuple[TestClient, sessionmaker[Session], dict[str, User]], None, None]:
    engine = create_engine(
        URL.create("sqlite+pysqlite", database=":memory:"),
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    users = {
        "citizen": User(
            id="citizen-test",
            name="Test Citizen",
            email="citizen@example.test",
            role="citizen",
            password_hash=password_hashes["citizen"],
        ),
        "other_citizen": User(
            id="other-citizen-test",
            name="Other Test Citizen",
            email="other-citizen@example.test",
            role="citizen",
            password_hash=password_hashes["other_citizen"],
        ),
        "engineer": User(
            id="engineer-test",
            name="Test Engineer",
            email="engineer@example.test",
            role="engineer",
            password_hash=password_hashes["engineer"],
        ),
        "verifier": User(
            id="verifier-test",
            name="Test Verifier",
            email="verifier@example.test",
            role="verifier",
            password_hash=password_hashes["verifier"],
        ),
        "other_verifier": User(
            id="other-verifier-test",
            name="Other Verifier",
            email="other-verifier@example.test",
            role="verifier",
            password_hash=password_hashes["other_verifier"],
        ),
        "officer": User(
            id="officer-test",
            name="Test Officer",
            email="officer@example.test",
            role="officer",
            password_hash=password_hashes["officer"],
        ),
        "admin": User(
            id="admin-test",
            name="Test Administrator",
            email="admin@example.test",
            role="admin",
            password_hash=password_hashes["officer"],
        ),
    }

    with test_session() as db:
        db.add_all(users.values())
        db.add(
            EngineerProfile(
                user_id=users["engineer"].id,
                department="Public Works",
                registration_number="ENG-TEST-001",
                skills=["Road maintenance"],
                application_note="Approved test engineer profile.",
                registration_status="APPROVED",
            )
        )
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client, test_session, users
    client.close()
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def auth_headers(api):
    _, _, users = api
    return {
        role: {"Authorization": f"Bearer {create_access_token(user)}"}
        for role, user in users.items()
    }


@pytest.fixture
def assigned_complaint(api) -> str:
    _, test_session, users = api
    complaint = Complaint(
        id="complaint-test",
        reference="CP-9001",
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
        citizen_id=users["other_citizen"].id,
        engineer_id=users["engineer"].id,
        verifier_id=users["verifier"].id,
    )
    with test_session() as db:
        db.add(complaint)
        db.commit()
    return complaint.id


@pytest.fixture
def work_payload() -> dict:
    return {
        "work_details": "Filled and compacted the damaged road surface.",
        "completion_notes": "The repaired section is level and safe for traffic.",
        "before_evidence": "before-photo.jpg",
        "after_evidence": "after-photo.jpg",
        "latitude": 12.9718,
        "longitude": 77.6407,
        "captured_at": "2026-01-15T10:30:00Z",
    }


@pytest.fixture
def auth_mailbox(monkeypatch):
    import app.main as main_module

    mailbox = {}
    monkeypatch.setattr(main_module.settings, "smtp_host", "smtp.example.test")
    monkeypatch.setattr(main_module.settings, "smtp_sender", "noreply@example.test")
    monkeypatch.setattr(
        main_module,
        "send_verification_email",
        lambda email, token: mailbox.__setitem__(("verification", email), token),
    )
    monkeypatch.setattr(
        main_module,
        "send_password_reset_email",
        lambda email, token: mailbox.__setitem__(("reset", email), token),
    )
    monkeypatch.setattr(
        main_module,
        "send_invitation_email",
        lambda email, token: mailbox.__setitem__(("invitation", email), token),
    )
    return mailbox
