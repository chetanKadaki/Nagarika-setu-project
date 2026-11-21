from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, inspect, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() == "sqlite":
        sqlite_path = parsed_url.database or ":memory:"
        in_memory = sqlite_path == ":memory:" or parsed_url.query.get("mode") == "memory"
        if not in_memory and not sqlite_path.startswith("file:"):
            Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        database_engine = create_engine(
            parsed_url,
            connect_args={"check_same_thread": False, "timeout": 30},
            pool_pre_ping=True,
        )

        @event.listens_for(database_engine, "connect")
        def enable_sqlite_safety(dbapi_connection, _connection_record) -> None:
            del _connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            if not in_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return database_engine

    return create_engine(database_url, pool_pre_ping=True, pool_recycle=1800)


def ensure_user_timestamp_columns(database_engine: Engine) -> None:
    if "users" not in inspect(database_engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(database_engine).get_columns("users")}
    if {"created_at", "updated_at"}.issubset(columns):
        return
    timestamp_type = "DATETIME" if database_engine.dialect.name == "sqlite" else "DATETIME(6)"
    with database_engine.begin() as connection:
        for column_name in ("created_at", "updated_at"):
            if column_name not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE users ADD COLUMN {column_name} {timestamp_type}"
                )
        connection.exec_driver_sql(
            "UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
        connection.exec_driver_sql(
            "UPDATE users SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
        )


engine = create_database_engine(settings.database_url)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
