from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    environment: str = "development"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embedding_model: str = "nomic-embed-text"
    chroma_path: str = "./chroma_db"
    database_url: str = "sqlite:///./data/civicai.sqlite3"
    complaint_upload_path: str = "./data/complaint-attachments"
    jwt_secret: str = "development-only-not-for-production"
    frontend_origin: str = "http://localhost:5173"
    google_client_id: str = ""
    seed_demo_accounts: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    smtp_starttls: bool = True
    bootstrap_admin_name: str = ""
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    allowed_hosts: str = "localhost,127.0.0.1,testserver"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()


def validate_runtime_settings(config: Settings = settings) -> None:
    allowed_hosts = [host.strip() for host in config.allowed_hosts.split(",") if host.strip()]
    if not allowed_hosts or "*" in allowed_hosts:
        raise RuntimeError("ALLOWED_HOSTS must contain explicit hostnames and cannot use a wildcard.")
    if config.environment.lower() == "production":
        if len(config.jwt_secret) < 32 or config.jwt_secret == "development-only-not-for-production":
            raise RuntimeError("Production requires a unique JWT_SECRET of at least 32 characters.")
        if config.seed_demo_accounts:
            raise RuntimeError("Demo accounts must be disabled in production.")
        if config.frontend_origin.startswith("http://"):
            raise RuntimeError("Production FRONTEND_ORIGIN must use HTTPS.")
        if not config.smtp_host or not config.smtp_sender:
            raise RuntimeError("Production requires SMTP_HOST and SMTP_SENDER for account emails.")
        if not 1 <= config.smtp_port <= 65535:
            raise RuntimeError("SMTP_PORT must be between 1 and 65535.")
        if config.smtp_port != 465 and not config.smtp_starttls:
            raise RuntimeError("Production SMTP must use STARTTLS or implicit TLS on port 465.")
        if make_url(config.database_url).get_backend_name() not in {"mysql", "mariadb"}:
            raise RuntimeError("Production requires a MySQL-compatible DATABASE_URL.")
    elif config.environment.lower() not in {"development", "test"}:
        raise RuntimeError("ENVIRONMENT must be development, test, or production.")
