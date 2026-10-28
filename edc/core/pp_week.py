"""PowerPlay week history: how a system's reinforcement/undermining moved since
the weekly reset. Pure functions over reading dicts (observed_at, pp_state,
reinforcement, undermining, control, source)."""
from datetime import datetime, timedelta
from typing import Optional


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def merge(local: list, hub: list) -> list:
    """Sorted by time; equal (time, R, U) readings appear once, local kept."""
    seen, out = set(), []
    for r in [*local, *hub]:
        k = (r["observed_at"], r["reinforcement"], r["undermining"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return sorted(out, key=lambda r: r["observed_at"])


def daily(readings: list, week_start: str, now: datetime) -> list:
    """One dict per UTC date from the reset to now. u/r are the day's gain over
    the previous day that has a reading (0 at the reset); spans/spans_r = days back
    to it for u/r (spans follows r when u is None), counting the reset day itself
    when there is no earlier reading."""
    last = {}
    for r in sorted(readings, key=lambda r: r["observed_at"]):
        if r["observed_at"] >= week_start:
            last[_t(r["observed_at"]).date()] = r
    first, out = _t(week_start).date(), []
    base = {"undermining": (0, None), "reinforcement": (0, None)}   # key -> (value, day)
    d = first
    while d <= now.date():
        r = last.get(d)
        row = {"day": d, "u": None, "r": None, "control": None, "state": None, "spans": 1, "spans_r": 1}
        if r:
            row["control"], row["state"] = r["control"], r["pp_state"]
            for key, name in (("undermining", "u"), ("reinforcement", "r")):
                v = r[key]
                if v is not None:
                    row[name] = v - base[key][0]
                    sp = (d - base[key][1]).days if base[key][1] else (d - first).days + 1
                    if name == "r":
                        row["spans_r"] = sp
                    if name == "u" or row["u"] is None:
                        row["spans"] = sp
                    base[key] = (v, d)
        out.append(row)
        d += timedelta(days=1)
    return out


def last_24h(readings: list, week_start: str, now: datetime) -> Optional[tuple]:
    """(gained undermining, "up"|"down"|"flat") over the last 24 h, or None."""
    cut = (now - timedelta(hours=24))
    rs = sorted((r for r in readings
                 if r["undermining"] is not None and week_start <= r["observed_at"]
                 and _t(r["observed_at"]) <= now), key=lambda r: r["observed_at"])
    base = [r for r in rs if _t(r["observed_at"]) <= cut]
    if not rs or not base or _t(rs[-1]["observed_at"]) <= cut:
        return None
    gained = rs[-1]["undermining"] - base[-1]["undermining"]
    return gained, "up" if gained > 0 else "down" if gained < 0 else "flat"
