"""
Announcement watcher — polls the Marcionite Church News RSS feed.

Pure helper module: no Discord or bot imports. bot.py calls fetch_feed()
on a schedule and decides what to post.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import TypedDict

import feedparser
import requests

FEED_URL = "https://marcionitechurchofchrist.org/category/news/feed/"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


class Article(TypedDict, total=False):
    url: str
    title: str
    summary: str
    author: str
    published_iso: str  # ISO 8601 UTC, or "" if missing
    published_ts: int   # epoch seconds, or 0 if missing


def _entry_to_article(entry) -> Article | None:
    url = (entry.get("link") or "").strip()
    title = (entry.get("title") or "").strip()
    if not url or not title:
        return None
    summary = (entry.get("summary") or "").strip()
    author = (entry.get("author") or "").strip()

    published_ts = 0
    published_iso = ""
    pp = entry.get("published_parsed")
    if pp:
        try:
            published_ts = calendar.timegm(pp)  # UTC struct_time -> epoch
            published_iso = datetime.fromtimestamp(published_ts, tz=timezone.utc).isoformat()
        except Exception:
            pass

    return Article(
        url=url,
        title=title,
        summary=summary,
        author=author,
        published_iso=published_iso,
        published_ts=published_ts,
    )


def fetch_feed(url: str = FEED_URL, timeout: int = 30) -> list[Article]:
    """Fetch and parse the news feed. Returns list of Articles, oldest-first.

    Raises requests.HTTPError on a non-2xx HTTP response. Returns [] on a
    parser-bozo response with no usable entries (logs to stderr-ish, doesn't
    crash the caller's task loop).
    """
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()

    # Pass bytes (not URL) to feedparser — feeding the URL would re-fetch with
    # the default User-Agent and 415, and feeding a path can break Expat.
    parsed = feedparser.parse(resp.content)
    if parsed.get("bozo") and not parsed.get("entries"):
        print(f"[announcements] Feed bozo with no entries: {parsed.get('bozo_exception')!r}")
        return []

    articles: list[Article] = []
    for entry in parsed.get("entries", []):
        art = _entry_to_article(entry)
        if art:
            articles.append(art)
    # Sort oldest-first so callers post in chronological order.
    articles.sort(key=lambda a: a.get("published_ts", 0))
    return articles
