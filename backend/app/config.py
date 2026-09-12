from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./doctor.db"
    jwt_secret: str = "dev-only-change-this-jwt-secret-at-least-32-bytes"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@example.test"
    smtp_starttls: bool = True
    scheduler_enabled: bool = True
    redis_url: str | None = None
    # AES-256 key material for patient identifiers (T13). Any passphrase works,
    # because it is hashed to 32 bytes; set a real secret outside local development.
    patient_data_key: str = "dev-only-insecure-patient-data-key"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
