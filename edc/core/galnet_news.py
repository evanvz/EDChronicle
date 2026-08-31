"""GalNet news -- Frontier's official in-game lore news feed. Static
display of the last few headlines, paged one at a time (matching the
in-game "Local News" panel's own last-5, page-at-a-time behavior) --
no scrolling ticker, no archive.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import requests

log = logging.getLogger(__name__)

_NEWS_URL_FMT = (
    "https://cms.zaonce.net/en-GB/jsonapi/node/galnet_article"
    "?page[limit]={limit}&sort=-published_at"
)
_ARTICLE_URL_FMT = "https://community.elitedangerous.com/en/galnet/uid/{guid}"
_TIMEOUT = 10
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"
_DEFAULT_LIMIT = 5


def fetch_latest_headlines(limit: int = _DEFAULT_LIMIT) -> List[Tuple[str, Optional[str]]]:
    """Returns up to `limit` (title, article_url) pairs, newest first, or
    an empty list on any failure (network error, bad response shape, empty
    result). article_url is None for an article with no field_galnet_guid
    to build the community-site link from -- its title is still returned.
    Synchronous -- call from a worker thread, never the UI thread."""
    try:
        resp = requests.get(
            _NEWS_URL_FMT.format(limit=limit), headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("GalNet news fetch failed: %s", exc)
        return []

    articles = data.get("data") if isinstance(data, dict) else None
    if not isinstance(articles, list):
        return []

    out: List[Tuple[str, Optional[str]]] = []
    for article in articles:
        if not isinstance(article, dict):
            continue
        attrs = article.get("attributes")
        if not isinstance(attrs, dict):
            continue
        title = attrs.get("title")
        if not (isinstance(title, str) and title.strip()):
            continue
        guid = attrs.get("field_galnet_guid")
        url = _ARTICLE_URL_FMT.format(guid=guid) if isinstance(guid, str) and guid.strip() else None
        out.append((title.strip(), url))
    return out
