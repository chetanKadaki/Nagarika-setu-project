import pytest
import jwt

from app.config import Settings, settings, validate_runtime_settings
from app.security import (
    TOKEN_AUDIENCE,
    TOKEN_ISSUER,
    TOKEN_TTL_SECONDS,
    create_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_uses_random_salt_and_verifies_password():
    first_hash = hash_password("a-long-civic-password")
    second_hash = hash_password("a-long-civic-password")

    assert first_hash != second_hash
    assert verify_password("a-long-civic-password", first_hash)
    assert not verify_password("a-different-password", first_hash)
    assert not verify_password("a-long-civic-password", "not-a-valid-hash")


def test_password_hash_rejects_weak_and_oversized_passwords():
    with pytest.raises(ValueError, match="12 characters"):
        hash_password("short")

    with pytest.raises(ValueError, match="12 characters"):
        hash_password("x" * 129)


def test_access_token_has_audience_issuer_and_short_expiry(api):
    _, _, users = api
    token = create_access_token(users["citizen"])
    claims = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=["HS256"],
        audience=TOKEN_AUDIENCE,
        issuer=TOKEN_ISSUER,
    )

    assert claims["sub"] == users["citizen"].id
    assert claims["exp"] - claims["iat"] == TOKEN_TTL_SECONDS


def test_tokens_without_a_database_session_are_rejected_outside_tests(api, monkeypatch):
    client, _, users = api
    monkeypatch.setattr(settings, "environment", "development")
    token = create_access_token(users["citizen"])

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_production_settings_require_secret_and_disable_demo_accounts():
    unsafe_config = Settings(
        environment="production",
        jwt_secret="development-only-not-for-production",
        frontend_origin="https://civic.example.test",
        seed_demo_accounts=False,
    )
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_runtime_settings(unsafe_config)

    valid_config = Settings(
        environment="production",
        jwt_secret="production-secret-that-is-more-than-32-characters",
        frontend_origin="https://civic.example.test",
        seed_demo_accounts=False,
        database_url="mysql+pymysql://user:password@localhost:3306/nagariksetu",
        smtp_host="smtp.example.test",
        smtp_sender="noreply@example.test",
    )
    validate_runtime_settings(valid_config)


def test_production_settings_reject_demo_seeding_and_wildcard_hosts():
    with pytest.raises(RuntimeError, match="Demo accounts"):
        validate_runtime_settings(
            Settings(
                environment="production",
                jwt_secret="production-secret-that-is-more-than-32-characters",
                frontend_origin="https://civic.example.test",
                seed_demo_accounts=True,
            )
        )

    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        validate_runtime_settings(Settings(allowed_hosts="*"))
