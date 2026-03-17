"""
EventService — main orchestration layer.

This is the single entry point for:
  - running all scrapers
  - filtering, deduplicating
  - saving to storage
  - returning results to callers (bot, CLI, cron)

All public methods are synchronous and safe to call from any context.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from config import settings
from deduplicator import deduplicate, find_new_events
from models import Event, EventCategory
from storage import Storage
from utils.logger import get_logger

logger = get_logger("event_service")


class EventService:
    def __init__(self, storage: Optional[Storage] = None):
        self.storage = storage or Storage()
        self._scrapers = self._load_scrapers()

    # ------------------------------------------------------------------
    # Main API (these are the methods OpenClaw Bot will call)
    # ------------------------------------------------------------------

    def run_all_scrapers(self, save: bool = True) -> list[Event]:
        """
        Run all registered scrapers in sequence.
        Graceful: if one fails, others continue.
        Returns deduplicated list of all fetched events.
        """
        all_events: list[Event] = []

        for scraper in self._scrapers:
            events = scraper.run()  # never raises
            all_events.extend(events)
            logger.info("Collected %d events from %s", len(events), scraper.source_name)

        deduped = deduplicate(all_events)
        logger.info("Total after dedup: %d events", len(deduped))

        if save and deduped:
            self.save_events(deduped)

        return deduped

    def get_events(
        self,
        days: int = 7,
        category: Optional[str] = None,
        city: Optional[str] = None,
        source: Optional[str] = None,
        from_storage: bool = True,
    ) -> list[Event]:
        """
        Get events for the next N days.
        If from_storage=True, loads from DB (fast).
        If from_storage=False, runs scrapers live.
        """
        date_from = date.today().isoformat()
        date_to = (date.today() + timedelta(days=days)).isoformat()

        if from_storage:
            return self.storage.load_events(
                category=category,
                date_from=date_from,
                date_to=date_to,
                city=city,
                source=source,
            )

        events = self.run_all_scrapers(save=True)
        return self.filter_events(events, days=days, category=category, city=city)

    def get_new_events(self) -> list[Event]:
        """
        Run all scrapers and return only events not yet in storage.
        Useful for Telegram notifications: "send only new events".
        """
        known_ids = self.storage.get_known_ids()
        fresh = self.run_all_scrapers(save=False)
        new = find_new_events(fresh, known_ids)

        if new:
            self.save_events(new)
            logger.info("Found %d new events", len(new))
        else:
            logger.info("No new events found")

        return new

    def filter_events(
        self,
        events: list[Event],
        days: Optional[int] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> list[Event]:
        """
        Filter an in-memory list of events.
        Used after run_all_scrapers() or for bot command filtering.
        """
        result = events

        if days is not None:
            _from = date.today().isoformat()
            _to = (date.today() + timedelta(days=days)).isoformat()
            result = [e for e in result if e.date and _from <= e.date <= _to]
        elif date_from or date_to:
            if date_from:
                result = [e for e in result if e.date and e.date >= date_from]
            if date_to:
                result = [e for e in result if e.date and e.date <= date_to]

        if category:
            result = [e for e in result if e.category == category]

        if city:
            city_lower = city.lower()
            result = [
                e for e in result
                if (e.city and city_lower in e.city.lower())
                or (e.region and city_lower in e.region.lower())
            ]

        return sorted(result, key=lambda e: (e.date or "9999", e.title))

    def save_events(self, events: list[Event]) -> int:
        """Persist events to storage."""
        return self.storage.save_events(events)

    def export_json(self, path: Optional[str] = None) -> str:
        """Export all stored events to a JSON file."""
        return self.storage.export_json(path)

    # ------------------------------------------------------------------
    # Convenience shortcuts (used by bot commands)
    # ------------------------------------------------------------------

    def get_concerts(self, days: int = 30) -> list[Event]:
        return self.get_events(days=days, category=EventCategory.CONCERT)

    def get_running_events(self, days: int = 90) -> list[Event]:
        return self.get_events(days=days, category=EventCategory.RUNNING)

    def get_weekend_events(self) -> list[Event]:
        """Events from coming Saturday to Sunday."""
        today = date.today()
        days_to_saturday = (5 - today.weekday()) % 7 or 7
        saturday = today + timedelta(days=days_to_saturday)
        sunday = saturday + timedelta(days=1)
        return self.storage.load_events(
            date_from=saturday.isoformat(),
            date_to=sunday.isoformat(),
        )

    def get_festivals(self, days: int = 60) -> list[Event]:
        return self.get_events(days=days, category=EventCategory.FESTIVAL)

    def get_sports_events(self, days: int = 30) -> list[Event]:
        return self.get_events(days=days, category=EventCategory.SPORTS)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load_scrapers(self):
        """
        Import scrapers lazily so a broken import in one doesn't kill others.
        """
        scrapers = []
        scraper_classes = [
            ("scrapers.viralagenda", "ViralAgendaScraper"),
            ("scrapers.aquiha", "AquiHaScraper"),
            ("scrapers.eventbrite", "EventbriteScraper"),
            ("scrapers.bandsintown", "BandsintownScraper"),
        ]
        for module_path, class_name in scraper_classes:
            try:
                import importlib
                module = importlib.import_module(module_path)
                cls = getattr(module, class_name)
                scrapers.append(cls())
            except Exception as e:
                logger.error("Could not load scraper %s.%s: %s", module_path, class_name, e)
        return scrapers
