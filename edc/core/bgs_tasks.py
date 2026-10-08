# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""BGS Tasks tracker -- per-task progress and status, derived only from
data the app already records (session activity tables, net.system_bgs_status,
faction_snapshots, systems.pp_*). No task data ever leaves the app. See
docs/superpowers/specs/2026-09-26-bgs-tasks-tracker-design.md."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

TASK_TYPES = ("boost", "hinder", "vote", "fight", "powerplay", "note")
TASK_LABELS = {"boost": "Boost", "hinder": "Hinder", "vote": "Vote", "fight": "Fight", "powerplay": "PowerPlay",
               "note": "Note"}

STATUS_DONE = "Done this tick"
STATUS_TODO = "To do"
STATUS_LOSING = "Losing ground"
STATUS_ENDED = "Conflict ended"
STATUS_NO_DATA = "No data yet"
STATUS_TRACKING = "Tracking"
STATUS_DROPPING = "Dropping"

STATUS_COLORS = {
    STATUS_DONE: "#6BCB77",
    STATUS_TODO: "#c8c8c8",
    STATUS_LOSING: "#FF6B6B",
    STATUS_ENDED: "#888888",
    STATUS_NO_DATA: "#666666",
    STATUS_TRACKING: "#4DD8C8",
    STATUS_DROPPING: "#6BCB77",
}

# One accent per task type, matching colours already used elsewhere
# (missions green, Overview election yellow / war red).
TYPE_COLORS = {
    "boost": "#6BCB77",
    "hinder": "#FF9F43",
    "vote": "#FFD93D",
    "fight": "#FF6B6B",
    "powerplay": "#B983FF",
    "note": "#888888",
}

# Squadron guidance defaults (Frontier publishes no per-stream limits).
# Squadron BGS guide (2023): bounties at most 10M per cash-in (20M total).
# Unconfirmed: SINC 2024 has no per-cash-in rule, and says transaction
# chunking no longer matters for trade.
BOUNTY_CASHIN_LIMIT = 10_000_000

DEFAULT_LIMITS = {"tier_score": 25, "bounties": 20_000_000, "exploration": 20_000_000}

_LIMITED_STREAMS = (("tier_score", "INF"), ("bounties", "Bounties"), ("exploration", "Exploration"),
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


def population_text(population) -> str:
    """ "51.9 million (large)", "850k (small)" or "unknown" -- sizes as in
    SINC's targets table (small < 1m, medium 1-25m, large > 25m)."""
    if not isinstance(population, int) or population <= 0:
        return "unknown"
    size = "small" if population < 1_000_000 else "medium" if population <= 25_000_000 else "large"
    if population >= 1_000_000_000:
        amount = f"{population / 1_000_000_000:.1f} billion"
    elif population >= 1_000_000:
        amount = f"{population / 1_000_000:.1f} million"
    else:
        amount = f"{population / 1_000:.0f}k"
    return f"{amount} ({size})"


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
        "allied_powers": getattr(cfg, "pp_allied_powers", None),
    }


def validate_task_input(system: str, task_type: str, faction: str, opponent: str, note: str) -> str:
    if task_type not in TASK_TYPES:
        return "Pick a task type."
    if task_type != "note" and not system:
        return "Enter a system name."
    if task_type in ("boost", "vote", "fight") and not faction:
        return "Enter the faction to support."
    if task_type == "hinder" and not faction:
        return "Enter the faction to hinder."
    if task_type in ("vote", "fight") and not opponent:
        return "Enter the opposing faction."
    if task_type == "note" and not note:
        return "Enter the note text."
    return ""


def distance_text(here: Optional[tuple], there: Optional[tuple], same_system: bool = False,
                  jump_range: Optional[float] = None) -> str:
    """Card corner text: "here", "42.3 ly · ~3 jumps", "42.3 ly", or "— ly"
    when either end's coordinates are unknown. Jumps are a best case
    (straight line / unladen max range), hence "~"."""
    if same_system:
        return "here"
    if not here or not there:
        return "— ly"
    dist = sum((a - b) ** 2 for a, b in zip(here, there)) ** 0.5
    text = f"{dist:,.1f} ly"
    if jump_range and jump_range > 0:
        jumps = max(1, math.ceil(dist / jump_range))
        text += f" · ~{jumps} jump{'s' if jumps != 1 else ''}"
    return text


def task_title(task: dict) -> str:
    parts = [TASK_LABELS.get(task["task_type"], task["task_type"])]
    if task.get("pp_mode"):
        parts[0] += f" ({task['pp_mode']})"
    if task.get("faction_name"):
        parts.append(task["faction_name"])
    if task.get("opponent_name"):
        parts.append(f"vs {task['opponent_name']}")
    head = " ".join(parts)
    system = task.get("system_name") or ""
    return f"{system} — {head}" if system else head


# The journal, EDSM and EDDN all spell Arissa as "A. Lavigny-Duval"; people
# (and the activity table) write her full name. Compare on one form.
_POWER_ALIASES = {"arissa lavigny-duval": "a. lavigny-duval"}


def _key(name: str) -> str:
    key = name.strip().lower()
    return _POWER_ALIASES.get(key, key)


def _same(a, b) -> bool:
    return isinstance(a, str) and isinstance(b, str) and _key(a) == _key(b)


# The ZYADA coalition (Zemina Torval, Yuri Grom, Arissa Lavigny-Duval,
# Denton Patreus, Aisling Duval): squadron rule, never undermine each other.
# Names as the game writes them.
ZYADA_COALITION = ("Zemina Torval", "Yuri Grom", "A. Lavigny-Duval", "Denton Patreus", "Aisling Duval")


# Each power's PowerPlay commodity per job: (Acquisition, Reinforcement,
# Undermining). ED wiki "Powerplay commodities" table.
POWERPLAY_COMMODITIES = {
    # Aisling's as the journal/cargo spell them (plural); others per the wiki.
    "aisling duval": ("Aisling Media Materials", "Aisling Sealed Contracts", "Aisling Programme Materials"),
    "archon delaine": ("Kumo Contraband Packages", "Unmarked Military Supplies", "Marked Slaves"),
    "a. lavigny-duval": ("Lavigny Corruption Reports", "Lavigny Garrison Supplies", "Lavigny Strategic Reports"),
    "denton patreus": ("Marked Military Arms", "Patreus Field Supplies", "Patreus Garrison Supplies"),
    "edmund mahon": ("Alliance Trade Agreements", "Alliance Legislative Contract", "Alliance Legislative Records"),
    "felicia winters": ("Liberal Federal Aid", "Liberal Federal Packages", "Liberal Propaganda"),
    "jerome archer": ("Archer's Restricted Intel", "Archer's Field Supplies", "Archer's Garrison Supplies"),
    "li yong-rui": ("Sirius Franchise Package", "Sirius Industrial Equipment", "Sirius Corporate Contracts"),
    "nakato kaine": ("Kaine Lobbying Material", "Kaine Aid Supplies", "Kaine Misinformation"),
    "pranav antal": ("Utopian Publicity", "Utopian Supplies", "Utopian Dissident"),
    "yuri grom": ("Grom Underground Support", "Grom Military Supplies", "Grom Counter Intelligence"),
    "zemina torval": ("Torval Trade Agreements", "Torval Deeds", "Torval Political Servants"),
}
_COMMODITY_ROUTE = {
    "Acquisition": (0, "collect at a Power Contact in a supporting system in range (your Fortified within "
                       "20 ly / Stronghold within 30 ly), deliver to the Power Contact here"),
    "Reinforcement": (1, "collect at a Power Contact in one of your Strongholds (not this system), "
                         "deliver to the Power Contact here"),
    "Undermining": (2, "collect at a Power Contact in one of your Strongholds, deliver to the Power Contact here"),
}


def transport_text(mode: str, pledged: str) -> str:
    """ "Transport Aisling Media Material (collect ..., deliver ...)" for the
    pledged power and job; the generic activity name when unknown. Only the
    commodity for THIS job counts -- the other two earn nothing here."""
    commodities = POWERPLAY_COMMODITIES.get(_key(pledged or ""))
    route = _COMMODITY_ROUTE.get(mode)
    if not commodities or not route:
        return "Transport Powerplay Commodities"
    index, how = route
    return f"Transport {commodities[index]} ({how})"


# Merits per hand-in vary a lot by target system (16 t -> 4,065 at ICZ
# AG-O b6-5, 83 t -> 547 at Tucanae, same job), so cards show the player's
# own last hand-in at that system rather than a generic figure.
# One allocation pool per commander, shared by every station: Isiti stayed
# greyed out until ~25 min after a Ban Vision collect (seen in game
# 2026-10-03). A load comes back ~30 min after the last one (community-
# reported, fits the day's 12 collects); idle time stacks loads and a
# rank-up adds a bonus load.
ALLOCATION_REFRESH_MIN = 30

# Control points (the system's tug-of-war score) are roughly merits / 4 for
# most activities (SOTL reference card; exploration/exobiology data is ~/6,
# and merit bonuses/penalties shift it). The journal only has merits.
MERITS_PER_CP = 4
CP_NOTE = ("≈ control points = merits ÷ 4 (community rule of thumb; data sales are nearer ÷6 "
           "and merit bonuses shift it). The journal records merits only.")


def cp_text(merits: int) -> str:
    return f"≈{round(merits / MERITS_PER_CP):,} CP"


# Frontier: Acquisition commodities must come from a supporting system --
# your Fortified within 20 ly or Stronghold within 30 ly of the target.
SUPPORT_RANGE_LY = {"Fortified": 20.0, "Stronghold": 30.0}
_held_cache: dict = {}


def supporting_systems(repo, pledged: str, target_name: str, edsm_powerplay=None) -> list:
    """[(name, state, distance_ly)] nearest first: the pledged power's
    Fortified systems within 20 ly and Strongholds within 30 ly of the
    target. Held systems come from EDSM's daily dump, overridden by our own
    journal reading where we visited more recently; their coordinates are
    cached per pledge/EDSM day (the dump is ~1,300 systems for a power)."""
    key = (_key(pledged or ""), getattr(edsm_powerplay, "fetched_date", None))
    held = _held_cache.get(key)
    if held is None:
        states = dict(edsm_powerplay.held_systems(pledged)) if edsm_powerplay else {}
        for name, (state, _ts) in repo.get_held_systems_from_journal(pledged).items():
            if state in SUPPORT_RANGE_LY:
                states[name] = state
            else:
                states.pop(name, None)  # our own visit says it isn't Fortified/Stronghold now
        coords = repo.get_system_coords_for_names(list(states)) if states else {}
        held = [(n, s, coords[n]) for n, s in states.items() if n in coords]
        _held_cache.clear()
        _held_cache[key] = held
    target = repo.get_system_coords_for_names([target_name]).get(target_name)
    if not target:
        return []
    out = []
    for name, state, xyz in held:
        dist = sum((a - b) ** 2 for a, b in zip(xyz, target)) ** 0.5
        if dist <= SUPPORT_RANGE_LY[state] and name.lower() != target_name.lower():
            out.append((name, state, dist))
    return sorted(out, key=lambda t: t[2])


def cargo_by_name(inventory) -> dict:
    """{commodity name lower-cased (in-game spelling): count} from the
    Cargo.json Inventory list (state.cargo_inventory)."""
    out = {}
    for item in inventory or []:
        if isinstance(item, dict):
            name = (item.get("Name_Localised") or item.get("Name") or "").strip().lower()
            if name:
                out[name] = out.get(name, 0) + int(item.get("Count", 0) or 0)
    return out


def commodity_info(mode: str, pledged: str, cargo: Optional[dict] = None,
                   last_collect: Optional[dict] = None, now: Optional[datetime] = None,
                   supporting: Optional[list] = None, collect_system: Optional[dict] = None,
                    collect_batch: Optional[dict] = None,
                   last_delivery: Optional[dict] = None) -> Optional[dict]:
    """The facts behind commodity_lines(), for compact card chips."""
    commodities = POWERPLAY_COMMODITIES.get(_key(pledged or ""))
    route = _COMMODITY_ROUTE.get(mode)
    if not commodities or not route:
        return None
    name = commodities[route[0]]
    key = name.lower()
    info = {"name": name, "carrying": (cargo or {}).get(key, 0), "next_allocation": "",
            "supporting": supporting if mode == "Acquisition" else None, "warning": "",
            "last_delivery": last_delivery, "collected_ok": "", "batch": max((collect_batch or {}).values(), key=lambda x: x["last"], default=None)}
    when = max((last_collect or {}).values(), default=None)   # one pool for all commodity types
    if when:
        try:
            ready = datetime.fromisoformat(when.replace("Z", "+00:00")) + timedelta(minutes=ALLOCATION_REFRESH_MIN)
            info["next_allocation"] = (ready.astimezone().strftime("%H:%M")
                                       if ready > (now or datetime.now(timezone.utc)) else "now")
        except ValueError:
            pass
    source = (collect_system or {}).get(key)
    if (mode == "Acquisition" and supporting is not None and info["carrying"] and source
            and not any(n.lower() == source.lower() for n, _s, _d in supporting)):
        fix = f" — collect at {supporting[0][0]} instead" if supporting else ""
        info["warning"] = (f"Your {info['carrying']} t were collected at {source}, which isn't a supporting "
                           f"system for this target, so they won't be accepted here{fix}")
    elif mode == "Acquisition" and supporting and info["carrying"] and source:
        info["collected_ok"] = source
    return info


def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone().strftime("%H:%M")
    except ValueError:
        return ""


def _seconds_ago(when: str, now: Optional[datetime] = None) -> Optional[float]:
    try:
        then = datetime.fromisoformat(str(when).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ((now or datetime.now(timezone.utc)) - then).total_seconds()


def commodity_lines(mode: str, pledged: str, cargo: Optional[dict] = None,
                    last_collect: Optional[dict] = None, now: Optional[datetime] = None,
                    supporting: Optional[list] = None, collect_system: Optional[dict] = None,
                    collect_batch: Optional[dict] = None,
                    last_delivery: Optional[dict] = None) -> list:
    """Card lines for the job's commodity: what you're carrying, when the
    next allocation is (30 min after your last collection, community-
    reported), and the observed merits-per-hand-in note. cargo /
    last_collect are keyed by lower-cased commodity name (in-game spelling);
    last_collect values are ISO timestamps."""
    commodities = POWERPLAY_COMMODITIES.get(_key(pledged or ""))
    route = _COMMODITY_ROUTE.get(mode)
    if not commodities or not route:
        return []
    name = commodities[route[0]]
    key = name.lower()
    parts = [f"Commodity: {name}"]
    carrying = (cargo or {}).get(key, 0)
    if carrying:
        parts.append(f"carrying {carrying} t")
    when = max((last_collect or {}).values(), default=None)   # one pool for all commodity types
    if when:
        try:
            collected = datetime.fromisoformat(when.replace("Z", "+00:00"))
            ready = collected + timedelta(minutes=ALLOCATION_REFRESH_MIN)
            now = now or datetime.now(timezone.utc)
            if ready > now:
                parts.append(f"next allocation ~{ready.astimezone().strftime('%H:%M')} "
                             f"({ALLOCATION_REFRESH_MIN} min after your last collection, community-reported)")
            else:
                parts.append("allocation should be available again")
        except ValueError:
            pass
    lines = [" · ".join(parts)]
    if mode == "Acquisition" and supporting is not None:
        if supporting:
            shown = ", ".join(f"{n} ({s}, {d:.1f} ly)" for n, s, d in supporting[:3])
            lines.append(f"Collect at a supporting system: {shown}")
        else:
            lines.append("No supporting system known in range (Fortified ≤20 ly / Stronghold ≤30 ly) — "
                         "check the galaxy map's strategic view")
        source = (collect_system or {}).get(key)
        if carrying and source and not any(n.lower() == source.lower() for n, _s, _d in supporting):
            fix = f" — collect at {supporting[0][0]} instead" if supporting else ""
            lines.append(f"⚠ Your {carrying} t were collected at {source}, which isn't a supporting system "
                         f"for this target, so they won't be accepted here{fix}")
    if last_delivery:
        lines.append(f"Your last hand-in here: {last_delivery['count']} t {last_delivery['type']} → "
                     f"{last_delivery['merits']:,} merits ({str(last_delivery['timestamp'])[:10]})")
    return lines


def allied_powers(pledged: str, configured=None) -> frozenset:
    """Lower-cased names of the powers treated as allies. configured is
    Config.pp_allied_powers: None means the default, i.e. the rest of
    ZYADA when pledged to one of its powers; a list (even empty) overrides."""
    if configured is None:
        configured = ZYADA_COALITION if any(_same(pledged, p) for p in ZYADA_COALITION) else ()
    return frozenset(_key(p) for p in configured
                     if isinstance(p, str) and p.strip() and not _same(p, pledged))


def is_rival_power(power: str, pledged: str, allies=frozenset()) -> bool:
    """Another power that is neither ours nor an ally."""
    return bool(pledged and power and not _same(power, pledged) and _key(power) not in allies)


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
                            "trade_profit", "trade_bought", "exploration", "exobiology", "bounty_max_cashin")}
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
                total["bounty_max_cashin"] = max(total["bounty_max_cashin"], e.get("bounties_max_cashin", 0))
                total["combat_bonds"] += e["combat_bonds_total"]
                total["cz_kills"] += sum(e["cz_kills"].values())
                total["cz_value"] += sum(n * _CZ_WEIGHTS.get(k, 0) for k, n in e["cz_kills"].items())
                total["trade_profit"] += e["trade_sold"]["commodity"]
                total["trade_bought"] += e["trade_sold"].get("purchase", 0)
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


def _state_names(raw) -> set:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return set()
    return {str(s.get("State")).lower() for s in (data or []) if isinstance(s, dict) and s.get("State")}


def _retreat_countdown(rows: list, today: date) -> tuple:
    """(line, warnings) for a faction in Retreat, from its daily snapshots
    (newest first). SINC Complete BGS Guide 2024 p56: pending, then active
    days 1-7; do the work on active day 5 (the Important Day), the 2.5%
    check is active day 6. Dates are UTC days and the tick isn't at
    midnight, hence "~"."""
    run = []
    for r in rows:  # contiguous newest-first run of snapshots that show Retreat
        pending = "retreat" in _state_names(r.get("pending_states"))
        active = "retreat" in _state_names(r.get("active_states"))
        if not (pending or active):
            break
        run.append((date.fromisoformat(r["snapshot_date"][:10]), active))
    if not run:
        return None, []
    active_days = [d for d, active in run if active]
    active_start = min(active_days) if active_days else min(d for d, _ in run) + timedelta(days=1)
    important = active_start + timedelta(days=4)
    judged = active_start + timedelta(days=5)
    phase = f"active (day {(today - active_start).days + 1})" if active_days else "pending"
    line = (f"Retreat {phase}: Important Day ~{important.isoformat()} (active day 5, ±1 day), "
            f"must be above 2.5% on ~{judged.isoformat()}")
    warnings = []
    if today == important:
        warnings.append("Retreat Important Day is today — hand everything in")
    influence = rows[0].get("influence")
    if isinstance(influence, (int, float)) and influence < 0.025:
        warnings.append(f"Influence {influence * 100:.1f}% is below 2.5% — the faction retreats unless it's raised")
    return line, warnings


def _hinder_view(task: dict, report: dict, history: list, today: Optional[date] = None,
                 squadron_faction: str = "") -> dict:
    """Pushing a faction's influence down. Only the influence trend and our
    missions' signed effect on it are measurable -- failed missions, trade
    at a loss and kills aren't credited to a faction in the journal."""
    faction = task.get("faction_name") or ""
    act = faction_activity(report, task["system_name"], faction)
    lines, warnings = [], []
    if squadron_faction and _same(faction, squadron_faction):
        warnings.append(f"{faction} is your squadron's own faction — check the objective")
    if act["tier_score"] < 0:
        lines.append(f"Your missions this tick: {-act['tier_score']} INF against {faction}")
    elif act["tier_score"] > 0:
        warnings.append(f"Your missions this tick helped {faction} by {act['tier_score']} INF")
    if act["trade_profit"] > 0 or act["exploration"] > 0 or act["bounties"] > 0:
        warnings.append(f"Profitable trade, exploration data or bounties for {faction} this tick help them")

    rows = [h for h in history if _same(h.get("faction_name"), faction) and isinstance(h.get("influence"), (int, float))]
    latest = rows[0]["influence"] if rows else None
    previous = rows[1]["influence"] if len(rows) > 1 else None
    as_of = f" (as of {rows[0]['snapshot_date']})" if rows else ""
    if latest is not None and previous is not None:
        lines.append(f"Influence {previous * 100:.1f}% → {latest * 100:.1f}%{as_of}")
    elif latest is not None:
        lines.append(f"Influence {latest * 100:.1f}%{as_of}")

    retreat_line, _ = _retreat_countdown(rows, today or datetime.now(timezone.utc).date())
    if retreat_line:
        lines.append(retreat_line)
        if latest is not None and latest < 0.025:
            warnings.append(f"Influence {latest * 100:.1f}% is below 2.5% — keep it there through the check day")
        else:
            warnings.append("In retreat — pushing them below 2.5% by the check day removes them from the system")

    if latest is None:
        status = STATUS_NO_DATA
    elif previous is not None and latest < previous:
        status = STATUS_DROPPING
    else:
        status = STATUS_TODO
    influence_txt = f"{latest * 100:.1f}%" if latest is not None else "no data"
    bars, chips = [], []
    if latest is not None:
        trend = "" if previous is None else ("▼" if latest < previous else "▲" if latest > previous else "▶")
        bars.append({"label": "Their influence", "value": latest, "max": 1.0,
                     "text": f"{latest * 100:.1f}% {trend}".strip() + (f"  (was {previous * 100:.1f}%)" if previous is not None and previous != latest else ""),
                     "state": "met" if trend == "▼" else ("against" if trend == "▲" else "")})
    if act["tier_score"] < 0:
        chips.append({"text": f"Your missions −{-act['tier_score']} INF", "color": "#6BCB77"})
    short = f"Boost the other factions · missions with a red − on {faction} · fail their missions"
    return {"status": status, "lines": lines, "warnings": warnings, "line_states": [""] * len(lines),
            "bars": bars, "chips": chips, "guide_short": short,
            "detail_lines": [retreat_line] if retreat_line else [],
            "hud": f"Hinder {faction} — {influence_txt}", "updated_at": rows[0].get("snapshot_date") if rows else None}


def _boost_view(task: dict, report: dict, history: list, limits: dict, today: Optional[date] = None) -> dict:
    faction = task.get("faction_name") or ""
    act = faction_activity(report, task["system_name"], faction)
    lines, line_states = [], []
    for key, label in _LIMITED_STREAMS:
        limit = limits.get(key, 0)
        if key == "tier_score":
            text = f"INF {act[key]} / {limit} ({_missions(act['missions'])})"
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
    if act["trade_bought"]:
        lines.append(f"Trade buys {_cr(act['trade_bought'])}")
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
    if act["bounty_max_cashin"] > BOUNTY_CASHIN_LIMIT:
        warnings.append(f"A single bounty cash-in of {_cr(act['bounty_max_cashin'])} — squadron guide: "
                        f"keep each cash-in at {_cr(BOUNTY_CASHIN_LIMIT)} or less (squad guidance, unconfirmed)")
    retreat_line, retreat_warnings = _retreat_countdown(rows, today or datetime.now(timezone.utc).date())
    if retreat_line:
        lines.append(retreat_line)
        warnings += retreat_warnings
    if any(limits.get(key, 0) > 0 and act[key] >= limits[key] for key, _ in _LIMITED_STREAMS):
        status = STATUS_DONE
    elif latest is not None and previous is not None and latest < previous:
        status = STATUS_LOSING
    else:
        status = STATUS_TODO
    view_bars = []
    for key, label in _LIMITED_STREAMS:
        limit = limits.get(key, 0)
        if limit <= 0 and not act[key]:
            continue
        value = act[key]
        text = (f"{value} / {limit} INF" if key == "tier_score"
                else f"{_cr(value)} / {_cr(limit)}" if limit > 0 else _cr(value))
        view_bars.append({"label": "Missions" if key == "tier_score" else label, "value": value,
                          "max": limit, "text": text,
                          "state": ("over" if value > limit else "met") if limit > 0 and value >= limit else ""})
    chips = []
    if latest is not None:
        trend = "" if previous is None else ("▲" if latest > previous else "▼" if latest < previous else "▶")
        color = "#FF6B6B" if latest < 0.025 else ("#6BCB77" if trend == "▲" else "#FFB347" if trend == "▼" else "")
        chips.append({"text": f"Influence {latest * 100:.1f}% {trend}".strip(), "color": color,
                      "tooltip": (f"{previous * 100:.1f}% → {latest * 100:.1f}%{as_of}" if previous is not None
                                  else f"{latest * 100:.1f}%{as_of}")})
    if act["trade_bought"]:
        chips.append({"text": f"Trade buys {_cr(act['trade_bought'])}"})
    if act["combat_bonds"]:
        chips.append({"text": f"Combat bonds {_cr(act['combat_bonds'])}"})
    structure = {"bars": view_bars, "chips": chips,
                 "detail_lines": [retreat_line] if retreat_line else [],
                 "guide_short": f"Missions · bounties · exploration data · profitable high-demand trade for {faction}"}
    return {"status": status, "lines": lines, "warnings": warnings, "line_states": line_states, **structure,
            "hud": f"Boost {faction} — INF {act['tier_score']}/{limits['tier_score']}",
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
            f"Your actions: {_missions(act['missions'])} (INF {act['tier_score']}), "
            f"trade profit {_cr(act['trade_profit'])}, exploration {_cr(act['exploration'])}"
        )
        acted = bool(act["missions"] or act["trade_profit"] > 0 or act["trade_bought"] or act["exploration"])
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
    # First side to win 4 days takes the conflict.
    bars, chips = [], []
    if c:
        if days_for is not None:
            bars.append({"label": f"Days won ({faction})", "value": days_for, "max": 4,
                         "text": f"{days_for} / 4", "state": "met" if days_for >= 4 else ""})
        if days_against is not None:
            bars.append({"label": f"Days won ({opponent or 'other'})", "value": days_against, "max": 4,
                         "text": f"{days_against} / 4", "state": "against"})
        chips.append({"text": (c["status"] or "pending").capitalize()})
        if c["stake_for"] or c["stake_against"]:
            chips.append({"text": "Stakes", "tooltip": f"{c['stake_for'] or 'none'} vs {c['stake_against'] or 'none'}"})
    if kind == "vote":
        chips.append({"text": f"{act['missions']} missions", "color": "#6BCB77" if act["missions"] else ""})
        if act["trade_profit"] > 0:
            chips.append({"text": f"Trade {_cr(act['trade_profit'])}"})
        if act["exploration"]:
            chips.append({"text": f"Exploration {_cr(act['exploration'])}"})
        short = f"Election missions for {faction} · trade / exploration break ties · no combat"
    else:
        chips.append({"text": f"{act['cz_kills']} CZ{'s' if act['cz_kills'] != 1 else ''} "
                              f"(≈{act['cz_value']:.1f} low space)", "color": "#6BCB77" if act["cz_kills"] else ""})
        if act["combat_bonds"]:
            chips.append({"text": f"Bonds {_cr(act['combat_bonds'])}"})
        if act["missions"]:
            chips.append({"text": f"{act['missions']} missions"})
        short = f"Win conflict zones for {faction} · bonds, massacre missions, bounties break ties"
    return {"status": status, "lines": lines, "warnings": warnings,
            "bars": bars, "chips": chips, "detail_lines": [], "guide_short": short,
            "hud": f"{verb} {who} — {score}", "updated_at": updated_at}


def powerplay_week_start(now: Optional[datetime] = None) -> str:
    """Most recent PowerPlay weekly tick: Thursday ~07:00 UTC (community
    estimate, same as the Faction Expansion Tracker's countdown)."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=(now.weekday() - 3) % 7)).replace(hour=7, minute=0, second=0, microsecond=0)
    if start > now:
        start -= timedelta(days=7)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


# Plain meanings for PowerPlay 2.0 states that are easy to misread
# ("Unoccupied" is not about population).
_PP_STATE_MEANINGS = {
    "Unoccupied": "no power yet",
    "Expansion": "a power is trying to take it",
    "Contested": "powers will fight for it next week",
}


def powerplay_mode(pledged: str, controlling_power: str, pp_state: str, powers_present=None,
                   allies=frozenset()) -> str:
    """Our power controls it -> Reinforcement; an allied power controls it ->
    Allied (never undermined); another power controls it -> Undermining;
    nobody controls it -> Acquisition, but only if our power is
    in range (Frontier: within 20 ly of its Fortified / 30 ly of its
    Stronghold systems) -- the journal shows that as our power appearing in
    the system's Powers list. When that list isn't known, stay permissive."""
    if not pledged:
        return ""
    if controlling_power:
        if _same(controlling_power, pledged):
            return "Reinforcement"
        return "Allied" if _key(controlling_power) in allies else "Undermining"
    if not pp_state:
        return ""
    if powers_present and not any(_same(p, pledged) for p in powers_present):
        return ""
    return "Acquisition"


def _powerplay_guide_short(mode: str, pp_state: str, pledged: str, pp_activities) -> str:
    """One glanceable line: the top three BGS-safe actions, commodity named
    without its collect/deliver route (that's in the full guide tooltip)."""
    if not pledged or not mode or mode == "Allied" or pp_activities is None:
        return _powerplay_guide(mode, pp_state, pledged, pp_activities)
    acts = [a for a in pp_activities.get_actions(mode.lower(), pp_state)
            if a.merits == "yes" and getattr(a, "bgs", "safe") == "safe"]
    acts.sort(key=lambda a: not any(_same(p, pledged) for p in a.bonus_powers))
    names = []
    for a in dict.fromkeys(x.action for x in acts):
        if a == "Transport Powerplay Commodities":
            commodities = POWERPLAY_COMMODITIES.get(_key(pledged))
            route = _COMMODITY_ROUTE.get(mode)
            a = f"Transport {commodities[route[0]]}" if commodities and route else a
        names.append(a)
    return " · ".join(names[:3]) if names else mode


def _powerplay_guide(mode: str, pp_state: str, pledged: str, pp_activities) -> str:
    if not pledged:
        return "Pledge to a power to see PowerPlay actions for this system"
    if not mode:
        return "Not a PowerPlay target for your power right now"
    if mode == "Allied":
        return "Allied power's system — don't undermine it (coalition)"
    if pp_activities is None:
        return mode
    # BGS-safe actions first (squadron rule); "joint" ones also move a minor
    # faction's influence, so only when that faction is being boosted too.
    acts = [a for a in pp_activities.get_actions(mode.lower(), pp_state) if a.merits == "yes"]
    acts.sort(key=lambda a: not any(_same(p, pledged) for p in a.bonus_powers))

    def names(bgs, n):
        picked = dict.fromkeys(a.action for a in acts if getattr(a, "bgs", "safe") == bgs)
        named = []
        for x in picked:
            if x == "Bounty Hunting":
                x = f"{x} (cash vouchers elsewhere)"
            elif x == "Transport Powerplay Commodities":
                x = transport_text(mode, pledged)
            named.append(x)
        return named[:n]

    safe, joint = names("safe", 4), names("joint", 2)
    if not safe and not joint:
        return mode
    text = f"{mode} — BGS-safe: {', '.join(safe)}" if safe else mode
    if joint:
        text += f". Only if also boosting the station's faction: {', '.join(joint)}"
    return text


PP_MODES = ("Reinforcement", "Acquisition", "Undermining")


def _edsm_age_days(edsm_row: dict) -> Optional[int]:
    try:
        when = datetime.fromisoformat(str(edsm_row.get("date"))[:10]).date()
    except (TypeError, ValueError):
        return None
    return (datetime.now(timezone.utc).date() - when).days


def detect_powerplay_mode(pledged: str, pp: Optional[dict], edsm_row: Optional[dict] = None,
                          allies=frozenset()) -> dict:
    """The PowerPlay job in a system for our pledge: {"mode", "source",
    "controller", "state", "range_unconfirmed"}. Our own journal reading
    (pp, repo.get_system_powerplay_snapshot shape) wins; EDSM's daily dump
    row (EdsmPowerPlayCache.get_controller_by_name shape) is the fallback
    for systems not visited yet. EDSM can't show whether our power is in
    range, so an Acquisition guess from it is flagged range_unconfirmed."""
    if pp:
        state = pp.get("pp_state") or ""
        controller = pp.get("pp_controlling_power") or ""
        powers_present = list(pp.get("pp_powers") or []) + list((pp.get("pp_conflict_progress") or {}).keys())
        return {"mode": powerplay_mode(pledged, controller, state, powers_present, allies),
                "source": "your journal", "controller": controller, "state": state, "range_unconfirmed": False}
    if edsm_row:
        state = edsm_row.get("power_state") or ""
        # An Unoccupied EDSM row is a foothold, not control.
        controller = "" if state == "Unoccupied" else (edsm_row.get("power") or "")
        mode = powerplay_mode(pledged, controller, state or "Unoccupied", None, allies)
        age = _edsm_age_days(edsm_row)
        source = "EDSM" if age is None else f"EDSM, {age} day{'s' if age != 1 else ''} old"
        return {"mode": mode, "source": source, "controller": controller, "state": state,
                "range_unconfirmed": mode == "Acquisition"}
    return {"mode": "", "source": "", "controller": "", "state": "", "range_unconfirmed": False}


def describe_detection(det: dict) -> str:
    """One line for the add-task preview, e.g. "Detected: Reinforcement
    (Aisling Duval, Fortified — EDSM, 2 days old)"."""
    if not det["source"]:
        return "No PowerPlay data for this system yet — pick the mode your squadron gave you."
    if not det["mode"]:
        return f"Detected: not a PowerPlay target for your power ({det['source']})"
    who = det["controller"] or "no controlling power"
    extra = " — range unconfirmed until you visit" if det["range_unconfirmed"] else ""
    return f"Detected: {det['mode']} ({who}, {det['state'] or 'unknown state'} — {det['source']}){extra}"


def _hours_ago(iso: str) -> str:
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return ""
    hours = max(0.0, (datetime.now(timezone.utc) - when).total_seconds() / 3600)
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def _acquisition_lines(acquisition: dict, pledged: str, source: str) -> tuple:
    """(reading suffix, extra lines) for per-power acquisition progress
    (0-1, 1.0 = the control threshold). Reaching it by the weekly cycle
    (Thursday ~07:00 UTC) takes the system; two or more powers reaching it
    make it Contested (ED wiki, from Frontier's PowerPlay 2.0 stream)."""
    ours = next((p for p in acquisition if _same(p, pledged)), None)
    shown = ours or max(acquisition, key=acquisition.get)
    suffix = f" — {shown} {acquisition[shown] * 100:.1f}%" + (f" ({source})" if source else "")
    extra = []
    if ours is not None:
        value = acquisition[ours]
        rivals = [p for p, v in acquisition.items() if p != ours and v >= 1.0]
        if value >= 1.0:
            extra.append(f"Threshold reached — {ours} takes it at Thursday's cycle"
                         + (f" unless it's Contested ({', '.join(rivals)} also reached it)" if rivals else ""))
        else:
            extra.append(f"{(1.0 - value) * 100:.1f}% to go before Thursday's cycle "
                         f"(100% = {ours} takes the system)")
    return suffix, extra


def _powerplay_view(pp: Optional[dict], pledged: str, merits: int, pp_activities,
                    allies=frozenset(), declared: str = "", edsm_row: Optional[dict] = None,
                    eddn_progress: Optional[dict] = None, population: Optional[int] = None,
                    cargo: Optional[dict] = None, last_collect: Optional[dict] = None,
                    supporting: Optional[list] = None, collect_system: Optional[dict] = None,
                    collect_batch: Optional[dict] = None,
                    last_delivery: Optional[dict] = None) -> dict:
    merits_line = [f"Your merits here this PowerPlay week: {merits:,}"] if pledged else []
    merits_hud = f" · {merits:,} merits this week" if pledged else ""
    det = detect_powerplay_mode(pledged, pp, edsm_row, allies)
    detected = det["mode"]
    mode = declared or detected
    warnings = []
    if declared and det["source"] and pledged:
        if detected == "Allied":
            warnings.append(f"Task says {declared}, but {det['controller']} is an allied (ZYADA) power — "
                            f"check with your coordinator before undermining")
        elif detected and detected != declared and not (det["range_unconfirmed"] and declared == "Acquisition"):
            who = f"controlled by {det['controller']}" if det["controller"] else "not controlled by any power"
            warnings.append(f"Task says {declared}, but the system is {who} ({detected}) — "
                            f"it may have changed since the objective was set")
        elif not detected and declared == "Acquisition":
            warnings.append("Task says Acquisition, but your power isn't in range here per your journal")

    if not pp:
        if det["source"]:
            reading = f"{det['state'] or 'Unknown'}" + (f", {det['controller']}" if det["controller"] else "")
            head = f"{mode}: {reading} ({det['source']})" if mode else f"{reading} ({det['source']})"
            lines = [head]
            if eddn_progress and eddn_progress.get("progress"):
                suffix, extra = _acquisition_lines(eddn_progress["progress"], pledged,
                                                   f"EDDN, {_hours_ago(eddn_progress.get('date'))}")
                lines[0] += suffix
                lines += extra
            if det["range_unconfirmed"] and mode == "Acquisition":
                lines.append("Range unconfirmed until you visit")
        else:
            head = f"{mode} (from your squadron's objective)" if mode else "No PowerPlay reading yet"
            lines = [head]
        lines += commodity_lines(mode, pledged, cargo, last_collect,
                                 supporting=supporting, collect_system=collect_system, collect_batch=collect_batch,
                                 last_delivery=last_delivery)
        if population is not None:
            lines.append(f"Population: {population_text(population)}")
        hud_head = head if (mode or det["source"]) else "no data yet"
        if pledged and not mode and not det["source"]:
            # Nothing known and no mode given -- don't claim it's "not a target".
            guide = ("No PowerPlay data for this system yet — visit it, or re-add the task with the "
                     "mode from your squadron's objective")
        else:
            guide = _powerplay_guide(mode, det["state"], pledged, pp_activities)
        view = {"status": STATUS_NO_DATA if not det["source"] else STATUS_TRACKING,
                "lines": lines + merits_line, "warnings": warnings,
                "hud": f"PowerPlay — {hud_head}{merits_hud}", "updated_at": None,
                "guide": guide}
        ep = (eddn_progress or {}).get("progress") or {}
        _add_powerplay_structure(view, mode, det["state"], pledged, pp_activities, None, ep,
                                 f"EDDN, {_hours_ago(eddn_progress.get('date'))}" if ep else "",
                                 det["controller"], population, merits,
                                 commodity_info(mode, pledged, cargo, last_collect, supporting=supporting,
                                                collect_system=collect_system, collect_batch=collect_batch, last_delivery=last_delivery),
                                 source_note=det["source"], range_unconfirmed=det["range_unconfirmed"])
        if not det["source"] and not mode:
            view["guide_short"] = guide
        return view

    pp_state = pp.get("pp_state") or ""
    # "Unoccupied" is a PowerPlay state (no controlling power), not population.
    reading = f"{pp_state} ({_PP_STATE_MEANINGS[pp_state]})" if pp_state in _PP_STATE_MEANINGS \
        else (pp_state or "Unknown")
    progress = pp.get("pp_control_progress")
    acquisition = pp.get("pp_conflict_progress") or {}
    source = ""
    # Other commanders' EDDN sighting wins when it's newer than our visit.
    if (eddn_progress and eddn_progress.get("progress") and not isinstance(progress, (int, float))
            and (not acquisition or (eddn_progress.get("date") or "") > (pp.get("pp_data_timestamp") or ""))):
        acquisition = eddn_progress["progress"]
        source = f"EDDN, {_hours_ago(eddn_progress.get('date'))}"
    extra = []
    if isinstance(progress, (int, float)):
        reading += f" — {progress * 100:.1f}%"
    elif acquisition:
        suffix, extra = _acquisition_lines(acquisition, pledged, source)
        reading += suffix
    head = f"{mode}: {reading}" if mode else reading
    lines = [head] + (extra if mode == "Acquisition" else [])
    lines += commodity_lines(mode, pledged, cargo, last_collect,
                             supporting=supporting, collect_system=collect_system, collect_batch=collect_batch, last_delivery=last_delivery)
    if population is not None:
        lines.append(f"Population: {population_text(population)}")
    if pp.get("pp_controlling_power"):
        lines.append(f"Controlled by {pp['pp_controlling_power']}")
    lines += merits_line
    view = {"status": STATUS_TRACKING, "lines": lines, "warnings": warnings,
            "hud": f"PowerPlay — {head}{merits_hud}", "updated_at": pp.get("pp_data_timestamp"),
            "guide": _powerplay_guide(mode, pp_state, pledged, pp_activities)}
    _add_powerplay_structure(view, mode, pp_state, pledged, pp_activities, progress, acquisition, source,
                             pp.get("pp_controlling_power") or "", population, merits,
                             commodity_info(mode, pledged, cargo, last_collect, supporting=supporting,
                                            collect_system=collect_system, collect_batch=collect_batch, last_delivery=last_delivery))
    return view


def _add_powerplay_structure(view: dict, mode: str, pp_state: str, pledged: str, pp_activities,
                             control_progress, acquisition: dict, progress_source: str, controller: str,
                             population, merits: int, info: Optional[dict],
                             source_note: str = "", range_unconfirmed: bool = False) -> None:
    """Bars / chips / short guide for a PowerPlay card (see _make_card)."""
    bars, chips = [], []
    if isinstance(control_progress, (int, float)):
        bars.append({"label": "Control", "value": control_progress, "max": 1.0,
                     "text": f"{control_progress * 100:.1f}%", "state": ""})
    elif acquisition:
        ours = next((p for p in acquisition if _same(p, pledged)), None)
        shown = ours or max(acquisition, key=acquisition.get)
        value = acquisition[shown]
        left = f" — {(1 - value) * 100:.1f}% to go" if ours and value < 1 else (" — threshold reached" if ours else "")
        bars.append({"label": shown if not ours else "Acquired", "value": min(value, 1.0), "max": 1.0,
                     "text": f"{value * 100:.1f}%{left}" + (f" ({progress_source})" if progress_source else ""),
                     "state": "met" if ours and value >= 1 else ""})
    state_txt = f"{pp_state} ({_PP_STATE_MEANINGS[pp_state]})" if pp_state in _PP_STATE_MEANINGS else pp_state
    if state_txt:
        chips.append({"text": state_txt + (f" · {controller}" if controller else ""),
                      "tooltip": source_note or "", "color": ""})
    if range_unconfirmed and mode == "Acquisition":
        chips.append({"text": "range unconfirmed", "color": "#FFB347",
                      "tooltip": "From EDSM -- visit the system to confirm your power is in range"})
    if population is not None:
        chips.append({"text": f"Pop {population_text(population)}"})
    if info:
        if info["carrying"]:
            chips.append({"text": f"Carrying {info['carrying']} t", "color": "#6BCB77",
                          "tooltip": info["name"]})
        if info["collected_ok"]:
            chips.append({"text": f"✓ Collected at {info['collected_ok']} (supporting)", "color": "#6BCB77",
                          "tooltip": "Within range of this target, so the hand-in will be accepted"})
        if info["next_allocation"]:
            batch = info["batch"]
            last = (f"Last load: {batch['tonnes']} t at {batch['station']}"
                    + (f" ({batch['system']})" if batch["system"] and batch["system"] != batch["station"] else "")
                    + f", {_hhmm(batch['last'])}\n") if batch else ""
            ready = info["next_allocation"] == "now"
            chips.append({"text": ("Load ready" if ready else f"Next load ≈{info['next_allocation']}")
                                  + " · any supporting station",
                          "color": "#6BCB77" if ready else "#FFB347",
                          "tooltip": (last + "One allocation for you, shared by every station (seen in game "
                                      f"2026-10-03): about {ALLOCATION_REFRESH_MIN} min after your last load. "
                                      "Loads stack up while you're away, and a rank-up gives a bonus load.")})
        if info["supporting"]:
            n, st, d = info["supporting"][0]
            chips.append({"text": f"Collect at {n} · {d:.1f} ly", "color": "#4DD8C8",
                          "tooltip": "Supporting systems (Fortified ≤20 ly / Stronghold ≤30 ly):\n" + "\n".join(
                              f"{a} ({b}, {c:.1f} ly)" for a, b, c in info["supporting"])})
        elif info["supporting"] is not None:
            chips.append({"text": "No supporting system known", "color": "#FFB347",
                          "tooltip": "Fortified ≤20 ly / Stronghold ≤30 ly -- check the galaxy map's strategic view"})
        if info["last_delivery"]:
            ld = info["last_delivery"]
            chips.append({"text": f"Last hand-in {ld['merits']:,} merits",
                          "tooltip": f"{ld['count']} t {ld['type']} on {str(ld['timestamp'])[:10]}"})
        if info["warning"]:
            view["warnings"] = [info["warning"]] + list(view.get("warnings") or [])
    if pledged:
        chips.append({"key": "merits", "text": f"{merits:,} merits this week ({cp_text(merits)})",
                      "tooltip": "Earned in this system this PowerPlay week.\n" + CP_NOTE})
    view["bars"] = bars
    view["chips"] = chips
    view["detail_lines"] = []
    view["guide_short"] = _powerplay_guide_short(mode, pp_state, pledged, pp_activities)


def _bgs_guide(task: dict, limits: dict, population_basis: str = "") -> str:
    # Wording follows what decides each day per the SINC Complete BGS Guide 2024.
    faction = task.get("faction_name") or "the faction"
    opponent = task.get("opponent_name") or "the other side"
    task_type = task["task_type"]
    if task_type == "hinder":
        # SINC Complete BGS Guide 2024, "Reducing influence" (p36-39), cheapest first.
        return (f"Influence is zero-sum, so boosting the other factions here pushes {faction} down without "
                f"costing reputation. Take missions that show a red − effect on them. Letting their missions "
                f"expire (failing them) costs them about 1 INF each, and you lose reputation with them. "
                f"Trading at a loss or into zero demand, or smuggling, at stations they control also hurts "
                f"them. Clean kills of their ships work but bring big bounties and notoriety — only when "
                f"your coordinator asks.")
    if task_type == "boost":
        return (f"A bit of each: missions for {faction} (about {limits['tier_score']} INF+ per tick), bounties, "
                f"exploration data and high-demand profitable trade at {faction}-controlled stations "
                f"(exobiology and mined goods don't count). {population_basis}").strip()
    if task_type == "vote":
        return (f"Complete election missions for {faction} — they decide each day. Trade, exploration data "
                f"and economic missions only break ties. Combat doesn't count in elections.")
    return (f"Win the most conflict zones for {faction} each day (do the CZ secondary objectives too) — "
            f"low space CZs are the most efficient. Combat bonds (cashed in this system; squad advice: about every 10M), "
            f"massacre missions and bounties only break ties; other actions don't count. "
            f"Don't cash bonds for {opponent}.")


def _population_basis(targets: Optional[dict], population) -> str:
    if targets:
        return (f"Targets for a {targets['size']} system ({population / 1_000_000:.1f} million), "
                f"SINC guidance.")
    return "Targets from Settings (population unknown)."


def build_task_view(task: dict, report: dict, bgs_status: Optional[dict], history: list,
                    pp: Optional[dict], limits: dict, pledged: str = "", merits: int = 0,
                    pp_activities=None, population: Optional[int] = None,
                    today: Optional[date] = None, edsm_row: Optional[dict] = None,
                    squadron_faction: str = "", eddn_progress: Optional[dict] = None,
                    cargo: Optional[dict] = None, last_collect: Optional[dict] = None,
                    supporting: Optional[list] = None, collect_system: Optional[dict] = None,
                    collect_batch: Optional[dict] = None,
                    last_delivery: Optional[dict] = None) -> dict:
    task_type = task["task_type"]
    population_basis = ""
    if task_type == "boost":
        targets = population_targets(population) if limits.get("by_population", True) else None
        if targets:
            limits = dict(limits, **{k: v for k, v in targets.items() if k != "size"})
        population_basis = _population_basis(targets, population)
        view = _boost_view(task, report, history, limits, today)
    elif task_type == "hinder":
        view = _hinder_view(task, report, history, today, squadron_faction)
    elif task_type in ("vote", "fight"):
        view = _conflict_view(task, report, bgs_status, task_type)
    elif task_type == "powerplay":
        view = _powerplay_view(pp, pledged, merits, pp_activities,
                               allied_powers(pledged, limits.get("allied_powers")),
                               declared=task.get("pp_mode") or "", edsm_row=edsm_row,
                               eddn_progress=eddn_progress, population=population,
                               cargo=cargo, last_collect=last_collect,
                               supporting=supporting, collect_system=collect_system, collect_batch=collect_batch,
                               last_delivery=last_delivery)
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
                     pledged: str = "", pp_activities=None, now: Optional[datetime] = None,
                     edsm_powerplay=None, eddn_powerplay=None,
                     cargo: Optional[dict] = None, last_collect: Optional[dict] = None,
                     collect_system: Optional[dict] = None,
                    collect_batch: Optional[dict] = None, deliveries: Optional[dict] = None) -> list[dict]:
    """Views for every task (or only those in system_address), in the
    user's priority order."""
    tasks = repo.list_bgs_tasks()
    if system_address is not None:
        tasks = [t for t in tasks if t["system_address"] == system_address]
    if not tasks:
        return []
    report = repo.get_session_activity_report(since)
    week_start = powerplay_week_start(now)
    squadron_faction = (repo.get_squadron_faction_name() or "") if any(t["task_type"] == "hinder" for t in tasks) else ""
    views = []
    for t in tasks:
        addr = t["system_address"]
        bgs_status = repo.get_bgs_status_for_system(addr) if addr is not None else None
        history = repo.get_faction_history(addr) if addr is not None else []
        pp = repo.get_system_powerplay_snapshot(addr) if addr is not None else None
        merits = (repo.get_powerplay_merits_since(addr, week_start)
                  if t["task_type"] == "powerplay" and pledged and addr is not None else 0)
        population = (repo.get_system_population(addr)
                      if t["task_type"] in ("boost", "powerplay") and addr is not None else None)
        # EDSM's daily dump fills in systems we haven't visited yet.
        edsm_row = (edsm_powerplay.get_controller_by_name(t["system_name"])
                    if t["task_type"] == "powerplay" and not pp and edsm_powerplay else None)
        views.append(build_task_view(t, report, bgs_status, history, pp, limits,
                                     pledged=pledged, merits=merits, pp_activities=pp_activities,
                                     population=population, edsm_row=edsm_row,
                                     squadron_faction=squadron_faction,
                                     eddn_progress=(eddn_powerplay.get_conflict_progress(addr)
                                                    if t["task_type"] == "powerplay" and eddn_powerplay else None),
                                     cargo=cargo, last_collect=last_collect,
                                     supporting=(supporting_systems(repo, pledged, t["system_name"], edsm_powerplay)
                                                 if t["task_type"] == "powerplay" and pledged else None),
                                     collect_system=collect_system, collect_batch=collect_batch,
                                     last_delivery=(deliveries or {}).get((t["system_name"] or "").lower())))
        if t["task_type"] == "powerplay" and pledged and addr is not None:
            _add_progress_trend(views[-1], repo, addr, pledged)
            _add_control_chip(views[-1], repo, addr, merits)
            tick = repo.get_powerplay_merits_since(addr, since)
            for chip in views[-1].get("chips") or []:
                if chip.get("key") == "merits":
                    chip["text"] = f"{tick:,} merits this tick · " + chip["text"].replace(" merits this week", " this week")
                    chip["tooltip"] = ("This tick: since the last BGS tick (daily). This week: since the Thursday "
                                       "PowerPlay reset.\n" + CP_NOTE)
    return views


def _cycle_reading(repo, addr: int, now: Optional[datetime] = None):
    """Latest reinforcement/undermining reading from the current PowerPlay
    cycle only -- both reset at the weekly tick, so an older one says
    nothing about this week."""
    getter = getattr(repo, "get_pp_control_reading", None)
    row = getter(addr) if getter else None
    return row if row and row["observed_at"] >= powerplay_week_start(now) else None


def control_status(repo, addr: int, now: Optional[datetime] = None) -> Optional[dict]:
    """This cycle's reinforcement/undermining split into weekly decay and
    real attack. Decay is counted as undermining and set at the weekly
    reset (Update 3.4; Ekono's undermining stayed constant all week for 10
    cycles running), so undermining at the first reading of the cycle is
    taken as decay and only growth after it as attack. A first reading taken
    days after the reset can hide an early attack inside "decay", so when
    the first reading is more than BASELINE_LATE_H after the reset the split
    is "unknown" rather than guessed."""
    row = _cycle_reading(repo, addr, now)
    if not row or (row["reinforcement"] is None and row["undermining"] is None):
        return None
    first_getter = getattr(repo, "get_pp_control_first", None)
    first = first_getter(addr, powerplay_week_start(now)) if first_getter else None
    r, u = row["reinforcement"] or 0, row["undermining"] or 0
    decay = min(u, (first["undermining"] or 0) if first else u)
    attack = u - decay
    week = datetime.fromisoformat(powerplay_week_start(now).replace("Z", "+00:00"))
    late = (not first) or datetime.fromisoformat(
        first["observed_at"].replace("Z", "+00:00")) > week + timedelta(hours=BASELINE_LATE_H)
    if attack > 0:
        status = "attack"
    elif u > r:
        status = "unknown" if late else "decay"
    else:
        status = "holding"
    return {"row": row, "reinforcement": r, "undermining": u, "decay": decay, "attack": attack, "status": status,
            "baseline_at": first["observed_at"] if first else None}


def _gained_since_tick(repo, addr: int, since: str, undermining: int, now: Optional[datetime] = None):
    """Undermining gained since the BGS tick, or None when there's no reading
    between the weekly reset and the tick to compare with (then it can't be
    told apart from the reset's decay)."""
    base = repo.get_pp_control_reading(addr, since)
    if not base or base["observed_at"] < powerplay_week_start(now) or base["undermining"] is None:
        return None
    return max(0, undermining - base["undermining"])


def _add_control_chip(view: dict, repo, addr: int, merits_week: int, now: Optional[datetime] = None) -> None:
    """Chip: this cycle's reinforcement vs undermining (decay vs real attack,
    see control_status) and your estimated share."""
    cs = control_status(repo, addr, now)
    if not cs or "chips" not in view:
        return
    r, decay, attack = cs["reinforcement"], cs["decay"], cs["attack"]
    if cs["status"] == "attack":
        text, color = f"Undermined +{attack:,} this cycle (+{decay:,} decay) vs reinforced {r:,}", "#FF6B6B"
    elif cs["status"] == "decay":
        text, color = f"Reinforced {r:,} vs decay \u2248{decay:,} \u00b7 {decay - r:,} to break even", "#FFB347"
    elif cs["status"] == "unknown":
        text, color = (f"Reinforced {r:,} vs undermined {cs['undermining']:,} \u00b7 decay or attack? "
                       "(first reading this cycle came late)"), "#FFB347"
    else:
        text, color = f"Reinforced {r:,} vs decay \u2248{decay:,} \u00b7 holding", "#6BCB77"
    share = round(merits_week / MERITS_PER_CP)
    if share:
        text += f" \u00b7 your share \u2248{share:,}" + (f" ({share * 100 // r}%)" if r else "")
    row = cs["row"]
    view["chips"].insert(0, {
        "text": text, "color": color,
        "tooltip": (f"This cycle so far, from all commanders ({row['source']}, {_hours_ago(row['observed_at'])}). "
                    "The weekly control decay is counted as undermining and set at the reset; only undermining "
                    "that grows during the week is a real attack. Decay alone can't drop a state.\n"
                    "Your share is your merits here this week \u00f7 4 (estimate).")})


_HELD_STATES = ("Exploited", "Fortified", "Stronghold")
BASELINE_LATE_H = 48   # first reading of a cycle later than this after the reset: decay/attack split unknown


def pp_watch(repo, pledged: str, edsm_powerplay=None) -> dict:
    """{system address: why it's watched} for reinforcement/undermining
    readings: PowerPlay task systems, the supporting systems of Acquisition
    tasks (a Stronghold undermined to Fortified drops from 30 to 20 ly reach),
    and squadron-faction systems your power controls. All dynamic."""
    out = {}
    tasks = [t for t in repo.list_bgs_tasks() if t["task_type"] == "powerplay" and t["system_address"]]
    for t in tasks:
        out[t["system_address"]] = "PowerPlay task"
    if not pledged:
        return out
    for t in tasks:
        snap = repo.get_system_powerplay_snapshot(t["system_address"]) or {}
        mode = t.get("pp_mode") or ("" if snap.get("pp_state") in _HELD_STATES else "Acquisition")
        if mode != "Acquisition":
            continue
        names = [n for n, _s, _d in supporting_systems(repo, pledged, t["system_name"], edsm_powerplay)]
        for name, addr in repo.get_system_addresses_for_names(names).items():
            out.setdefault(addr, f"supports {t['system_name']}")
    held = set(edsm_powerplay.held_systems(pledged, _HELD_STATES)) if edsm_powerplay else set()
    for name, (state, _ts) in repo.get_held_systems_from_journal(pledged).items():
        (held.add if state in _HELD_STATES else held.discard)(name)
    for name, addr in repo.get_squadron_faction_systems().items():
        if name in held:
            out.setdefault(addr, "squad system")
    return out


def watch_rows(repo, since: str, watch: dict, now: Optional[datetime] = None) -> list:
    """One row per watched system for the PowerPlay Watch List: latest
    reinforcement/undermining this cycle, undermining gained since the BGS
    tick, why it's watched. Systems losing (undermining ahead) first, biggest
    gap first; then the rest by name. No reading yet -> numbers are None."""
    names = repo.get_system_names_for_addresses(list(watch))
    rows = []
    for addr, why in watch.items():
        cs = control_status(repo, addr, now)
        row = cs["row"] if cs else None
        r = u = gained = None
        if cs:
            r, u = cs["reinforcement"], cs["undermining"]
            gained = _gained_since_tick(repo, addr, since, u, now) if row["observed_at"] > since else 0
        rows.append({"address": addr, "name": names.get(addr, str(addr)), "why": why,
                     "state": row["pp_state"] if row else None, "reinforcement": r, "undermining": u,
                     "decay": cs["decay"] if cs else None, "attack": cs["attack"] if cs else None,
                     "status": cs["status"] if cs else None,
                     "gained": gained, "observed_at": row["observed_at"] if row else None,
                     "source": row["source"] if row else None,
                     "losing": bool(cs) and cs["status"] == "attack"})
    order = {"attack": 0, "unknown": 1, "decay": 2, "holding": 3, None: 4}
    rows.sort(key=lambda x: (order[x["status"]], -(x["attack"] or 0) if x["status"] == "attack"
                             else -((x["decay"] or 0) - (x["reinforcement"] or 0)), x["name"].lower()))
    return rows


def undermining_alerts(repo, since: str, watch: dict, now: Optional[datetime] = None) -> list:
    """[(system name, undermining gained since `since`, undermining,
    reinforcement, why watched)] where undermining grew since the BGS tick
    and is ahead of reinforcement."""
    out = []
    names = {}
    for addr in watch:
        now_row = _cycle_reading(repo, addr, now)
        if not now_row or now_row["observed_at"] <= since or now_row["undermining"] is None:
            continue
        u, r = now_row["undermining"] or 0, now_row["reinforcement"] or 0
        gained = _gained_since_tick(repo, addr, since, u, now)
        if gained and u > r:
            if not names:
                names = repo.get_system_names_for_addresses(list(watch))
            out.append((names.get(addr, str(addr)), gained, u, r, watch[addr]))
    return sorted(out, key=lambda t: -t[1])


def _add_progress_trend(view: dict, repo, addr: int, pledged: str) -> None:
    """Chip: how your power's acquisition progress moved over the stored
    readings, with your merits here between each pair on hover -- the raw
    data for measuring merits per control point."""
    getter = getattr(repo, "get_pp_progress_history", None)
    hist = getter(addr, pledged) if getter else []
    if len(hist) < 2 or "chips" not in view:
        return
    (new_at, new_p, _s), (old_at, old_p, _s2) = hist[0], hist[-1]
    delta = (new_p - old_p) * 100
    tips = []
    for (b_at, b_p, b_src), (a_at, a_p, _x) in zip(hist, hist[1:]):
        mine = repo.get_powerplay_merits_between(addr, a_at, b_at)
        tips.append(f"{a_at[5:16].replace('T', ' ')} → {b_at[5:16].replace('T', ' ')}: "
                    f"{(b_p - a_p) * 100:+.3f}% ({b_src}) · your merits here: {mine:,}")
    view["chips"].insert(0, {
        "text": f"{delta:+.2f}% since {old_at[5:16].replace('T', ' ')}",
        "color": "#6BCB77" if delta > 0 else ("#FF6B6B" if delta < 0 else ""),
        "tooltip": "Acquisition progress changes (UTC), newest first:\n" + "\n".join(tips)
                   + "\nOther commanders move it too; Frontier updates it in batches, not per hand-in.",
    })


def hud_line(views: list) -> str:
    parts = [v["hud"] for v in views if v.get("hud")]
    return ("Squadron task: " + " · ".join(parts)) if parts else ""
