"""
Scraper for ViralAgenda (viralagenda.com).

Site: https://www.viralagenda.com/pt/viana-do-castelo
Structure: server-rendered HTML, no JS rendering needed.

HTML card selector: li.viral-event
Date: data-date-start attribute (ISO datetime — very clean!)
Time: .viral-event-hour (may be "N/D")
Title: .viral-event-title a
City: a.node-name span
Venue: .viral-event-place span
Categories: .viral-event-box-cat a
Image: img[src] inside .viral-event-image

Risk level: LOW-MEDIUM — stable HTML structure, clear selectors.
Rate limit: be respectful, 1.5s delay between requests.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from config import settings
from models import Event
from scrapers.base import BaseScraper
from normalizer import categorize, normalize_event
from utils.dates import parse_date, parse_time, parse_datetime
from utils.text import clean_text

BASE_URL = "https://www.viralagenda.com"
REGION_URL = f"{BASE_URL}/pt/viana-do-castelo"

# Category sub-pages on ViralAgenda (verified 200 OK, Mar 2026)
CATEGORY_PATHS = [
    "/pt/viana-do-castelo",           # all events
    "/pt/viana-do-castelo/concerts",
    "/pt/viana-do-castelo/sports",
    "/pt/viana-do-castelo/festivals",
    "/pt/viana-do-castelo/tradition",
    "/pt/viana-do-castelo/cinema-video",
    "/pt/viana-do-castelo/literature",
    "/pt/viana-do-castelo/meetings",
]

MAX_PAGES = 3  # max pages per category path


class ViralAgendaScraper(BaseScraper):
    source_name = "viralagenda"
    base_url = BASE_URL

    def fetch(self) -> list[Event]:
        events: list[Event] = []
        seen_ids: set[str] = set()

        for path in CATEGORY_PATHS:
            url = BASE_URL + path
            page = 1

            while True:
                paged_url = f"{url}?page={page}" if page > 1 else url
                resp = self.get(paged_url)
                if not resp:
                    break

                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select("li.viral-event")

                if not cards:
                    break

                new_found = 0
                for card in cards:
                    # use data-id for fast dedup before full parse
                    card_id = card.get("data-id")
                    if card_id and card_id in seen_ids:
                        continue
                    if card_id:
                        seen_ids.add(card_id)

                    event = self._parse_card(card)
                    if event:
                        events.append(event)
                        new_found += 1

                if new_found == 0 or page >= MAX_PAGES:
                    break
                page += 1

        return events

    # ------------------------------------------------------------------

    def _parse_card(self, card: Tag) -> Optional[Event]:
        try:
            # Title
            title_el = card.select_one(".viral-event-title a span, .viral-event-title a")
            title = clean_text(title_el.get_text()) if title_el else None
            if not title:
                # fallback: aria-label on the link
                link = card.select_one("a.viral-linked[aria-label]")
                title = link.get("aria-label") if link else None
            if not title:
                return None

            # Date — ISO datetime directly in data-date-start attribute
            raw_date_start = card.get("data-date-start", "")
            event_date = parse_date(raw_date_start) if raw_date_start else None
            datetime_iso = parse_datetime(raw_date_start) if raw_date_start else None

            # Time — .viral-event-hour (may be "N/D")
            time_el = card.select_one(".viral-event-hour")
            raw_time = time_el.get_text(strip=True) if time_el else None
            event_time = None
            if raw_time and raw_time.lower() not in {"n/d", "nd", "tbd", ""}:
                event_time = parse_time(raw_time)

            # City — .node-name span (municipality)
            city_el = card.select_one("a.node-name span, .node-name span")
            city = clean_text(city_el.get_text()) if city_el else settings.default_region

            # Venue — .viral-event-place span
            venue_el = card.select_one(".viral-event-place span, .viral-event-place")
            venue = clean_text(venue_el.get_text()) if venue_el else None

            # Source URL — data-url attribute (relative)
            data_url = card.get("data-url", "")
            source_url = urljoin(BASE_URL, data_url) if data_url else ""

            # Image
            img_el = card.select_one(".viral-event-image img[src]")
            image_url = img_el.get("src") if img_el else None
            if not image_url:
                # try data-img on the div
                img_div = card.select_one(".viral-event-image[data-img]")
                image_url = img_div.get("data-img") if img_div else None

            # Categories / tags from .viral-event-box-cat links
            cat_els = card.select(".viral-event-box-cat a")
            tags = [clean_text(c.get_text()) for c in cat_els if c.get_text(strip=True)]
            tags = [t for t in tags if t]

            event = Event(
                id=Event.make_id(
                    source_url=source_url,
                    title=title,
                    date=event_date or "",
                    venue=venue or "",
                ),
                title=title,
                date=event_date,
                time=event_time,
                datetime_iso=datetime_iso,
                city=city or settings.default_region,
                region=settings.default_region,
                venue=venue,
                source_name=self.source_name,
                source_url=source_url,
                image_url=image_url,
                tags=tags,
                category=categorize(title, " ".join(tags)),
            )
            return normalize_event(event)

        except Exception as e:
            self.logger.warning("Failed to parse ViralAgenda card: %s", e)
            return None
