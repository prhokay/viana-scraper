"""
Event deduplication.

Strategy:
  1. Hard dedup by event.id (sha256 hash of URL or title+date+venue)
  2. Soft dedup by title similarity + same date (catches same event from 2 sources)

The deduplicator is stateless — pass it a list of events, get back unique events.
For cross-run dedup (new vs. already saved), see storage.py.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from models import Event
from utils.logger import get_logger

logger = get_logger("deduplicator")

# Similarity threshold: 0.80 means 80% similar titles on the same date -> duplicate
TITLE_SIMILARITY_THRESHOLD = 0.80


def deduplicate(events: list[Event]) -> list[Event]:
    """
    Remove duplicates from a list of events.
    Preserves order (first occurrence wins).
    """
    if not events:
        return []

    # Step 1: hard dedup by id
    seen_ids: set[str] = set()
    after_id: list[Event] = []
    for e in events:
        if e.id not in seen_ids:
            seen_ids.add(e.id)
            after_id.append(e)

    hard_removed = len(events) - len(after_id)
    if hard_removed:
        logger.debug("Hard dedup removed %d events (same id)", hard_removed)

    # Step 2: soft dedup by title similarity + date
    result: list[Event] = []
    for event in after_id:
        if not _is_soft_duplicate(event, result):
            result.append(event)

    soft_removed = len(after_id) - len(result)
    if soft_removed:
        logger.debug("Soft dedup removed %d events (similar title+date)", soft_removed)

    logger.info(
        "Dedup: %d in -> %d out (removed %d duplicates)",
        len(events), len(result), len(events) - len(result),
    )
    return result


def find_new_events(fresh: list[Event], known_ids: set[str]) -> list[Event]:
    """
    Given a fresh batch and a set of already-seen IDs,
    return only events not in known_ids.
    """
    new = [e for e in fresh if e.id not in known_ids]
    logger.info("New events: %d out of %d", len(new), len(fresh))
    return new


# --------------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------------

def _normalize_title(title: str) -> str:
    """Lowercase, remove accents, remove punctuation for fuzzy comparison."""
    title = title.lower()
    title = unicodedata.normalize("NFKD", title)
    title = title.encode("ascii", "ignore").decode("ascii")
    title = re.sub(r"[^\w\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _title_similarity(a: str, b: str) -> float:
    na, nb = _normalize_title(a), _normalize_title(b)
    return SequenceMatcher(None, na, nb).ratio()


def _is_soft_duplicate(event: Event, existing: list[Event]) -> bool:
    """
    Returns True if event appears to be a duplicate of any in existing.
    Matching criteria: same date AND high title similarity.
    """
    for ex in existing:
        # must have same date (or both None) to be considered dup
        if event.date != ex.date:
            continue
        sim = _title_similarity(event.title, ex.title)
        if sim >= TITLE_SIMILARITY_THRESHOLD:
            logger.debug(
                "Soft dup (sim=%.2f): '%s' ≈ '%s'", sim, event.title, ex.title
            )
            return True
    return False
