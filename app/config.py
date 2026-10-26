import ipaddress
import logging

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
    # Microsoft Graph sender (ticket 02): all four set → real email. Outside
    # dev all four are required (the app refuses to start); in dev any one
    # missing → emails are only logged. SecretStr keeps the secret out of
    # repr/logs.
    ms_tenant_id: str = ""
    ms_client_id: str = ""
    ms_client_secret: SecretStr = SecretStr("")
    mail_sender: str = ""
    # Exchange allows about 30 messages a minute per mailbox.
    # Checked at start-up: a bad value must stop the app, not fail every click.
    mail_rate_per_minute: int = Field(default=25, ge=1)

    # The proxy in front of the app (STORY-006 ticket 06): its IPs or CIDR
    # ranges, comma separated, or "none" when clients connect directly. Only a
    # request arriving from one of these may say who the client is
    # (X-Forwarded-For). Required outside dev; empty in dev means 127.0.0.1.
    forwarded_allow_ips: str = ""

    class Config:
        env_file = ".env"

    @model_validator(mode="after")
    def _require_real_secret_outside_dev(self) -> "Settings":
        # A known SECRET_KEY lets anyone forge a session cookie, so refuse to start.
        if self.app_env != "dev" and self.secret_key in _PLACEHOLDER_SECRETS:
            raise ValueError("SECRET_KEY must be set to a real secret when APP_ENV is not 'dev'")
        return self

    def graph_missing(self) -> list[str]:
        """Names of the Graph settings that are empty (values never shown)."""
        values = {"MS_TENANT_ID": self.ms_tenant_id, "MS_CLIENT_ID": self.ms_client_id,
                  "MS_CLIENT_SECRET": self.ms_client_secret.get_secret_value(),
                  "MAIL_SENDER": self.mail_sender}
        return [name for name, value in values.items() if not value.strip()]

    @model_validator(mode="after")
    def _require_graph_outside_dev(self) -> "Settings":
        # Without a real sender every request would be marked notified while
        # no email went out, and nothing would show on the resend list.
        missing = self.graph_missing()
        if self.app_env != "dev" and missing:
            raise ValueError(f"{', '.join(missing)} must be set when APP_ENV is not 'dev' "
                             "(see .env.example)")
        if missing and len(missing) < 4:
            # Half-configured in dev is a mistake worth seeing, once at start.
            logging.getLogger("app.mail").warning(
                "mail: Graph settings incomplete (missing %s) — emails are only logged",
                ", ".join(missing))
        return self

    def trusted_proxies(self) -> list[str] | None:
        """The proxies whose X-Forwarded-For is believed, or None for "none"
        (no proxy: the connecting address is the client). Raises ValueError
        on a value that must not start the app."""
        raw = self.forwarded_allow_ips.strip()
        # A stray comma leaves an empty entry: a typo, not a wrong value. Only
        # commas count as unset (STORY-015 21).
        entries = [e.strip() for e in raw.split(",") if e.strip()]
        if not entries:
            if self.app_env == "dev":
                return ["127.0.0.1"]
            # Unset behind a platform proxy, every request would look like the
            # proxy's one IP, and the login limit per IP would block every plant.
            raise ValueError(
                "FORWARDED_ALLOW_IPS must be set when APP_ENV is not 'dev': the IPs or "
                "CIDR ranges of the proxy in front of the app (comma separated), or "
                "'none' if clients connect directly (see .env.example)")
        if "*" in raw:
            # uvicorn's "*" takes the leftmost X-Forwarded-For entry, which the
            # client writes itself: anyone could pose as any IP.
            raise ValueError(
                "FORWARDED_ALLOW_IPS must not contain '*': with '*' the client IP is "
                "read from the leftmost X-Forwarded-For entry, which the client writes "
                "itself, so anyone could pose as any IP. List the proxy's IPs or CIDR "
                "ranges, or 'none'")
        if [e.lower() for e in entries] == ["none"]:
            return None
        for entry in entries:
            try:
                ipaddress.ip_network(entry)
            except ValueError:
                raise ValueError(
                    f"FORWARDED_ALLOW_IPS: {entry!r} is not an IP address or CIDR range "
                    "('none' must stand alone)") from None
        return entries

    @model_validator(mode="after")
    def _check_forwarded_allow_ips(self) -> "Settings":
        # A bad value must stop the app at start, not misjudge every login.
        self.trusted_proxies()
        return self

    @property
    def cookie_secure(self) -> bool:
        """Session cookie travels over HTTPS only, except on a dev machine."""
        return self.app_env != "dev"


settings = Settings()
