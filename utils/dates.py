"""
Date/time parsing utilities.
All public functions return ISO strings or None on failure.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Optional

import dateparser

# Portuguese month names → number
_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
    "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
    # abbreviated
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}


def parse_date(raw: str, settings_override: dict | None = None) -> Optional[str]:
    """
    Parse any date string -> ISO date string YYYY-MM-DD, or None.
    Fast-path for ISO 8601 formats, then dateparser, then manual PT fallback.
    """
    if not raw:
        return None

    raw = raw.strip()

    # Fast-path: ISO 8601 "2026-03-18", "2026-03-18T00:59:00+00:00", etc.
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    if iso_match:
        try:
            return date.fromisoformat(iso_match.group(1)).isoformat()
        except ValueError:
            pass

    # dateparser handles en/pt/fr and many formats
    dp_settings = {
        "PREFER_DAY_OF_MONTH": "first",
        "DATE_ORDER": "DMY",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "PREFER_DATES_FROM": "future",
    }
    if settings_override:
        dp_settings.update(settings_override)

    parsed = dateparser.parse(raw, languages=["pt", "en"], settings=dp_settings)
    if parsed:
        return parsed.date().isoformat()

    # manual fallback for "15 de marco de 2025" / "15 marco 2025"
    return _parse_pt_manual(raw)


def parse_datetime(raw: str) -> Optional[str]:
    """Parse datetime string -> ISO datetime string, or None."""
    if not raw:
        return None

    raw = raw.strip()

    # Fast-path: ISO 8601 with time component
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
        try:
            # strip timezone offset for naive datetime
            raw_naive = re.sub(r"[+-]\d{2}:\d{2}$|Z$", "", raw)
            return datetime.fromisoformat(raw_naive).isoformat(timespec="seconds")
        except ValueError:
            pass

    parsed = dateparser.parse(
        raw,
        languages=["pt", "en"],
        settings={
            "DATE_ORDER": "DMY",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DATES_FROM": "future",
        },
    )
    if parsed:
        return parsed.isoformat(timespec="seconds")
    return None


def parse_time(raw: str) -> Optional[str]:
    """Extract HH:MM from a time string."""
    if not raw:
        return None
    m = re.search(r"(\d{1,2}):(\d{2})", raw.strip())
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return None


def date_range(days: int = 7) -> tuple[str, str]:
    """Return (today_iso, end_iso) for the next N days."""
    today = date.today()
    end = today + timedelta(days=days)
    return today.isoformat(), end.isoformat()


def is_in_range(date_str: Optional[str], start: str, end: str) -> bool:
    """Check if date_str falls within [start, end] inclusive."""
    if not date_str:
        return False
    return start <= date_str[:10] <= end


def _parse_pt_manual(raw: str) -> Optional[str]:
    """Fallback: parse '15 de março de 2025' or '15/03/2025'."""
    raw_lower = raw.lower()

    # numeric: dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"(\d{1,2})[\/\-\.](\d{1,2})[\/\-\.](\d{4})", raw_lower)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    # "15 de março de 2025" or "15 março 2025"
    m = re.search(r"(\d{1,2})\s+(?:de\s+)?([a-zç]+)\s+(?:de\s+)?(\d{4})", raw_lower)
    if m:
        day, month_str, year = int(m.group(1)), m.group(2), int(m.group(3))
        month = _PT_MONTHS.get(month_str)
        if month:
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                pass
    return None
