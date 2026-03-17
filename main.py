"""
main.py — CLI entry point for the Events Scraper.

Usage:
    python main.py                        # run all scrapers, save, print summary
    python main.py --run-scrapers         # same as above
    python main.py --events --days 7      # print upcoming 7 days
    python main.py --category running     # print running events
    python main.py --new                  # print new events only
    python main.py --export events.json   # export DB → JSON
    python main.py --clean-old --days 90  # remove events older than 90 days

Cron example (every 6 hours):
    0 */6 * * * cd /path/to/project && python main.py --run-scrapers >> /var/log/events.log 2>&1
"""

from __future__ import annotations

import argparse
import json
import sys

from config import settings
from services.event_service import EventService
from utils.logger import get_logger

logger = get_logger("main")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Events scraper for Viana do Castelo region",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-scrapers", action="store_true", help="Run all scrapers and save results")
    parser.add_argument("--events", action="store_true", help="List upcoming events from storage")
    parser.add_argument("--new", action="store_true", help="Show only new events (not yet in DB)")
    parser.add_argument("--days", type=int, default=7, help="Number of days ahead (default: 7)")
    parser.add_argument("--category", type=str, default=None,
                        help="Filter by category: concert|running|sports|festival|culture|other")
    parser.add_argument("--city", type=str, default=None, help="Filter by city name")
    parser.add_argument("--export", type=str, default=None, metavar="FILE", help="Export events to JSON file")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument("--clean-old", action="store_true", help="Remove events older than N days")
    parser.add_argument("--serve", action="store_true", help="Start FastAPI HTTP server (requires fastapi+uvicorn)")
    return parser.parse_args()


def main():
    args = parse_args()
    service = EventService()

    # Default: run scrapers if no flag given
    if not any([args.run_scrapers, args.events, args.new, args.export, args.clean_old, args.serve]):
        args.run_scrapers = True

    if args.serve:
        _start_server()
        return

    if args.clean_old:
        removed = service.storage.delete_old_events(days=args.days)
        logger.info("Cleaned up %d old events", removed)
        print(f"Removed {removed} old events.")
        return

    if args.run_scrapers:
        events = service.run_all_scrapers(save=True)
        if args.json:
            print(json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2))
        else:
            print(f"\nScraped {len(events)} events total.\n")
            _print_summary(events)
        return

    if args.new:
        events = service.get_new_events()
        label = "New events"
    elif args.events:
        events = service.get_events(
            days=args.days,
            category=args.category,
            city=args.city,
        )
        label = f"Events (next {args.days} days)"
    else:
        events = []
        label = ""

    if args.export:
        service.storage.export_json(args.export, events if events else None)
        print(f"Exported to {args.export}")
        return

    if args.json:
        print(json.dumps([e.to_dict() for e in events], ensure_ascii=False, indent=2))
    else:
        print(f"\n{label}: {len(events)} events\n")
        _print_summary(events)


def _print_summary(events):
    if not events:
        print("  No events found.")
        return
    for e in events[:50]:
        date_str = e.date or "?"
        time_str = f" {e.time}" if e.time else ""
        venue_str = f" @ {e.venue}" if e.venue else ""
        price_str = ""
        if e.price is not None:
            price_str = f" [FREE]" if e.price == 0 else f" [{e.price}{e.currency}]"
        print(f"  [{e.category:10}] {date_str}{time_str}{venue_str} — {e.title}{price_str}")
        print(f"             {e.source_url}")
    if len(events) > 50:
        print(f"  ... and {len(events) - 50} more")


def _start_server():
    try:
        import uvicorn
        from integrations.openclaw_adapter import _create_fastapi_app
        app = _create_fastapi_app()
        if app is None:
            print("FastAPI not installed. Run: pip install fastapi uvicorn")
            sys.exit(1)
        uvicorn.run(app, host="0.0.0.0", port=8000)
    except ImportError:
        print("Missing dependencies. Run: pip install fastapi uvicorn")
        sys.exit(1)


if __name__ == "__main__":
    main()
