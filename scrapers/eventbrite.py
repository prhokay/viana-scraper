"""
Eventbrite scraper via official REST API v3.

Docs: https://www.eventbrite.com/platform/api
Auth: Bearer token (private token from your Eventbrite account)

Set EVENTBRITE_API_KEY in .env.

Risk level: LOW — official API, stable, no HTML parsing needed.
Rate limit: ~1000 req/day on free tier.
"""

from __future__ import annotations

from typing import Optional

from config import settings
from models import Event, EventType
from scrapers.base import BaseScraper
from normalizer import categorize, normalize_event
from utils.dates import parse_date, parse_time, parse_datetime
from utils.text import clean_text, extract_price

API_BASE = "https://www.eventbriteapi.com/v3"

# Eventbrite category IDs for relevant categories
# Full list: GET /v3/categories/
EVENTBRITE_CATEGORIES = {
    "103": "music",         # Music
    "108": "sports",        # Sports & Fitness
    "110": "food",
    "113": "community",
    "105": "performing_arts",
    "107": "science",
}

SEARCH_CATEGORIES = "103,108,113,105"  # music, sports, performing arts, community


class EventbriteScraper(BaseScraper):
    source_name = "eventbrite"
    base_url = API_BASE

    def __init__(self):
        super().__init__()
        if settings.eventbrite_api_key:
            self.session.headers["Authorization"] = f"Bearer {settings.eventbrite_api_key}"

    def fetch(self) -> list[Event]:
        if not settings.eventbrite_api_key:
            self.logger.warning(
                "EVENTBRITE_API_KEY not set — Eventbrite scraper disabled. "
                "Get a key at https://www.eventbrite.com/platform/api"
            )
            return []

        events: list[Event] = []
        page = 1

        while True:
            data = self.get_json(
                f"{API_BASE}/events/search/",
                params={
                    "location.address": settings.eventbrite_location,
                    "location.within": settings.eventbrite_radius,
                    "categories": SEARCH_CATEGORIES,
                    "expand": "venue,organizer,ticket_classes",
                    "page": page,
                    "page_size": 50,
                    "sort_by": "date",
                    "start_date.keyword": "today",
                },
            )
            if not data or "events" not in data:
                break

            for raw in data["events"]:
                event = self._parse_event(raw)
                if event:
                    events.append(event)

            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items"):
                break
            if page >= 10:  # safety: max 500 events
                break
            page += 1

        return events

    # ------------------------------------------------------------------

    def _parse_event(self, raw: dict) -> Optional[Event]:
        try:
            title = clean_text(raw.get("name", {}).get("text", ""))
            if not title:
                return None

            start = raw.get("start", {})
            end = raw.get("end", {})

            raw_dt = start.get("utc") or start.get("local", "")
            event_date = parse_date(raw_dt)
            event_time = parse_time(raw_dt)
            datetime_iso = parse_datetime(raw_dt)

            venue_data = raw.get("venue", {}) or {}
            venue_name = clean_text(venue_data.get("name", ""))
            address_data = venue_data.get("address", {}) or {}
            city = address_data.get("city") or settings.default_region
            address = address_data.get("localized_address_display", "")

            desc_data = raw.get("description", {}) or {}
            full_desc = clean_text(desc_data.get("text", ""), max_len=1000)
            short_desc = clean_text(raw.get("summary", "") or desc_data.get("text", ""), max_len=300)

            image_url = None
            logo = raw.get("logo")
            if logo and isinstance(logo, dict):
                image_url = logo.get("url") or logo.get("original", {}).get("url")

            source_url = raw.get("url", "")

            # price from ticket_classes
            price = None
            currency = "EUR"
            is_free = raw.get("is_free", False)
            if is_free:
                price = 0.0
            else:
                tkt = (raw.get("ticket_classes") or [{}])[0]
                if tkt.get("cost"):
                    cost = tkt["cost"]
                    price = float(cost.get("value", 0)) / 100
                    currency = cost.get("currency", "EUR")

            online = raw.get("online_event", False)
            event_type = EventType.ONLINE if online else EventType.PHYSICAL

            category_id = str(raw.get("category_id", ""))
            # try to infer category from Eventbrite category + title
            category = categorize(title, short_desc or "", eb_category=EVENTBRITE_CATEGORIES.get(category_id, ""))

            tags = [sc.get("name", "") for sc in raw.get("subcategories", []) if sc.get("name")]

            return normalize_event(Event(
                id=Event.make_id(source_url=source_url),
                title=title,
                date=event_date,
                time=event_time,
                datetime_iso=datetime_iso,
                city=city,
                region=settings.default_region,
                venue=venue_name,
                address=address,
                short_description=short_desc,
                full_description=full_desc,
                source_name=self.source_name,
                source_url=source_url,
                image_url=image_url,
                price=price,
                currency=currency,
                event_type=event_type,
                category=category,
                tags=tags,
            ))

        except Exception as e:
            self.logger.warning("Failed to parse Eventbrite event: %s", e)
            return None
