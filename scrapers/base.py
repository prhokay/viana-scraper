"""
Abstract base scraper.
All scrapers inherit from BaseScraper and implement fetch().
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import settings
from models import Event
from utils.logger import get_logger


class BaseScraper(ABC):
    """
    Provides:
    - requests.Session with retry + timeout
    - rate-limit delay
    - structured logging
    - graceful error handling
    """

    source_name: str = "unknown"
    base_url: str = ""

    def __init__(self):
        self.logger = get_logger(f"scraper.{self.source_name}")
        self.session = self._build_session()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(self) -> list[Event]:
        """
        Entry point. Returns events or empty list on failure.
        Never raises — caller can always continue with other scrapers.
        """
        self.logger.info("Starting scraper: %s", self.source_name)
        try:
            events = self.fetch()
            self.logger.info("Scraped %d events from %s", len(events), self.source_name)
            return events
        except Exception as exc:
            self.logger.error("Scraper %s failed: %s", self.source_name, exc, exc_info=True)
            return []

    @abstractmethod
    def fetch(self) -> list[Event]:
        """Must be implemented by each scraper. Should return List[Event]."""
        ...

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def get(self, url: str, params: dict | None = None, **kwargs) -> Optional[requests.Response]:
        """GET with timeout and error logging. Returns None on failure."""
        try:
            self.logger.debug("GET %s params=%s", url, params)
            resp = self.session.get(
                url,
                params=params,
                timeout=settings.request_timeout,
                **kwargs,
            )
            resp.raise_for_status()
            self._rate_limit()
            return resp
        except requests.exceptions.HTTPError as e:
            self.logger.warning("HTTP error for %s: %s", url, e)
        except requests.exceptions.ConnectionError as e:
            self.logger.warning("Connection error for %s: %s", url, e)
        except requests.exceptions.Timeout:
            self.logger.warning("Timeout for %s", url)
        except Exception as e:
            self.logger.error("Unexpected error for %s: %s", url, e)
        return None

    def get_json(self, url: str, params: dict | None = None, **kwargs) -> Optional[dict | list]:
        """GET and parse JSON. Returns None on failure."""
        resp = self.get(url, params=params, **kwargs)
        if resp is None:
            return None
        try:
            return resp.json()
        except Exception as e:
            self.logger.error("JSON parse error for %s: %s", url, e)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        retry = Retry(
            total=settings.request_retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _rate_limit(self):
        time.sleep(settings.request_delay)
