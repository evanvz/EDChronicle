from datetime import date, datetime, timezone


def utc_today() -> date:
    """The app's one "today". Snapshot dates and data timestamps are UTC (journal/EDDN
    event time, the game's clock); the local date runs ahead for UTC+ players near
    local midnight."""
    return datetime.now(timezone.utc).date()
