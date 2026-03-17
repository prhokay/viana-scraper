"""
Text cleaning and normalization utilities.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


def clean_text(text: Optional[str], max_len: int = 0) -> Optional[str]:
    """
    Strip HTML tags, collapse whitespace, optionally truncate.
    Returns None if input is None or empty after cleaning.
    """
    if not text:
        return None

    # remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # decode common HTML entities
    text = (text
            .replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
            .replace("&nbsp;", " "))
    # collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None
    if max_len and len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def truncate(text: Optional[str], max_len: int = 200) -> Optional[str]:
    if not text:
        return None
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "…"


def slugify(text: str) -> str:
    """Convert text to ASCII slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")


def extract_price(text: Optional[str]) -> tuple[Optional[float], str]:
    """
    Try to extract a numeric price and currency from a text string.
    Returns (price_float, currency_str) or (None, "EUR").
    Examples: "Free" → (0.0, "EUR"), "€10" → (10.0, "EUR"), "10 EUR" → (10.0, "EUR")
    """
    if not text:
        return None, "EUR"

    lower = text.lower().strip()
    if lower in {"free", "gratuito", "grátis", "gratis", "entrada livre", "entrada gratuita"}:
        return 0.0, "EUR"

    # currency symbols
    currency = "EUR"
    if "$" in text:
        currency = "USD"
    elif "£" in text:
        currency = "GBP"

    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", text.replace(",", "."))
    if m:
        try:
            return float(m.group(1)), currency
        except ValueError:
            pass
    return None, currency


def normalize_url(url: Optional[str], base: str = "") -> Optional[str]:
    """Make relative URL absolute."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if base:
        return base.rstrip("/") + "/" + url.lstrip("/")
    return url
