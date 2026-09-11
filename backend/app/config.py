from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./doctor.db"
    jwt_secret: str = "dev-only-change-this-jwt-secret-at-least-32-bytes"
    scheduler_enabled: bool = True
    redis_url: str | None = None
    # AES-256 key material for patient identifiers (T13). Any passphrase works,
    # because it is hashed to 32 bytes; set a real secret outside local development.
    patient_data_key: str = "dev-only-insecure-patient-data-key"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
