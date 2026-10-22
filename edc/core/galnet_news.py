# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""GalNet news -- Frontier's official in-game lore news feed. Static
display of the last few headlines, paged one at a time (matching the
in-game "Local News" panel's own last-5, page-at-a-time behavior) --
no scrolling ticker, no archive.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import requests

from edc.version import USER_AGENT

log = logging.getLogger(__name__)

_NEWS_URL_FMT = (
    "https://cms.zaonce.net/en-GB/jsonapi/node/galnet_article"
    "?page[limit]={limit}&sort=-published_at"
)
_ARTICLE_URL_FMT = "https://community.elitedangerous.com/en/galnet/uid/{guid}"
_TIMEOUT = 10
_USER_AGENT = USER_AGENT
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


_FRONTIER_URL_FMT = (
    "https://cms.zaonce.net/en-GB/jsonapi/node/{kind}?sort=-published_at&page[limit]=3"
    "&filter[t][condition][path]=title&filter[t][condition][operator]=CONTAINS"
    "&filter[t][condition][value]=Elite%20Dangerous"
)
_SITE = "https://www.elitedangerous.com"
NOTICE_DAYS = 14


def fetch_frontier_notices(days: int = NOTICE_DAYS, now: Optional[datetime] = None) -> List[Tuple[str, Optional[str]]]:
    """Frontier's own Elite Dangerous patch notes and dev logs from the last
    `days` (same CMS as GalNet; it serves every Frontier game, hence the title
    filter) -- so game changes that may affect the app don't go unnoticed.
    (title, url) pairs, newest first; [] on any failure. Synchronous."""
    now = now or datetime.now(timezone.utc)
    out = []
    for kind in ("game_update", "news_article"):
        try:
            resp = requests.get(_FRONTIER_URL_FMT.format(kind=kind), headers={"User-Agent": _USER_AGENT},
                                timeout=_TIMEOUT)
            resp.raise_for_status()
            items = resp.json().get("data") or []
        except Exception as exc:
            log.warning("Frontier %s fetch failed: %s", kind, exc)
            continue
        for item in items:
            a = item.get("attributes") if isinstance(item, dict) else None
            if not isinstance(a, dict) or not isinstance(a.get("title"), str):
                continue
            try:
                published = datetime.fromisoformat(str(a.get("published_at") or a.get("created")))
            except ValueError:
                continue
            if now - published > timedelta(days=days) or published > now:
                continue   # old, or scheduled and not out yet
            version = a.get("field_version")
            if isinstance(version, dict):   # formatted-text field: {"value": "4.4.2.0", ...}
                version = version.get("value")
            version = version.strip() if isinstance(version, str) else ""
            if kind == "game_update":
                title = f"Update notes{' ' + version if version else ''}: {a['title']}"
                url = f"{_SITE}/news/updates/{version.replace('.', '-')}" if version else f"{_SITE}/news/updates"
            else:
                title = f"Frontier news: {a['title']}"
                url = f"{_SITE}/news/{a['field_slug']}" if a.get("field_slug") else None
            out.append((published, f"{title} ({published:%m-%d})", url))
    return [(t, u) for _p, t, u in sorted(out, key=lambda x: x[0], reverse=True)]
