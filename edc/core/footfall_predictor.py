"""Estimates whether a body's First Footfall bonus is still unclaimed,
using only the Spansh snapshot already fetched on system arrival
(edc/core/spansh_client.py::fetch_system_bodies) — no extra network call.

Odyssey (and on-foot exploration/exobiology) shipped 2021-05-19, so a body
Spansh last saw updated before that date has certainly never been footfalled;
a body Spansh has never indexed at all is likely unvisited too. was_mapped
is Spansh's own record of whether the body has been DSS-mapped — not proof
of a footfall, but the closest proxy available pre-visit. This is an
estimate only: the journal doesn't record footfall status until you sell
the data at Vista Genomics (WasFootfalled/FirstFootfall in event_engine.py
are the real signal, and always take priority once a body is personally
scanned)."""
from __future__ import annotations

ODYSSEY_DATE = "2021-05-19"

LIKELY_UNCLAIMED = "Likely unclaimed"
POSSIBLY_UNCLAIMED = "Possibly unclaimed"
UNCERTAIN = "Uncertain"
LIKELY_CLAIMED = "Likely claimed"


def predict_footfall(updated_at: str | None, was_mapped: int | bool | None) -> tuple[int, str]:
    """Returns (score 0-100, label). Higher score = more likely still unclaimed."""
    score = 50

    if not updated_at:
        score += 20
    elif updated_at < ODYSSEY_DATE:
        score += 35
    else:
        score -= 10

    if was_mapped is True or was_mapped == 1:
        score -= 15
    elif was_mapped is False or was_mapped == 0:
        score += 20

    score = max(0, min(100, score))

    if score >= 70:
        label = LIKELY_UNCLAIMED
    elif score >= 40:
        label = POSSIBLY_UNCLAIMED
    elif score >= 20:
        label = UNCERTAIN
    else:
        label = LIKELY_CLAIMED
    return score, label
