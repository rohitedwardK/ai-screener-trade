"""RSS news fetcher for the MarketContextAgent.

Pulls Indian-market headlines from the `NEWS_RSS_FEEDS` URLs (default:
MoneyControl + ET Markets) and returns a flat, deduped list sorted by
recency. Cached for 5 minutes in-process so a fast-monitor tick does not
hammer the upstream feeds.

Per-feed failures are silently swallowed (logged at WARNING) — one slow
or 503ing feed must not block the entire briefing.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import feedparser

from ..config import get_settings

log = logging.getLogger(__name__)

# 5 minutes — RSS feeds rarely refresh faster than this and the agent layer
# only needs "recent context", not real-time news.
_CACHE_TTL_SECONDS = 300.0


@dataclass(frozen=True)
class NewsHeadline:
    """One feed entry, minimised to what the agent prompt actually consumes."""

    title: str
    link: str
    source: str
    published: Optional[str]


_lock = threading.Lock()
_cached: List[NewsHeadline] = []
_cached_at: float = 0.0


def _source_label(url: str) -> str:
    """`https://www.moneycontrol.com/...` -> `moneycontrol.com`."""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return "rss"
    return netloc.removeprefix("www.") or "rss"


def _parse_feed(url: str, *, max_entries: int) -> List[NewsHeadline]:
    """Best-effort fetch of one feed. Returns [] on any error."""
    try:
        parsed = feedparser.parse(url)
    except Exception:  # noqa: BLE001 — defensive; feedparser usually swallows errors itself
        log.warning("RSS parse raised for %s", url, exc_info=True)
        return []
    if getattr(parsed, "bozo", False) and not getattr(parsed, "entries", None):
        log.warning("RSS feed empty / malformed: %s", url)
        return []

    label = _source_label(url)
    out: List[NewsHeadline] = []
    for entry in (parsed.entries or [])[:max_entries]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = (
            entry.get("published")
            or entry.get("updated")
            or entry.get("pubDate")
            or None
        )
        out.append(NewsHeadline(title=title, link=link, source=label, published=published))
    return out


def _fetch_all(per_feed: int) -> List[NewsHeadline]:
    settings = get_settings()
    seen: set[Tuple[str, str]] = set()
    merged: List[NewsHeadline] = []
    for url in settings.news_rss_feed_list:
        for entry in _parse_feed(url, max_entries=per_feed):
            key = (entry.title.lower(), entry.source)
            if key in seen:
                continue
            seen.add(key)
            merged.append(entry)
    return merged


def fetch_headlines(limit: int = 10, *, force: bool = False) -> List[NewsHeadline]:
    """Return up to `limit` recent headlines across all configured feeds.

    Honours the 5-minute in-process cache. `force=True` bypasses it (used
    by the manual `/v1/agents/run-deep-cycle` trigger).
    """
    global _cached, _cached_at
    now = time.monotonic()

    with _lock:
        cache_fresh = _cached and (now - _cached_at) < _CACHE_TTL_SECONDS
        if not force and cache_fresh:
            return list(_cached[:limit])

    # Pull a few extra per feed because we'll dedupe and possibly trim.
    per_feed = max(limit, 8)
    fetched = _fetch_all(per_feed=per_feed)

    with _lock:
        _cached = fetched
        _cached_at = time.monotonic()

    return fetched[:limit]


def reset_cache() -> None:
    """Test hook so pytest fixtures can clear in-process state."""
    global _cached, _cached_at
    with _lock:
        _cached = []
        _cached_at = 0.0


__all__ = [
    "NewsHeadline",
    "fetch_headlines",
    "reset_cache",
]
