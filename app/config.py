from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings

# Placeholder secrets that must never reach a non-dev environment.
_PLACEHOLDER_SECRETS = {"dev-only-change-me", "change-me", ""}


class Settings(BaseSettings):
    """App settings loaded from environment variables (.env in local dev)."""

    database_url: str = "sqlite:///./dev.db"
    secret_key: str = "dev-only-change-me"
    # Fail closed: an unset APP_ENV means production (real SECRET_KEY required,
    # Secure cookie, no /docs). Dev machines set APP_ENV=dev explicitly.
    app_env: str = "production"

    # Argon2 cost parameters. Defaults are argon2-cffi's RFC 9106 profile;
    # tests lower them through env vars so the suite stays fast.
    argon2_time_cost: int = 3
    argon2_memory_cost: int = 65536  # KiB
    argon2_parallelism: int = 4

    # A session ends this long after login, whatever happens in between
    # (STORY-001). No "remember me".
    session_max_hours: int = 8

    # Email (STORY-002). Full portal address for links in emails; none when
    # empty. Replies go to Procurement when MAIL_REPLY_TO is set.
    public_base_url: str = ""
    mail_reply_to: str = ""
    # Microsoft Graph sender (ticket 02): all four set → real email; any one
    # missing → emails are only logged. SecretStr keeps the secret out of
    # repr/logs.
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")
    mail_sender: str = ""
    # Exchange allows about 30 messages a minute per mailbox.
    # Checked at start-up: a bad value must stop the app, not fail every click.
    mail_rate_per_minute: int = Field(default=25, ge=1)

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
