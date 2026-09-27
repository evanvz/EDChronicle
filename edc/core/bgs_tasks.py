# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""BGS Tasks tracker -- per-task progress and status, derived only from
data the app already records (session activity tables, net.system_bgs_status,
faction_snapshots, systems.pp_*). No task data ever leaves the app. See
docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

TASK_TYPES = ("boost", "vote", "fight", "powerplay", "note")
TASK_LABELS = {"boost": "Boost", "vote": "Vote", "fight": "Fight", "powerplay": "PowerPlay", "note": "Note"}

STATUS_DONE = "Done this tick"
STATUS_TODO = "To do"
STATUS_LOSING = "Losing ground"
STATUS_ENDED = "Conflict ended"
STATUS_NO_DATA = "No data yet"
STATUS_TRACKING = "Tracking"

STATUS_COLORS = {
    STATUS_DONE: "#6BCB77",
    STATUS_TODO: "#c8c8c8",
    STATUS_LOSING: "#FF6B6B",
    STATUS_ENDED: "#888888",
    STATUS_NO_DATA: "#666666",
    STATUS_TRACKING: "#4DD8C8",
}

# One accent per task type, matching colours already used elsewhere
# (missions green, Overview election yellow / war red).
TYPE_COLORS = {
    "boost": "#6BCB77",
    "vote": "#FFD93D",
    "fight": "#FF6B6B",
    "powerplay": "#B983FF",
    "note": "#888888",
}

# Squadron guidance defaults (Frontier publishes no per-stream limits).
DEFAULT_LIMITS = {"tier_score": 25, "bounties": 20_000_000, "exploration": 20_000_000}

_LIMITED_STREAMS = (("tier_score", "Tier score"), ("bounties", "Bounties"), ("exploration", "Exploration"),
                    ("trade_profit", "Trade profit"))

# SINC's recommended effort per player per day per system, by population
# (Complete BGS Guide 2024, p69). Community guidance, not Frontier numbers.
_POPULATION_TARGETS = (
    (1_000_000, "small", {"tier_score": 15, "bounties": 10_000_000, "exploration": 5_000_000,
                          "trade_profit": 10_000_000}),
    (25_000_000, "medium", {"tier_score": 25, "bounties": 20_000_000, "exploration": 10_000_000,
                            "trade_profit": 20_000_000}),
    (None, "large", {"tier_score": 50, "bounties": 30_000_000, "exploration": 15_000_000,
                     "trade_profit": 30_000_000}),
)


def population_targets(population) -> Optional[dict]:
    """SINC daily targets for a system of this population, or None if the
    population isn't known. Small < 1m, medium 1m-25m, large > 25m."""
    if not isinstance(population, int) or population <= 0:
        return None
    for ceiling, size, targets in _POPULATION_TARGETS:
        if ceiling is None or (population < ceiling if size == "small" else population <= ceiling):
            return dict(targets, size=size)
    return None


def bgs_limits(cfg) -> dict:
    return {
        "tier_score": int(getattr(cfg, "bgs_limit_tier_score", DEFAULT_LIMITS["tier_score"])),
        "bounties": int(getattr(cfg, "bgs_limit_bounties_cr", DEFAULT_LIMITS["bounties"])),
        "exploration": int(getattr(cfg, "bgs_limit_exploration_cr", DEFAULT_LIMITS["exploration"])),
        "by_population": bool(getattr(cfg, "bgs_population_targets", True)),
    }


def validate_task_input(system: str, task_type: str, faction: str, opponent: str, note: str) -> str:
    if task_type not in TASK_TYPES:
        return "Pick a task type."
    if task_type != "note" and not system:
        return "Enter a system name."
    if task_type in ("boost", "vote", "fight") and not faction:
        return "Enter the faction to support."
    if task_type in ("vote", "fight") and not opponent:
        return "Enter the opposing faction."
    if task_type == "note" and not note:
        return "Enter the note text."
    return ""


def task_title(task: dict) -> str:
    parts = [TASK_LABELS.get(task["task_type"], task["task_type"])]
    if task.get("faction_name"):
        parts.append(task["faction_name"])
    if task.get("opponent_name"):
        parts.append(f"vs {task['opponent_name']}")
    head = " ".join(parts)
    system = task.get("system_name") or ""
    return f"{system} — {head}" if system else head


def _same(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and a.strip().lower() == b.strip().lower()


def _missions(n: int) -> str:
    return f"{n} mission" if n == 1 else f"{n} missions"


def _cr(value: int) -> str:
    return f"{value / 1_000_000:.1f}M" if abs(value) >= 1_000_000 else f"{value:,}"


# Relative worth of a CZ towards winning a war day, in low-space-CZ units
# (Complete BGS Guide 2024, p46 -- community-measured).
_CZ_WEIGHTS = {"space_l": 1.0, "space_m": 1.3, "space_h": 1.6,
               "ground_l": 0.25, "ground_m": 0.325, "ground_h": 0.4}


def faction_activity(report: dict, system_name: str, faction_name: str) -> dict:
    """This tick's activity for one faction in one system, summed across
    every day in the session report. Names match case-insensitively."""
    total = {k: 0 for k in ("missions", "tier_score", "bounties", "combat_bonds", "cz_kills", "cz_value",
                            "trade_profit", "exploration", "exobiology")}
    for systems in report.values():
        for sys_name, factions in systems.items():
            if not _same(sys_name, system_name):
                continue
            for fac_name, e in factions.items():
                if not _same(fac_name, faction_name):
                    continue
                total["missions"] += e["missions"]["count"]
                total["tier_score"] += e["missions"]["weighted"]
                total["bounties"] += e.get("bounties_total", 0)
                total["combat_bonds"] += e["combat_bonds_total"]
                total["cz_kills"] += sum(e["cz_kills"].values())
                total["cz_value"] += sum(n * _CZ_WEIGHTS.get(k, 0) for k, n in e["cz_kills"].items())
                total["trade_profit"] += e["trade_sold"]["commodity"]
                total["exploration"] += e["trade_sold"]["exploration"]
                total["exobiology"] += e["trade_sold"]["exobiology"]
    return total


def find_conflict(bgs_status: Optional[dict], faction_name: str, opponent_name: str, war_types: tuple) -> Optional[dict]:
    """The stored conflict between faction_name and opponent_name (any
    opponent if blank), oriented so "for" is faction_name's side."""
    for c in (bgs_status or {}).get("conflicts") or []:
        if c.get("war_type") not in war_types:
            continue
        f1, f2 = c.get("faction1"), c.get("faction2")
        if _same(f1, faction_name) and (not opponent_name or _same(f2, opponent_name)):
            ours, theirs = "1", "2"
        elif _same(f2, faction_name) and (not opponent_name or _same(f1, opponent_name)):
            ours, theirs = "2", "1"
        else:
            continue
        return {
            "war_type": c.get("war_type"), "status": c.get("status") or "",
            "days_for": c.get(f"won_days{ours}"), "days_against": c.get(f"won_days{theirs}"),
            "stake_for": c.get(f"stake{ours}"), "stake_against": c.get(f"stake{theirs}"),
        }
    return None


def _boost_view(task: dict, report: dict, history: list, limits: dict) -> dict:
    faction = task.get("faction_name") or ""
    act = faction_activity(report, task["system_name"], faction)
    lines, line_states = [], []
    for key, label in _LIMITED_STREAMS:
        limit = limits.get(key, 0)
        if key == "tier_score":
            text = f"Tier score {act[key]} / {limit} ({_missions(act['missions'])})"
        elif limit > 0:
            text = f"{label} {_cr(act[key])} / {_cr(limit)}"
        elif act[key]:
            text = f"{label} {_cr(act[key])}"  # no target set for this stream
        else:
            continue
        state = ""
        if limit > 0 and act[key] >= limit:
            state = "over" if act[key] > limit else "met"
            text += " ✓"
        lines.append(text)
        line_states.append(state)
    if act["combat_bonds"]:
        lines.append(f"Combat bonds {_cr(act['combat_bonds'])}")

    rows = [h for h in history if _same(h.get("faction_name"), faction) and isinstance(h.get("influence"), (int, float))]
    latest = rows[0]["influence"] if rows else None
    previous = rows[1]["influence"] if len(rows) > 1 else None
    as_of = f" (as of {rows[0]['snapshot_date']})" if rows else ""
    if latest is not None and previous is not None:
        lines.append(f"Influence {previous * 100:.1f}% → {latest * 100:.1f}%{as_of}")
    elif latest is not None:
        lines.append(f"Influence {latest * 100:.1f}%{as_of}")

    warnings = [
        f"{label} past the daily target — diminishing returns"
        for key, label in _LIMITED_STREAMS if limits.get(key, 0) > 0 and act[key] > limits[key]
    ]
    if any(limits.get(key, 0) > 0 and act[key] >= limits[key] for key, _ in _LIMITED_STREAMS):
        status = STATUS_DONE
    elif latest is not None and previous is not None and latest < previous:
        status = STATUS_LOSING
    else:
        status = STATUS_TODO
    return {"status": status, "lines": lines, "warnings": warnings, "line_states": line_states,
            "hud": f"Boost {faction} — tier score {act['tier_score']}/{limits['tier_score']}",
            "updated_at": None}


def _conflict_view(task: dict, report: dict, bgs_status: Optional[dict], kind: str) -> dict:
    faction = task.get("faction_name") or ""
    opponent = task.get("opponent_name") or ""
    war_types = ("election",) if kind == "vote" else ("war", "civilwar")
    act = faction_activity(report, task["system_name"], faction)
    c = find_conflict(bgs_status, faction, opponent, war_types)
    updated_at = (bgs_status or {}).get("data_timestamp")
    lines, warnings = [], []

    days_for = days_against = 0
    if c:
        days_for = c["days_for"] if isinstance(c["days_for"], int) else None
        days_against = c["days_against"] if isinstance(c["days_against"], int) else None
        lines.append(f"Days won {days_for if days_for is not None else '?'} - "
                     f"{days_against if days_against is not None else '?'} ({c['status'] or 'pending'})")
        if c["stake_for"] or c["stake_against"]:
            lines.append(f"Stakes: {c['stake_for'] or 'none'} vs {c['stake_against'] or 'none'}")

    if kind == "vote":
        lines.append(
            f"Your actions: {_missions(act['missions'])} (tier score {act['tier_score']}), "
            f"trade profit {_cr(act['trade_profit'])}, exploration {_cr(act['exploration'])}"
        )
        acted = bool(act["missions"] or act["trade_profit"] > 0 or act["exploration"])
        if act["combat_bonds"] or act["cz_kills"]:
            warnings.append("Combat doesn't count in elections")
    else:
        cz_count = f"{act['cz_kills']} CZ fought" if act["cz_kills"] == 1 else f"{act['cz_kills']} CZs fought"
        lines.append(
            f"Your actions: {cz_count} (worth {act['cz_value']:.1f} low space CZs), "
            f"combat bonds {_cr(act['combat_bonds'])}, {_missions(act['missions'])}"
        )
        acted = bool(act["cz_kills"] or act["combat_bonds"] or act["missions"])
        if opponent and faction_activity(report, task["system_name"], opponent)["combat_bonds"]:
            warnings.append(f"You cashed combat bonds for {opponent}")

    if c is None:
        read_since_created = bool(updated_at) and updated_at >= (task.get("created_at") or "")
        status = STATUS_ENDED if read_since_created else STATUS_NO_DATA
    elif acted:
        status = STATUS_DONE
    elif days_for is not None and days_against is not None and days_against > days_for:
        status = STATUS_LOSING
    else:
        status = STATUS_TODO

    verb = TASK_LABELS[kind]
    who = f"{faction} vs {opponent}" if opponent else faction
    score = f"{days_for if days_for is not None else '?'}-{days_against if days_against is not None else '?'}" if c else "no score yet"
    return {"status": status, "lines": lines, "warnings": warnings,
            "hud": f"{verb} {who} — {score}", "updated_at": updated_at}


def powerplay_week_start(now: Optional[datetime] = None) -> str:
    """Most recent PowerPlay weekly tick: Thursday ~07:00 UTC (community
    estimate, same as the Faction Expansion Tracker's countdown)."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=(now.weekday() - 3) % 7)).replace(hour=7, minute=0, second=0, microsecond=0)
    if start > now:
        start -= timedelta(days=7)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def powerplay_mode(pledged: str, controlling_power: str, pp_state: str) -> str:
    """Same rule as the megaship merit callout: our power controls it ->
    Reinforcement; another power controls it -> Undermining; nobody controls
    it but it's PowerPlay-active -> Acquisition."""
    if not pledged:
        return ""
    if controlling_power:
        return "Reinforcement" if _same(controlling_power, pledged) else "Undermining"
    return "Acquisition" if pp_state else ""


def _powerplay_guide(mode: str, pp_state: str, pledged: str, pp_activities) -> str:
    if not pledged:
        return "Pledge to a power to see PowerPlay actions for this system"
    if not mode:
        return "Not a PowerPlay target for your power right now"
    if pp_activities is None:
        return mode
    acts = [a for a in pp_activities.get_actions(mode.lower(), pp_state) if a.merits == "yes"]
    acts.sort(key=lambda a: not any(_same(p, pledged) for p in a.bonus_powers))
    names = list(dict.fromkeys(a.action for a in acts))[:4]
    return f"{mode}: {', '.join(names)}" if names else mode


def _powerplay_view(pp: Optional[dict], pledged: str, merits: int, pp_activities) -> dict:
    merits_line = [f"Your merits here this PowerPlay week: {merits:,}"] if pledged else []
    merits_hud = f" · {merits:,} merits this week" if pledged else ""
    if not pp:
        return {"status": STATUS_NO_DATA, "lines": ["No PowerPlay reading yet"] + merits_line, "warnings": [],
                "hud": "PowerPlay — no data yet" + merits_hud, "updated_at": None,
                "guide": "" if pledged else _powerplay_guide("", "", "", None)}
    pp_state = pp.get("pp_state") or ""
    reading = pp_state or "Unknown"
    progress = pp.get("pp_control_progress")
    if isinstance(progress, (int, float)):
        reading += f" — {progress * 100:.1f}%"
    mode = powerplay_mode(pledged, pp.get("pp_controlling_power") or "", pp_state)
    head = f"{mode}: {reading}" if mode else reading
    lines = [head]
    if pp.get("pp_controlling_power"):
        lines.append(f"Controlled by {pp['pp_controlling_power']}")
    lines += merits_line
    return {"status": STATUS_TRACKING, "lines": lines, "warnings": [],
            "hud": f"PowerPlay — {head}{merits_hud}", "updated_at": pp.get("pp_data_timestamp"),
            "guide": _powerplay_guide(mode, pp_state, pledged, pp_activities)}


def _bgs_guide(task: dict, limits: dict, population_basis: str = "") -> str:
    # Wording follows what decides each day per the SINC Complete BGS Guide 2024.
    faction = task.get("faction_name") or "the faction"
    opponent = task.get("opponent_name") or "the other side"
    task_type = task["task_type"]
    if task_type == "boost":
        return (f"A bit of each: missions for {faction} (about {limits['tier_score']} INF+ per tick), bounties, "
                f"exploration data and high-demand profitable trade at {faction}-controlled stations "
                f"(exobiology and mined goods don't count). {population_basis}").strip()
    if task_type == "vote":
        return (f"Complete election missions for {faction} — they decide each day. Trade, exploration data "
                f"and economic missions only break ties. Combat doesn't count in elections.")
    return (f"Win the most conflict zones for {faction} each day — low space CZs are the most efficient. "
            f"Combat bonds, bounties and combat missions only break ties. Don't cash bonds for {opponent}.")


def _population_basis(targets: Optional[dict], population) -> str:
    if targets:
        return (f"Targets for a {targets['size']} system ({population / 1_000_000:.1f} million), "
                f"SINC guidance.")
    return "Targets from Settings (population unknown)."


def build_task_view(task: dict, report: dict, bgs_status: Optional[dict], history: list,
                    pp: Optional[dict], limits: dict, pledged: str = "", merits: int = 0,
                    pp_activities=None, population: Optional[int] = None) -> dict:
    task_type = task["task_type"]
    population_basis = ""
    if task_type == "boost":
        targets = population_targets(population) if limits.get("by_population", True) else None
        if targets:
            limits = dict(limits, **{k: v for k, v in targets.items() if k != "size"})
        population_basis = _population_basis(targets, population)
        view = _boost_view(task, report, history, limits)
    elif task_type in ("vote", "fight"):
        view = _conflict_view(task, report, bgs_status, task_type)
    elif task_type == "powerplay":
        view = _powerplay_view(pp, pledged, merits, pp_activities)
    else:
        note = task.get("note") or ""
        lines = [note] if note else []
        return {"task": task, "status": "", "lines": lines, "line_states": [""] * len(lines), "warnings": [],
                "hud": f"Note: {note}" if note else "", "updated_at": None, "guide": ""}
    if task_type != "powerplay":
        view["guide"] = _bgs_guide(task, limits, population_basis)
    if task.get("note"):
        view["lines"].append(task["note"])
    # "met" / "over" per line where the line has a target (Boost streams), else "".
    states = view.get("line_states", [])
    view["line_states"] = states + [""] * (len(view["lines"]) - len(states))
    view["task"] = task
    return view


def build_task_views(repo, since: str, limits: dict, system_address: Optional[int] = None,
                     pledged: str = "", pp_activities=None, now: Optional[datetime] = None) -> list[dict]:
    """Views for every task (or only those in system_address), in the
    user's priority order."""
    tasks = repo.list_bgs_tasks()
    if system_address is not None:
        tasks = [t for t in tasks if t["system_address"] == system_address]
    if not tasks:
        return []
    report = repo.get_session_activity_report(since)
    week_start = powerplay_week_start(now)
    views = []
    for t in tasks:
        addr = t["system_address"]
        bgs_status = repo.get_bgs_status_for_system(addr) if addr is not None else None
        history = repo.get_faction_history(addr) if addr is not None else []
        pp = repo.get_system_powerplay_snapshot(addr) if addr is not None else None
        merits = (repo.get_powerplay_merits_since(addr, week_start)
                  if t["task_type"] == "powerplay" and pledged and addr is not None else 0)
        population = (repo.get_system_population(addr)
                      if t["task_type"] == "boost" and addr is not None else None)
        views.append(build_task_view(t, report, bgs_status, history, pp, limits,
                                     pledged=pledged, merits=merits, pp_activities=pp_activities,
                                     population=population))
    return views


def hud_line(views: list) -> str:
    parts = [v["hud"] for v in views if v.get("hud")]
    return ("Squadron task: " + " · ".join(parts)) if parts else ""
