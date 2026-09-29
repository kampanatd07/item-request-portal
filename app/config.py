from pydantic import model_validator
from pydantic_settings import BaseSettings

# Placeholder secrets that must never reach a non-dev environment.
_PLACEHOLDER_SECRETS = {"dev-only-change-me", "change-me", ""}


class Settings(BaseSettings):
    """App settings loaded from environment variables (.env in local dev)."""

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-only-change-me"
    app_env: str = "dev"

    # Argon2 cost parameters. Defaults are argon2-cffi's RFC 9106 profile;
    # tests lower them through env vars so the suite stays fast.
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536  # KiB
    argon2_parallelism: int = 4

    # A session ends this long after login, whatever happens in between
    # (STORY-001). No "remember me".
    session_max_hours: int = 8

    class Config:
        env_file = ".env"

    @model_validator(mode="after")
    def _require_real_secret_outside_dev(self) -> "Settings":
        # A known SECRET_KEY lets anyone forge a session cookie, so refuse to start.
        if self.app_env != "dev" and self.secret_key in _PLACEHOLDER_SECRETS:
            raise ValueError("SECRET_KEY must be set to a real secret when APP_ENV is not 'dev'")
        return self

    @property
    def cookie_secure(self) -> bool:
        """Session cookie travels over HTTPS only, except on a dev machine."""
        return self.app_env != "dev"


settings = Settings()
