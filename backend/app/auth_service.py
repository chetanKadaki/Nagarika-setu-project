import hashlib
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import quote

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailVerificationToken, PasswordResetToken

EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=60)
INVITATION_TTL = timedelta(days=3)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def ensure_email_configured() -> None:
    if not settings.smtp_host or not settings.smtp_sender:
        raise RuntimeError("Email delivery is not configured. Set SMTP_HOST and SMTP_SENDER.")
    if bool(settings.smtp_username) != bool(settings.smtp_password):
        raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must both be configured.")


def create_one_time_token(
    db: Session,
    token_model: type[EmailVerificationToken] | type[PasswordResetToken],
    user_id: str,
    ttl: timedelta,
) -> str:
    db.execute(
        delete(token_model).where(
            token_model.user_id == user_id,
            token_model.used_at.is_(None),
        )
    )
    token = secrets.token_urlsafe(32)
    record = token_model(
        token_hash=token_digest(token),
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + ttl,
    )
    db.add(record)
    return token


def send_auth_email(recipient: str, subject: str, body: str) -> None:
    ensure_email_configured()

    message = EmailMessage()
    message["From"] = settings.smtp_sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            context=ssl.create_default_context(),
            timeout=15,
        ) as server:
            _send_message(server, recipient, message)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.ehlo()
            if settings.smtp_starttls:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            _send_message(server, recipient, message)


def send_verification_email(recipient: str, token: str) -> None:
    link = f"{settings.frontend_origin.rstrip('/')}/?verify_email={quote(token)}"
    send_auth_email(
        recipient,
        "Verify your NagarikSetu email",
        f"Open this link to verify your NagarikSetu account. It expires in 24 hours:\n\n{link}",
    )


def send_password_reset_email(recipient: str, token: str) -> None:
    link = f"{settings.frontend_origin.rstrip('/')}/?reset_password={quote(token)}"
    send_auth_email(
        recipient,
        "Reset your NagarikSetu password",
        f"Open this link to choose a new NagarikSetu password. It expires in 60 minutes:\n\n{link}",
    )


def send_invitation_email(recipient: str, token: str) -> None:
    link = f"{settings.frontend_origin.rstrip('/')}/?accept_invitation={quote(token)}"
    send_auth_email(
        recipient,
        "NagarikSetu official account invitation",
        f"Open this link to activate your official account. It expires in 3 days:\n\n{link}",
    )


def _send_message(server: smtplib.SMTP, recipient: str, message: EmailMessage) -> None:
    if settings.smtp_username:
        server.login(settings.smtp_username, settings.smtp_password)
    server.send_message(message, to_addrs=[recipient])
