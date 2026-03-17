"""
Configuration — loaded from .env file or environment variables.
Usage: from config import settings
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Eventbrite ---
    eventbrite_api_key: Optional[str] = None
    eventbrite_location: str = "Viana do Castelo, Portugal"
    eventbrite_radius: str = "50km"

    # --- Bandsintown ---
    bandsintown_app_id: str = "openclaw_events"  # any string per their docs
    bandsintown_location: str = "Viana do Castelo, PT"
    bandsintown_radius: int = 50  # km

    # --- Scraping behaviour ---
    request_timeout: int = 20          # seconds
    request_retries: int = 3
    request_delay: float = 1.5         # seconds between requests
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )

    # --- Storage ---
    storage_backend: str = "sqlite"     # "sqlite" | "json"
    sqlite_path: str = "events.db"
    json_path: str = "events.json"

    # --- Filtering defaults ---
    default_region: str = "Viana do Castelo"
    default_country: str = "Portugal"
    default_days_ahead: int = 30        # how many days to look ahead by default

    # --- Logging ---
    log_level: str = "INFO"
    log_file: Optional[str] = "scraper.log"

    # --- Telegram (OpenClaw Bot integration) ---
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    @field_validator("storage_backend")
    @classmethod
    def validate_backend(cls, v: str) -> str:
        allowed = {"sqlite", "json"}
        if v not in allowed:
            raise ValueError(f"storage_backend must be one of {allowed}")
        return v


settings = Settings()
BASE_DIR = Path(__file__).parent
