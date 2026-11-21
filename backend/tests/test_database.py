import pytest
from sqlalchemy import URL, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import database
from app.database import Base, create_database_engine
from app.models import Complaint, User
from app.seed import seed_demo_data


def test_sqlite_connections_enforce_foreign_keys_and_busy_timeout(tmp_path):
    engine = create_database_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "civic.sqlite3")).render_as_string(
            hide_password=False
        )
    )
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 30_000
            assert connection.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
    finally:
        engine.dispose()


def test_database_dependency_rolls_back_when_request_fails(monkeypatch, tmp_path):
    engine = create_database_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "rollback.sqlite3")).render_as_string(
            hide_password=False
        )
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(database, "SessionLocal", test_session)

    dependency = database.get_db()
    session = next(dependency)
    session.add(
        User(
            id="uncommitted",
            name="Uncommitted User",
            email="uncommitted@example.test",
            role="citizen",
            password_hash="test-hash",
        )
    )
    with pytest.raises(RuntimeError, match="request failed"):
        dependency.throw(RuntimeError("request failed"))

    with test_session() as check_session:
        assert check_session.get(User, "uncommitted") is None
    engine.dispose()


def test_database_dependency_closes_session_after_success(monkeypatch, tmp_path):
    engine = create_database_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "close.sqlite3")).render_as_string(
            hide_password=False
        )
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    monkeypatch.setattr(database, "SessionLocal", test_session)
    dependency = database.get_db()
    session = next(dependency)
    session.execute(text("SELECT 1"))

    with pytest.raises(StopIteration):
        next(dependency)

    assert not session.in_transaction()
    engine.dispose()


def test_sqlite_engine_rejects_unexpected_foreign_key_reference(tmp_path):
    engine = create_database_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "foreign-key.sqlite3")).render_as_string(
            hide_password=False
        )
    )
    Base.metadata.create_all(engine)

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO complaints "
                "(id, reference, title, description, category, severity, official_status, "
                "engineer_work_status, verification_status, ward, address, latitude, longitude, "
                "department, citizen_id, is_demo, created_at) "
                "VALUES ('bad', 'CP-9999', 'Test complaint', 'Description', 'Roads', 'Low', "
                "'SUBMITTED', 'NOT_STARTED', 'NOT_SUBMITTED', 'Ward 1', 'Test address', "
                "12.0, 77.0, 'Public Works', 'missing-citizen', 0, '2026-01-15 10:30:00')"
            )
    engine.dispose()


def test_demo_seed_respects_foreign_keys_on_a_fresh_database(tmp_path):
    engine = create_database_engine(
        URL.create("sqlite+pysqlite", database=str(tmp_path / "seed.sqlite3")).render_as_string(
            hide_password=False
        )
    )
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine)
    try:
        with test_session() as db:
            seed_demo_data(db)
            assert db.query(User).count() == 4
            assert db.query(Complaint).count() == 7
        with test_session() as db:
            seed_demo_data(db)
            assert db.query(User).count() == 4
            assert db.query(Complaint).count() == 7
    finally:
        engine.dispose()
