"""
Scraper for AquiHá (aquiha.pt).

AquiHá is a Portuguese local events aggregator.
The listing pages are server-side rendered HTML.

Target: https://www.aquiha.pt/viana-do-castelo

NOTE: HTML structure may change. Selectors below reflect the site
      as of early 2025. Update _parse_card() if layout changes.

Risk level: MEDIUM — HTML scraping, no API, no auth.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from config import settings
from models import Event
from scrapers.base import BaseScraper
from normalizer import categorize, normalize_event
from utils.dates import parse_date, parse_time
from utils.text import clean_text, normalize_url, extract_price

BASE_URL = "https://www.aquiha.pt"
REGION_SLUG = "viana-do-castelo"
SEARCH_URL = f"{BASE_URL}/{REGION_SLUG}"

CATEGORY_PATHS = [
    f"/{REGION_SLUG}",
    f"/{REGION_SLUG}/musica",
    f"/{REGION_SLUG}/desporto-e-aventura",
    f"/{REGION_SLUG}/festivais",
    f"/{REGION_SLUG}/teatro-e-cinema",
]


class AquiHaScraper(BaseScraper):
    source_name = "aquiha"
    base_url = BASE_URL

    def fetch(self) -> list[Event]:
        events: list[Event] = []
        seen_urls: set[str] = set()

        for path in CATEGORY_PATHS:
            url = BASE_URL + path
            page = 1

            while True:
                paged_url = f"{url}?page={page}" if page > 1 else url
                resp = self.get(paged_url)
                if not resp:
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                cards = self._find_cards(soup)

                if not cards:
                    break

                new_found = 0
                for card in cards:
                    event_url = self._get_card_url(card)
                    if event_url and event_url in seen_urls:
                        continue
                    if event_url:
                        seen_urls.add(event_url)

                    event = self._parse_card(card)
                    if event:
                        events.append(event)
                        new_found += 1

                if new_found == 0 or page >= 4:
                    break
                page += 1

        return events

    # ------------------------------------------------------------------

    def _find_cards(self, soup: BeautifulSoup) -> list[Tag]:
        selectors = [
            "div.event-card",
            "article.event",
            ".events-list .item",
            ".event-list-item",
            "li.event-entry",
        ]
        for sel in selectors:
            cards = soup.select(sel)
            if cards:
                return cards
        return []

    def _get_card_url(self, card: Tag) -> Optional[str]:
        a = card.find("a", href=True)
        if a:
            return urljoin(BASE_URL, a["href"])
        return None

    def _parse_card(self, card: Tag) -> Optional[Event]:
        try:
            title_el = (
                card.select_one("h2, h3, .event-title, .title")
                or card.find(["h2", "h3"])
            )
            title = clean_text(title_el.get_text()) if title_el else None
            if not title:
                return None

            # date + time
            date_el = card.select_one("time[datetime], .date, .event-date")
            raw_date = (
                date_el.get("datetime") or date_el.get_text()
                if date_el else None
            )
            event_date = parse_date(raw_date) if raw_date else None

            time_el = card.select_one(".time, .event-time, .hora")
            event_time = parse_time(time_el.get_text()) if time_el else None

            # location
            venue_el = card.select_one(".venue, .local, .location, address")
            venue = clean_text(venue_el.get_text()) if venue_el else None

            city_el = card.select_one(".city, .cidade")
            city = clean_text(city_el.get_text()) if city_el else settings.default_region

            address_el = card.select_one("address, .address, .morada")
            address = clean_text(address_el.get_text()) if address_el else None

            # description
            desc_el = card.select_one("p, .description, .descricao, .excerpt")
            short_desc = clean_text(desc_el.get_text(), max_len=300) if desc_el else None

            # image
            img_el = card.select_one("img[src], img[data-src]")
            image_url = normalize_url(
                img_el.get("data-src") or img_el.get("src") if img_el else None,
                BASE_URL,
            )

            # price
            price_el = card.select_one(".price, .preco, .ticket-price")
            price, currency = extract_price(
                clean_text(price_el.get_text()) if price_el else None
            )

            # tags
            tag_els = card.select(".tag, .category-tag, .badge")
            tags = [clean_text(t.get_text()) for t in tag_els if t.get_text().strip()]

            # source url
            a_el = card.find("a", href=True)
            source_url = urljoin(BASE_URL, a_el["href"]) if a_el else ""

            event = Event(
                id=Event.make_id(source_url=source_url, title=title, date=event_date or "", venue=venue or ""),
                title=title,
                date=event_date,
                time=event_time,
                datetime_iso=f"{event_date}T{event_time}:00" if event_date and event_time else event_date,
                city=city or settings.default_region,
                region=settings.default_region,
                venue=venue,
                address=address,
                short_description=short_desc,
                source_name=self.source_name,
                source_url=source_url,
                image_url=image_url,
                price=price,
                currency=currency,
                tags=[t for t in tags if t],
                category=categorize(title, short_desc or "", tags),
            )
            return normalize_event(event)

        except Exception as e:
            self.logger.warning("Failed to parse AquiHá card: %s", e)
            return None
