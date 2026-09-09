from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./doctor.db"
    redis_url: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
