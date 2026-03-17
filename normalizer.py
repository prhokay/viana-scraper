"""
Data normalization and auto-categorization.

normalize_event() — cleans all fields of an Event in place.
categorize()      — returns EventCategory based on keywords.
"""

from __future__ import annotations

import re
from typing import Optional

from models import Event, EventCategory
from utils.text import clean_text, truncate

# --------------------------------------------------------------------------
# Keyword maps for category detection
# --------------------------------------------------------------------------

_KEYWORDS: dict[EventCategory, list[str]] = {
    EventCategory.RUNNING: [
        "corrida", "maratona", "meia maratona", "trail", "trailrun", "ultratrail",
        "running", "run", "marathon", "half marathon", "triathlon", "duatlo",
        "duatlon", "corridas", "atletismo", "cross country", "10k", "5k", "15k",
        "20k", "circuito pedestre", "pedestrianismo",
    ],
    EventCategory.CONCERT: [
        "concerto", "concert", "música", "musica", "banda", "band", "festival musical",
        "espetáculo musical", "espetaculo", "live music", "ao vivo", "dj set",
        "noite de fado", "fado", "gala", "recital", "jam session",
    ],
    EventCategory.FESTIVAL: [
        "festival", "festas", "festa", "romaria", "arraial", "fair", "feria",
        "feira", "carnaval", "folia", "procissão", "procissao", "celebração",
    ],
    EventCategory.SPORTS: [
        "futebol", "football", "rugby", "ténis", "tenis", "basquetebol",
        "voleibol", "natação", "natacao", "ciclismo", "cycling", "vela", "remo",
        "judo", "karaté", "capoeira", "equitação", "desporto", "sport", "fitness",
        "ginásio", "yoga", "pilates", "surf", "skate", "esgrima",
    ],
    EventCategory.CULTURE: [
        "teatro", "theatre", "exposição", "exposicao", "museu", "museum",
        "arte", "art", "dança", "danca", "ballet", "cinema", "film", "filme",
        "literatura", "livro", "book", "conferência", "conferencia", "workshop",
        "palestra", "lecture", "gastronomia", "culinária", "fotografia",
    ],
}

# compile for fast matching
_COMPILED: dict[EventCategory, re.Pattern] = {
    cat: re.compile(
        r"\b(" + "|".join(re.escape(kw) for kw in sorted(kws, key=len, reverse=True)) + r")\b",
        re.IGNORECASE | re.UNICODE,
    )
    for cat, kws in _KEYWORDS.items()
}

# Priority order (first match wins)
_PRIORITY = [
    EventCategory.RUNNING,
    EventCategory.CONCERT,
    EventCategory.FESTIVAL,
    EventCategory.SPORTS,
    EventCategory.CULTURE,
]


def categorize(
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    eb_category: str = "",
) -> EventCategory:
    """
    Infer EventCategory from title, description, tags, and optional
    Eventbrite category string.
    Returns EventCategory.OTHER if nothing matches.
    """
    search_text = " ".join(filter(None, [title, description, " ".join(tags or []), eb_category]))

    for cat in _PRIORITY:
        if _COMPILED[cat].search(search_text):
            return cat

    return EventCategory.OTHER


def normalize_event(event: Event) -> Event:
    """
    Cleans and normalizes all text fields of an Event.
    Returns the same event (mutated) for chaining.
    """
    event.title = clean_text(event.title) or event.title
    event.short_description = truncate(clean_text(event.short_description), 300)
    event.full_description = clean_text(event.full_description)
    event.venue = clean_text(event.venue)
    event.address = clean_text(event.address)
    event.city = _normalize_city(event.city)
    event.region = _normalize_region(event.region)

    # Ensure region/city defaults
    if not event.region:
        event.region = "Viana do Castelo"
    if not event.city:
        event.city = event.region

    # Tags: deduplicate and lowercase
    event.tags = list(dict.fromkeys(t.lower().strip() for t in event.tags if t and t.strip()))

    # Re-run categorization if still OTHER
    if event.category == EventCategory.OTHER:
        event.category = categorize(
            event.title,
            event.short_description or "",
            event.tags,
        )

    return event


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------

_CITY_ALIASES = {
    "viana": "Viana do Castelo",
    "viana do castelo": "Viana do Castelo",
    "vdc": "Viana do Castelo",
    "braga": "Braga",
    "porto": "Porto",
    "lisbon": "Lisboa",
    "lisabon": "Lisboa",
    "lisboa": "Lisboa",
}


def _normalize_city(city: Optional[str]) -> Optional[str]:
    if not city:
        return None
    return _CITY_ALIASES.get(city.lower().strip(), city.strip().title())


_REGION_ALIASES = {
    "viana": "Viana do Castelo",
    "viana do castelo": "Viana do Castelo",
    "minho": "Minho",
    "alto minho": "Alto Minho",
}


def _normalize_region(region: Optional[str]) -> Optional[str]:
    if not region:
        return None
    return _REGION_ALIASES.get(region.lower().strip(), region.strip())
