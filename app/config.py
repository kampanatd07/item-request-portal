from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """App settings loaded from environment variables (.env in local dev)."""

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-only-change-me"
    app_env: str = "dev"

    class Config:
        env_file = ".env"


settings = Settings()
