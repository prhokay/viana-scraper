"""
Event data model — unified structure for all scrapers/providers.
All scrapers must return List[Event].
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class EventCategory(str, Enum):
    CONCERT = "concert"
    RUNNING = "running"
    SPORTS = "sports"
    FESTIVAL = "festival"
    CULTURE = "culture"
    OTHER = "other"


class EventType(str, Enum):
    ONLINE = "online"
    PHYSICAL = "physical"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class Event(BaseModel):
    """Unified event model. All fields except id/title/source_url are optional."""

    id: str = Field(..., description="Stable deterministic ID: sha256(source_url or title+date+venue)")
    title: str
    date: Optional[str] = None            # ISO date: 2025-06-15
    time: Optional[str] = None            # HH:MM
    datetime_iso: Optional[str] = None    # 2025-06-15T20:00:00
    city: Optional[str] = None
    region: Optional[str] = None
    venue: Optional[str] = None
    address: Optional[str] = None
    category: EventCategory = EventCategory.OTHER
    tags: list[str] = Field(default_factory=list)
    short_description: Optional[str] = None
    full_description: Optional[str] = None
    source_name: str = ""
    source_url: str = ""
    image_url: Optional[str] = None
    price: Optional[float] = None
    currency: str = "EUR"
    event_type: EventType = EventType.UNKNOWN
    scraped_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, v):
        if v is None:
            return v
        return str(v)[:10]  # keep only YYYY-MM-DD

    @field_validator("tags", mode="before")
    @classmethod
    def validate_tags(cls, v):
        if isinstance(v, str):
            return [t.strip() for t in v.split(",") if t.strip()]
        return v or []

    def to_dict(self) -> dict:
        return self.model_dump()

    def to_json(self, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)

    @classmethod
    def make_id(cls, source_url: str = "", title: str = "", date: str = "", venue: str = "") -> str:
        """Deterministic stable ID — hash of the most unique combination."""
        if source_url:
            raw = source_url.strip()
        else:
            raw = f"{title.lower().strip()}|{date}|{venue.lower().strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    model_config = {"use_enum_values": True, "validate_assignment": True}
