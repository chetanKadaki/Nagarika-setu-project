import uuid

from sqlalchemy import select

from app import models
from app.config import settings
from app.database import SessionLocal
from app.main import initialize_database
from app.schemas import normalize_email_address
from app.security import hash_password


def main() -> None:
    if not settings.bootstrap_admin_name.strip():
        raise RuntimeError("Set BOOTSTRAP_ADMIN_NAME before running this command.")
    if not settings.bootstrap_admin_email.strip():
        raise RuntimeError("Set BOOTSTRAP_ADMIN_EMAIL before running this command.")
    if not settings.bootstrap_admin_password:
        raise RuntimeError("Set BOOTSTRAP_ADMIN_PASSWORD before running this command.")

    name = settings.bootstrap_admin_name.strip()
    if not 2 <= len(name) <= 120:
        raise RuntimeError("BOOTSTRAP_ADMIN_NAME must be between 2 and 120 characters.")
    try:
        email = normalize_email_address(settings.bootstrap_admin_email)
    except ValueError as error:
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL must be a valid email address.") from error
    if len(email) > 180:
        raise RuntimeError("BOOTSTRAP_ADMIN_EMAIL must be 180 characters or fewer.")

    initialize_database()
    with SessionLocal() as db:
        if db.scalar(select(models.User.id).where(models.User.role == "admin")) is not None:
            raise RuntimeError("An administrator already exists; bootstrap can only run once.")
        if db.scalar(select(models.User.id).where(models.User.email == email)) is not None:
            raise RuntimeError("The bootstrap email already belongs to an account.")

        user = models.User(
            id=str(uuid.uuid4()),
            name=name,
            email=email,
            role="admin",
            password_hash=hash_password(settings.bootstrap_admin_password),
        )
        db.add(user)
        db.flush()
        db.add(
            models.UserAuthentication(
                user_id=user.id,
                email_verified=True,
                account_status="ACTIVE",
            )
        )
        db.commit()
    print(f"Administrator account created for {email}.")


if __name__ == "__main__":
    main()
