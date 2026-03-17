"""
OpenClaw Bot Adapter.

This is the bridge between OpenClaw Bot and the events module.

HOW TO USE IN YOUR BOT:
========================

    from integrations.openclaw_adapter import EventsAdapter

    adapter = EventsAdapter()  # singleton, create once on bot startup

    # In a command handler:
    @bot.message_handler(commands=["events"])
    def cmd_events(message):
        events = adapter.handle_command("/events")
        bot.send_message(message.chat.id, adapter.format_for_telegram(events))

    # In a scheduler (APScheduler / aiocron / etc.):
    def scheduled_notify():
        adapter.notify_new_events(bot, chat_id)

INTEGRATION PATTERNS:
=====================
Pattern A — Library (recommended for monolith bots):
  Import EventsAdapter directly into your bot code.
  No separate process needed. Works with python-telegram-bot, aiogram, telebot.

Pattern B — Microservice (recommended for large bots):
  Run main.py --serve as a separate process / Docker container.
  Bot calls it via HTTP (FastAPI endpoint) or message queue (Redis/RabbitMQ).
  See _http_server_example() below for a FastAPI stub.

Pattern C — CLI + cron:
  Cron calls: python main.py --run-scrapers
  Bot reads from DB directly using EventsAdapter(refresh=False).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Optional

from config import settings
from models import Event, EventCategory
from services.event_service import EventService
from utils.logger import get_logger

logger = get_logger("openclaw_adapter")

# -------------------------------------------------------------------------
# Telegram message formatting limits
# -------------------------------------------------------------------------
MAX_EVENTS_PER_MESSAGE = 10
MAX_MESSAGE_LEN = 4000  # Telegram limit is 4096


class EventsAdapter:
    """
    Stateful adapter — holds a single EventService instance.
    Create one instance per bot startup, reuse across handlers.
    """

    def __init__(self, auto_refresh: bool = False):
        """
        auto_refresh=True: run scrapers on each command call (slow but fresh).
        auto_refresh=False: read from local DB (fast, use cron for updates).
        """
        self.service = EventService()
        self.auto_refresh = auto_refresh

    # ------------------------------------------------------------------
    # Command handlers — map bot commands to service calls
    # ------------------------------------------------------------------

    def handle_command(
        self,
        command: str,
        args: str = "",
    ) -> list[Event]:
        """
        Dispatch bot command to the right service method.
        Returns list of Event objects ready for formatting.

        Supported commands:
          /events [days]          — all events for N days (default 7)
          /concerts [days]        — concerts
          /running [days]         — running events
          /weekend                — this weekend
          /festivals              — upcoming festivals
          /sports                 — sports events
          /new                    — newly discovered events
        """
        cmd = command.lstrip("/").lower().strip()

        if self.auto_refresh:
            self.service.run_all_scrapers(save=True)

        days = self._parse_days_arg(args, default=7)

        dispatch = {
            "events":    lambda: self.service.get_events(days=days),
            "concerts":  lambda: self.service.get_concerts(days=days),
            "running":   lambda: self.service.get_running_events(days=max(days, 90)),
            "weekend":   lambda: self.service.get_weekend_events(),
            "festivals": lambda: self.service.get_festivals(days=max(days, 60)),
            "sports":    lambda: self.service.get_sports_events(days=days),
            "new":       lambda: self.service.get_new_events(),
        }

        handler = dispatch.get(cmd)
        if handler is None:
            logger.warning("Unknown command: %s", command)
            return []

        events = handler()
        logger.info("Command /%s → %d events", cmd, len(events))
        return events[:MAX_EVENTS_PER_MESSAGE]

    # ------------------------------------------------------------------
    # Formatting for Telegram
    # ------------------------------------------------------------------

    def format_for_telegram(
        self,
        events: list[Event],
        header: str = "",
        use_markdown: bool = True,
    ) -> str:
        """
        Format event list as a Telegram-ready message.
        Keeps under 4096 chars. Uses Markdown V2 by default.
        """
        if not events:
            return "Наразі подій не знайдено. Спробуйте пізніше."

        lines: list[str] = []
        if header:
            lines.append(f"*{self._escape_md(header)}*\n")

        for i, e in enumerate(events, 1):
            lines.append(self._format_event(e, index=i, use_markdown=use_markdown))

        text = "\n".join(lines)
        if len(text) > MAX_MESSAGE_LEN:
            text = text[:MAX_MESSAGE_LEN - 3] + "..."
        return text

    def format_single_event(self, event: Event) -> str:
        """Detailed view of a single event (for inline buttons, /event <id>)."""
        lines = [
            f"*{self._escape_md(event.title)}*",
            "",
        ]
        if event.date:
            date_str = event.date
            if event.time:
                date_str += f" о {event.time}"
            lines.append(f"📅 {date_str}")
        if event.venue:
            lines.append(f"📍 {self._escape_md(event.venue)}")
        if event.address:
            lines.append(f"🏠 {self._escape_md(event.address)}")
        if event.city:
            lines.append(f"🌍 {self._escape_md(event.city)}")
        if event.price is not None:
            price_str = "Безкоштовно" if event.price == 0 else f"{event.price} {event.currency}"
            lines.append(f"💶 {price_str}")
        if event.short_description:
            lines.append(f"\n_{self._escape_md(event.short_description)}_")
        if event.source_url:
            lines.append(f"\n[Детальніше →]({event.source_url})")
        return "\n".join(lines)

    def format_as_json(self, events: list[Event]) -> str:
        """Return events as JSON string (for API/webhook use cases)."""
        return json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Notification helpers (for scheduled sends)
    # ------------------------------------------------------------------

    def notify_new_events(self, bot, chat_id: str | int) -> int:
        """
        Check for new events and send them to chat_id.
        Returns number of messages sent.

        Example integration with python-telegram-bot:
            from telegram import Bot
            bot = Bot(token=settings.telegram_bot_token)
            adapter.notify_new_events(bot, settings.telegram_chat_id)

        Example integration with aiogram:
            from aiogram import Bot
            bot = Bot(token=settings.telegram_bot_token)
            await bot.send_message(chat_id, text)  # use async version below
        """
        new_events = self.service.get_new_events()
        if not new_events:
            logger.info("No new events to notify")
            return 0

        sent = 0
        # send in batches of MAX_EVENTS_PER_MESSAGE
        for i in range(0, len(new_events), MAX_EVENTS_PER_MESSAGE):
            batch = new_events[i : i + MAX_EVENTS_PER_MESSAGE]
            text = self.format_for_telegram(batch, header="🆕 Нові події в регіоні!")
            try:
                bot.send_message(
                    chat_id,
                    text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception as e:
                logger.error("Failed to send Telegram message: %s", e)

        return sent

    async def notify_new_events_async(self, bot, chat_id: str | int) -> int:
        """Async version for aiogram / python-telegram-bot v20+."""
        new_events = self.service.get_new_events()
        if not new_events:
            return 0

        sent = 0
        for i in range(0, len(new_events), MAX_EVENTS_PER_MESSAGE):
            batch = new_events[i : i + MAX_EVENTS_PER_MESSAGE]
            text = self.format_for_telegram(batch, header="🆕 Нові події в регіоні!")
            try:
                await bot.send_message(
                    chat_id,
                    text,
                    parse_mode="MarkdownV2",
                    disable_web_page_preview=True,
                )
                sent += 1
            except Exception as e:
                logger.error("Failed to send async Telegram message: %s", e)

        return sent

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _format_event(self, event: Event, index: int, use_markdown: bool = True) -> str:
        """Single-event compact format for a list view."""
        parts = [f"{index}. *{self._escape_md(event.title)}*"]

        meta = []
        if event.date:
            meta.append(f"📅 {event.date}")
        if event.time:
            meta.append(f"🕐 {event.time}")
        if event.venue:
            meta.append(f"📍 {self._escape_md(event.venue)}")
        if event.price is not None:
            meta.append("🆓" if event.price == 0 else f"💶 {event.price}{event.currency}")
        if meta:
            parts.append("  " + " | ".join(meta))
        if event.source_url:
            parts.append(f"  🔗 {event.source_url}")

        return "\n".join(parts)

    @staticmethod
    def _escape_md(text: str | None) -> str:
        """Escape special chars for Telegram MarkdownV2."""
        if not text:
            return ""
        special = r"\_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{c}" if c in special else c for c in text)

    @staticmethod
    def _parse_days_arg(args: str, default: int = 7) -> int:
        """Parse an integer days argument from a bot command string."""
        try:
            return int(args.strip().split()[0])
        except (ValueError, IndexError):
            return default


# -------------------------------------------------------------------------
# FastAPI microservice stub (Pattern B)
# Run with: uvicorn integrations.openclaw_adapter:app
# -------------------------------------------------------------------------

def _create_fastapi_app():
    """
    Optional HTTP API. Uncomment and use if running as a microservice.
    Install: pip install fastapi uvicorn
    """
    try:
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
    except ImportError:
        return None

    app = FastAPI(title="Events API", version="1.0")
    adapter = EventsAdapter()

    @app.get("/events")
    def get_events(days: int = 7, category: str = None, city: str = None):
        events = adapter.service.get_events(days=days, category=category, city=city)
        return [e.to_dict() for e in events]

    @app.get("/events/new")
    def get_new_events():
        events = adapter.service.get_new_events()
        return [e.to_dict() for e in events]

    @app.post("/events/refresh")
    def refresh_events():
        events = adapter.service.run_all_scrapers(save=True)
        return {"scraped": len(events)}

    @app.get("/events/{event_id}")
    def get_event(event_id: str):
        events = adapter.service.storage.load_events()
        for e in events:
            if e.id == event_id:
                return e.to_dict()
        return JSONResponse(status_code=404, content={"error": "Not found"})

    return app


# Uncomment to expose as microservice:
# app = _create_fastapi_app()
