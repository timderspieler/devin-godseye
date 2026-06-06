"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class Settings(BaseSettings):
    """Runtime configuration.

    Values are read from environment variables (or a local ``.env`` file).
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Devin API ---
    devin_api_key: str = ""
    devin_api_base_url: str = "https://api.devin.ai"

    # --- GitHub ---
    github_token: str = ""
    github_api_base_url: str = "https://api.github.com"
    github_webhook_secret: str = ""
    # Repository the automation watches, used as the default for the prompt link.
    target_repo: str = "timderspieler/superset"

    # --- Labels ---
    # Labels that trigger the automation when added to an issue.
    trigger_labels: str = "devin-fix"
    # Labels that auto-approve a session without manual review.
    auto_approve_labels: str = ""

    # --- Storage / polling ---
    database_url: str = "sqlite:///./data/godseye.db"
    poll_interval_seconds: int = 30
    # When False, the background poller is not started (useful for tests).
    enable_poller: bool = True

    # Default ACU limit applied to created sessions (None = account default).
    session_max_acu_limit: int | None = None

    @property
    def trigger_label_set(self) -> set[str]:
        return {label.lower() for label in _split_csv(self.trigger_labels)}

    @property
    def auto_approve_label_set(self) -> set[str]:
        return {label.lower() for label in _split_csv(self.auto_approve_labels)}


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
