"""
Bandsintown scraper via public Artist Events API.

Docs: https://help.artists.bandsintown.com/en/articles/9186477-api-documentation
API:  GET https://rest.bandsintown.com/artists/{name}/events?app_id=...

IMPORTANT: Bandsintown's public API does NOT support location-based search
(returns 403). It only supports per-artist event lookup.

Strategy: maintain a list of known artists/bands that perform in the
Viana do Castelo / Alto Minho region, fetch their upcoming events,
and filter by location.

To extend: add more artists to KNOWN_ARTISTS list in config or override here.

Risk level: MEDIUM — public API, no auth needed, but per-artist only.
            Add artists to get useful data.
"""

from __future__ import annotations

from typing import Optional

from config import settings
from models import Event, EventCategory
from scrapers.base import BaseScraper
from normalizer import normalize_event
from utils.dates import parse_date, parse_time, parse_datetime
from utils.text import clean_text

API_BASE = "https://rest.bandsintown.com"

# Known artists that regularly perform in Viana do Castelo / Alto Minho region.
# Expand this list to get more results. Can also be loaded from config/DB.
DEFAULT_ARTISTS = [
    "Dead Combo",
    "Ornatos Violeta",
    "Xutos & Pontapés",
    "Deolinda",
    "Ana Moura",
    "Mariza",
    "Salvador Sobral",
    "Buraka Som Sistema",
    "Richie Campbell",
    "Paulo de Carvalho",
    "Moonspell",
    "Mind da Gap",
    "GNR",
    "Primitive Reason",
    "HMB",
]

# Location keywords to filter events by (lowercase match in city/country)
LOCATION_KEYWORDS = [
    "viana do castelo",
    "viana",
    "braga",
    "alto minho",
    "portugal",
    "pt",
]


class BandsintownScraper(BaseScraper):
    source_name = "bandsintown"
    base_url = API_BASE

    def __init__(self, artists: list[str] | None = None):
        super().__init__()
        self.artists = artists or DEFAULT_ARTISTS

    def fetch(self) -> list[Event]:
        events: list[Event] = []

        for artist_name in self.artists:
            artist_events = self._fetch_artist_events(artist_name)
            events.extend(artist_events)
            if artist_events:
                self.logger.debug(
                    "Bandsintown: %d events for artist '%s'",
                    len(artist_events), artist_name,
                )

        self.logger.info(
            "Bandsintown: %d total events before location filter", len(events)
        )

        # Filter to only events in Portugal / region
        filtered = [e for e in events if self._is_in_region(e)]
        self.logger.info(
            "Bandsintown: %d events after location filter", len(filtered)
        )
        return filtered

    # ------------------------------------------------------------------

    def _fetch_artist_events(self, artist_name: str) -> list[Event]:
        encoded = artist_name.replace(" ", "%20").replace("&", "%26")
        data = self.get_json(
            f"{API_BASE}/artists/{encoded}/events",
            params={
                "app_id": settings.bandsintown_app_id,
                "date": "upcoming",
            },
        )

        if not data:
            return []

        if isinstance(data, dict) and ("error" in data or data.get("artist") == ""):
            self.logger.debug("No Bandsintown data for artist: %s", artist_name)
            return []

        if not isinstance(data, list):
            return []

        events = []
        for raw in data:
            event = self._parse_event(raw, artist_name)
            if event:
                events.append(event)
        return events

    def _parse_event(self, raw: dict, artist_name: str) -> Optional[Event]:
        try:
            title = clean_text(raw.get("title", "")) or f"{artist_name} — Concerto"

            raw_dt = raw.get("datetime", "") or raw.get("starts_at", "")
            event_date = parse_date(raw_dt)
            event_time = parse_time(raw_dt)
            datetime_iso = parse_datetime(raw_dt)

            venue_data = raw.get("venue", {}) or {}
            venue_name = clean_text(venue_data.get("name", ""))
            city = venue_data.get("city") or ""
            country = venue_data.get("country", "")
            region_str = venue_data.get("region") or ""

            address_parts = [
                venue_data.get("street_address") or venue_data.get("street", ""),
                city,
                region_str,
                country,
            ]
            address = ", ".join(p for p in address_parts if p)

            source_url = raw.get("url", "") or raw.get("event_url", "")

            # artist image
            offers = raw.get("offers", [])
            image_url = None
            artist_data = raw.get("artist", {})
            if isinstance(artist_data, dict):
                image_url = artist_data.get("image_url") or artist_data.get("thumb_url")

            # lineup tags
            lineup = raw.get("lineup", [])
            tags = []
            if isinstance(lineup, list):
                tags = [
                    (a if isinstance(a, str) else a.get("name", ""))
                    for a in lineup
                ]
                tags = [t for t in tags if t]

            description = clean_text(raw.get("description", ""), max_len=300)

            # determine effective city/region for storage
            effective_region = settings.default_region
            if country.lower() in {"pt", "portugal"} and city:
                effective_region = city

            return normalize_event(Event(
                id=Event.make_id(
                    source_url=source_url,
                    title=title,
                    date=event_date or "",
                    venue=venue_name or "",
                ),
                title=title,
                date=event_date,
                time=event_time,
                datetime_iso=datetime_iso,
                city=city or effective_region,
                region=effective_region,
                venue=venue_name,
                address=address,
                short_description=description,
                source_name=self.source_name,
                source_url=source_url,
                image_url=image_url,
                category=EventCategory.CONCERT,
                tags=tags,
            ))

        except Exception as e:
            self.logger.warning("Failed to parse Bandsintown event: %s", e)
            return None

    @staticmethod
    def _is_in_region(event: Event) -> bool:
        """Return True if event appears to be in Portugal / target region."""
        check = " ".join(filter(None, [
            event.city or "",
            event.region or "",
            event.address or "",
        ])).lower()
        return any(kw in check for kw in LOCATION_KEYWORDS)
