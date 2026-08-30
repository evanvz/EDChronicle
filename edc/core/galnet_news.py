"""GalNet news -- Frontier's official in-game lore news feed. Latest
headline only (no scrolling ticker, no archive) -- static display of
whatever's currently newest.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

_NEWS_URL = (
    "https://cms.zaonce.net/en-GB/jsonapi/node/galnet_article"
    "?page[limit]=1&sort=-published_at"
)
_TIMEOUT = 10
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


def fetch_latest_headline() -> Optional[str]:
    """Returns the newest GalNet article's title, or None on any failure
    (network error, bad response shape, empty result). Synchronous --
    call from a worker thread, never the UI thread."""
    try:
        resp = requests.get(_NEWS_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("GalNet news fetch failed: %s", exc)
        return None

    articles = data.get("data") if isinstance(data, dict) else None
    if not isinstance(articles, list) or not articles:
        return None
    first = articles[0]
    if not isinstance(first, dict):
        return None
    attrs = first.get("attributes")
    if not isinstance(attrs, dict):
        return None
    title = attrs.get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None
