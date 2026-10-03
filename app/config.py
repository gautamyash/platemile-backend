from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:dev@localhost:5432/dietapp"
    redis_url: str = "redis://localhost:6380"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 30
    google_client_id: str = ""  # Web client ID (ID-token audience)
    google_extra_client_ids: str = ""  # comma separated, optional
    welcome_credits: int = 50
    gemini_timeout_s: int = 25
    ai_mode: Literal["engine", "llm"] = "engine"  # engine = curated recipes, no LLM; llm = old Gemini path for meals/plans/grocery
    rate_limit_enabled: bool = True
    dev_login_enabled: bool = False  # local testing only; must stay False in production
    support_email: str = "support@example.com"  # set to the real support address before launch

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, v: str) -> str:
        """Hosts (Render, Heroku...) hand out postgres:// or postgresql:// URLs; we need the asyncpg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                v = "postgresql+asyncpg://" + v[len(prefix):]
        # asyncpg does not understand ?sslmode=...; drop it (use the host's internal URL, or ?ssl=require)
        if "sslmode=" in v:
            base, _, query = v.partition("?")
            kept = [q for q in query.split("&") if q and not q.startswith("sslmode=")]
            v = base + ("?" + "&".join(kept) if kept else "")
        return v

    @property
    def google_audiences(self) -> list[str]:
        ids = [self.google_client_id, *self.google_extra_client_ids.split(",")]
        return [i.strip() for i in ids if i.strip()]


settings = Settings()
