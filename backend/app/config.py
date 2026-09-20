from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "production"
    database_url: str = "sqlite:///./doctor.db"
    # T31's shared upload component writes here. Relative paths resolve against
    # the backend working directory, which is where the startup scripts run.
    upload_dir: str = "uploads"
    jwt_secret: str = Field(default="", repr=False)
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_from: str = "noreply@example.test"
    smtp_starttls: bool = True
    smtp_timeout: float = Field(default=10, gt=0, le=30)
    otp_daily_limit: int = Field(default=20, ge=1)
    scheduler_enabled: bool = True
    reminder_timezone: str = "Asia/Shanghai"
    redis_url: str | None = None
    # AES-256 key material for patient identifiers (T13). Any passphrase works,
    # because it is hashed to 32 bytes; set a real secret outside local development.
    patient_data_key: str = "dev-only-insecure-patient-data-key"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
