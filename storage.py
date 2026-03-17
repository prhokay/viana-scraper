"""
Storage layer: SQLite (default) and JSON export.

SQLite schema is simple and maps 1:1 to the Event model.
Designed for easy migration to Postgres later (see note below).

Migration to Postgres:
  - Replace sqlite3 with psycopg2 or asyncpg
  - Change _CREATE_TABLE to use SERIAL/BIGSERIAL instead of INTEGER PRIMARY KEY
  - Use %s placeholders instead of ?
  - The rest of the logic stays the same
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from config import settings
from models import Event
from utils.logger import get_logger

logger = get_logger("storage")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    date            TEXT,
    time            TEXT,
    datetime_iso    TEXT,
    city            TEXT,
    region          TEXT,
    venue           TEXT,
    address         TEXT,
    category        TEXT,
    tags            TEXT,      -- JSON array stored as string
    short_description TEXT,
    full_description TEXT,
    source_name     TEXT,
    source_url      TEXT,
    image_url       TEXT,
    price           REAL,
    currency        TEXT,
    event_type      TEXT,
    scraped_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_name);
"""


class Storage:
    def __init__(self, db_path: Optional[str] = None, json_path: Optional[str] = None):
        self.db_path = db_path or settings.sqlite_path
        self.json_path = json_path or settings.json_path
        # Keep a persistent connection for :memory: (new conn = new empty DB)
        self._mem_conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_events(self, events: list[Event]) -> int:
        """
        Upsert events. Returns count of newly inserted (not updated) rows.
        Filter is applied BEFORE save: only future/recent events are kept.
        """
        if not events:
            return 0

        if settings.storage_backend == "json":
            return self._save_json(events)
        return self._save_sqlite(events)

    def load_events(
        self,
        category: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        city: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 500,
    ) -> list[Event]:
        """Load events from storage with optional filtering."""
        if settings.storage_backend == "json":
            return self._load_json(category=category, date_from=date_from, date_to=date_to)

        return self._load_sqlite(
            category=category,
            date_from=date_from,
            date_to=date_to,
            city=city,
            source=source,
            limit=limit,
        )

    def get_known_ids(self) -> set[str]:
        """Return all stored event IDs — used for new-event detection."""
        if settings.storage_backend == "json":
            return {e.id for e in self._load_json()}

        with self._connect() as conn:
            rows = conn.execute("SELECT id FROM events").fetchall()
            return {row[0] for row in rows}

    def export_json(self, path: Optional[str] = None, events: Optional[list[Event]] = None) -> str:
        """Export events to a JSON file. Returns the path written."""
        out_path = path or self.json_path
        if events is None:
            events = self.load_events()
        data = [e.to_dict() for e in events]
        Path(out_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Exported %d events to %s", len(data), out_path)
        return out_path

    def delete_old_events(self, days: int = 90) -> int:
        """Remove events older than N days. Returns deleted count."""
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=days)).isoformat()

        if settings.storage_backend == "json":
            all_events = self._load_json()
            kept = [e for e in all_events if not e.date or e.date >= cutoff]
            self._save_json(kept, overwrite=True)
            return len(all_events) - len(kept)

        with self._connect() as conn:
            cur = conn.execute("DELETE FROM events WHERE date < ?", (cutoff,))
            conn.commit()
            return cur.rowcount

    # ------------------------------------------------------------------
    # SQLite internals
    # ------------------------------------------------------------------

    def _init_db(self):
        if settings.storage_backend != "sqlite":
            return
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.executescript(_CREATE_TABLE)
            self._mem_conn.commit()
        else:
            with self._connect() as conn:
                conn.executescript(_CREATE_TABLE)
                conn.commit()
        logger.debug("SQLite initialized: %s", self.db_path)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        if self._mem_conn is not None:
            # reuse the single in-memory connection
            yield self._mem_conn
            return
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _save_sqlite(self, events: list[Event]) -> int:
        inserted = 0
        with self._connect() as conn:
            for e in events:
                row = e.to_dict()
                row["tags"] = json.dumps(row.get("tags", []), ensure_ascii=False)
                existing = conn.execute("SELECT id FROM events WHERE id = ?", (e.id,)).fetchone()
                if existing:
                    # update — keep scraped_at of first insert for stable tracking
                    conn.execute(
                        """UPDATE events SET title=:title, date=:date, time=:time,
                           datetime_iso=:datetime_iso, city=:city, region=:region,
                           venue=:venue, address=:address, category=:category, tags=:tags,
                           short_description=:short_description, full_description=:full_description,
                           source_name=:source_name, source_url=:source_url, image_url=:image_url,
                           price=:price, currency=:currency, event_type=:event_type
                           WHERE id=:id""",
                        row,
                    )
                else:
                    conn.execute(
                        """INSERT INTO events VALUES (
                           :id,:title,:date,:time,:datetime_iso,:city,:region,:venue,:address,
                           :category,:tags,:short_description,:full_description,:source_name,
                           :source_url,:image_url,:price,:currency,:event_type,:scraped_at)""",
                        row,
                    )
                    inserted += 1
            conn.commit()
        logger.info("SQLite: saved %d events (%d new)", len(events), inserted)
        return inserted

    def _load_sqlite(
        self,
        category=None, date_from=None, date_to=None,
        city=None, source=None, limit=500,
    ) -> list[Event]:
        clauses = []
        params: list = []

        if category:
            clauses.append("category = ?")
            params.append(category)
        if date_from:
            clauses.append("date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("date <= ?")
            params.append(date_to)
        if city:
            clauses.append("city LIKE ?")
            params.append(f"%{city}%")
        if source:
            clauses.append("source_name = ?")
            params.append(source)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM events {where} ORDER BY date ASC, title ASC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_event(dict(row)) for row in rows]

    @staticmethod
    def _row_to_event(row: dict) -> Event:
        if isinstance(row.get("tags"), str):
            try:
                row["tags"] = json.loads(row["tags"])
            except (json.JSONDecodeError, TypeError):
                row["tags"] = []
        return Event(**{k: v for k, v in row.items() if v is not None or k in {"id", "title", "source_url"}})

    # ------------------------------------------------------------------
    # JSON backend
    # ------------------------------------------------------------------

    def _save_json(self, events: list[Event], overwrite: bool = False) -> int:
        path = Path(self.json_path)
        existing: dict[str, dict] = {}

        if not overwrite and path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                existing = {e["id"]: e for e in raw if "id" in e}
            except Exception:
                pass

        inserted = 0
        for e in events:
            if e.id not in existing:
                inserted += 1
            existing[e.id] = e.to_dict()

        path.write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("JSON: saved %d events (%d new) to %s", len(events), inserted, path)
        return inserted

    def _load_json(
        self,
        category=None, date_from=None, date_to=None,
    ) -> list[Event]:
        path = Path(self.json_path)
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to load JSON: %s", e)
            return []

        events = []
        for item in raw:
            try:
                e = Event(**item)
                if category and e.category != category:
                    continue
                if date_from and e.date and e.date < date_from:
                    continue
                if date_to and e.date and e.date > date_to:
                    continue
                events.append(e)
            except Exception:
                continue
        return sorted(events, key=lambda x: (x.date or "", x.title))
