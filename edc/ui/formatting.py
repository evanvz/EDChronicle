from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional, Tuple


def relative_time(iso_str: str) -> Tuple[str, float]:
    """Returns (display text, age in seconds) for an ISO-8601 timestamp —
    "3h ago" instead of a raw timestamp is what's actually useful at a
    glance; age in seconds doubles as a sort key so a column sorts by
    actual recency, not alphabetically. The older the data, the more
    likely a BGS/security/faction shift has made it stale or wrong —
    always show this next to anything sourced from a past visit or sighting."""
    if not iso_str:
        return "—", float("inf")
    try:
        ts = iso_str.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        if age < 3600:
            mins = int(age // 60)
            return (f"{mins}m ago" if mins > 0 else "just now"), age
        if age < 86400:
            return f"{int(age // 3600)}h ago", age
        return f"{int(age // 86400)}d ago", age
    except (ValueError, TypeError):
        return iso_str, float("inf")


def bounty_age_days(commit_ts: str) -> Optional[float]:
    """Age in days since a bounty/fine's CommitCrime timestamp (ISO-8601
    UTC, e.g. "2026-08-23T18:01:51Z") — used for the 7-day dormancy cutoff
    (a dormant bounty is hidden from scans, only payable at a station the
    issuing faction controls). Same fromisoformat-based UTC parsing as
    relative_time() above — NOT time.mktime(time.strptime(...)), which
    misinterprets a naive struct_time as local time rather than UTC and
    previously gave every non-UTC commander a skewed dormancy countdown
    (duplicated identically in two panels before both were pointed here)."""
    if not commit_ts:
        return None
    try:
        ts = commit_ts.strip()
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds()) / 86400.0
    except (ValueError, TypeError):
        return None


def clean_token(value: Any) -> Any:
    """
    Convert Frontier internal tokens like '$economy_Extraction;' into 'Extraction'.
    If value isn't a token-like string, returns unchanged.
    """
    if not isinstance(value, str):
        return value

    s = value.strip()
    if not s:
        return s

    # Strip the journal token decorations
    if s.startswith("$"):
        s = s[1:]
    if s.endswith(";"):
        s = s[:-1]

    # Remove common prefixes that show up in system meta
    for prefix in ("government_", "economy_", "SYSTEM_SECURITY_", "system_security_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break

    s = s.replace("_", " ").strip()
    if s:
        s = s[0].upper() + s[1:]
    return s

def text(value: Any, default: str = "") -> str:
    """
    Safe string conversion for UI display.
    Also cleans token-like strings.
    """
    if value is None:
        return default
    v = clean_token(value)
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip() if v.strip() else default
    return str(v)

def int_commas(value: Any, default: str = "") -> str:
    try:
        if value is None:
            return default
        return f"{int(value):,}"
    except Exception:
        return default

def credits(value: Any, default: str = "") -> str:
    """
    Formats credits as '1,234,567 cr'
    """
    try:
        if value is None:
            return default
        return f"{int(value):,} cr"
    except Exception:
        return default

def pct_1(value: Any, default: str = "") -> str:
    """
    Formats 0..1 floats as '12.3%'. If already 0..100, still works reasonably.
    """
    try:
        if value is None:
            return default
        x = float(value)
        if 0.0 <= x <= 1.0:
            x *= 100.0
        return f"{x:.1f}%"
    except Exception:
        return default

def join_meta(*parts: Optional[str], sep: str = " | ") -> str:
    items = []
    for p in parts:
        if not p:
            continue
        s = str(p).strip()
        if s:
            items.append(s)
    return sep.join(items)