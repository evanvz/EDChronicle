import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Tuple
from .state import GameState
from pathlib import Path
from .planet_values import PlanetValueTable
from .exo_values import ExoValueTable
from .external_intel import ExternalIntel
from edc.engine.handlers import exploration, exobio, inventory, powerplay, misc, fleet_carrier, mining, engineers
from edc.core.squadron_events import SQUADRON_EVENT_NAMES, apply_squadron_event
from edc.core.mission_events import MISSION_EVENT_NAMES, apply_mission_event
from edc.core.bgs_conflicts import find_squadron_war_enemy, squadron_faction_name
from edc.core.ship_loadout import has_any_weapon
from edc.core.ring_signals import RING_NAME_RE as _RING_NAME_RE, parse_ring_hotspots

log = logging.getLogger("edc.event_engine")

logger = logging.getLogger(__name__)

# Ground CZ intensity thresholds, verified against the real-world reference
# implementation (aussig/BGS-Tally) — Frontier doesn't report CZ size
# directly, so it's inferred from the combat bond amount, self-correcting
# upward as bigger bonds arrive (kills split across a team start low).
_CZ_GROUND_LOW_CB_MAX = 5000
_CZ_GROUND_MED_CB_MAX = 38000
_CZ_PENDING_TIMEOUT_S = 300  # 5 minutes since approach/drop, else assume we've moved on


def _journal_age_seconds(older_ts: str, newer_ts: str) -> float:
    try:
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(newer_ts, fmt) - datetime.strptime(older_ts, fmt)).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def _derive_conflicts_from_factions(factions: list) -> list:
    from collections import defaultdict
    war_factions: dict = defaultdict(list)
    for f in factions:
        if not isinstance(f, dict):
            continue
        for s in (f.get("ActiveStates") or []):
            state_name = str(s.get("State") or "").lower()
            if state_name in ("war", "civilwar"):
                war_factions[state_name].append(f.get("Name", ""))
    conflicts = []
    for war_type, names in war_factions.items():
        for i in range(0, len(names), 2):
            conflicts.append({
                "WarType": war_type,
                "Status": "active",
                "Faction1": {"Name": names[i] if i < len(names) else "", "Stake": "", "WonDays": 0},
                "Faction2": {"Name": names[i + 1] if i + 1 < len(names) else "", "Stake": "", "WonDays": 0},
            })
    return conflicts


def _engage_risk(wanted: bool, hostile: bool, power: str | None, pledged: str | None,
                  ctrl: str | None, government: str | None, enemy: bool = False) -> str:
    """
    Returns "safe", "caution", or "unknown" -- whether killing a contact
    with these attributes is expected to draw a bounty against the
    player. Deliberately conservative: anything not confidently known
    safe defaults to "unknown", never a false "safe".

    LegalStatus "Enemy" (an opposing PowerPlay power's own combatant) is
    safe to kill wherever encountered, not just in the player's own
    controlled territory -- confirmed externally (community-verified PP
    mechanics): the bounty risk belongs to a rival power's *Clean* local
    faction ship outside your own territory, not to an Enemy-flagged
    combatant itself. The pp_enemy/in_my_pp_space inference below is kept
    as a fallback for the rare case LegalStatus isn't populated.
    """
    if wanted or hostile or enemy:
        return "safe"
    p = (pledged or "").strip().lower()
    in_my_pp_space = bool(p and ctrl and ctrl.strip().lower() == p)
    pp_enemy = bool(p and power and power.strip().lower() != p)
    if in_my_pp_space and pp_enemy:
        return "safe"
    if "anarchy" in (government or "").lower():
        return "caution"
    return "unknown"


_COMBAT_RANK_TIERS = (
    "harmless", "mostly harmless", "novice", "competent",
    "expert", "master", "dangerous", "deadly", "elite",
)


def _wanted_rank_meets_player(pilot_rank: str, player_combat_rank: int | None) -> bool:
    """
    True if killing a Wanted contact of this rank would still earn the
    player non-zero Combat rank progress. Elite Dangerous's own combat-
    rank formula is progress_multiplier = max(0, 1.0 + 0.25 * (target_idx
    - player_idx)) -- confirmed against two independent community data
    points (a Deadly-rank player: Elite=1.25/Deadly=1.00/Dangerous=0.75/
    Master=0.50/Expert=0.25/below Expert=0; a Novice-rank player:
    Harmless=0.5/Elite=2.5 -- both fit this formula exactly). That hits
    zero exactly 4 tiers below the player's own rank, so a target ranked
    up to 3 tiers below still counts. Missing/unparseable data defaults
    to True (still call out): we'd rather over-call on an unknown than
    silently drop a real one.
    """
    if player_combat_rank is None:
        return True
    try:
        idx = _COMBAT_RANK_TIERS.index((pilot_rank or "").strip().lower())
    except ValueError:
        return True
    return idx >= player_combat_rank - 3


def _callout_reason(
    hostile: bool, enemy: bool, wanted: bool, power: str, faction: str,
    pledged: str, squadron_faction: str,
    ctrl: str, system_powers: list, pp_state: str,
    pilot_rank: str = "", player_combat_rank: int | None = None,
) -> str | None:
    """
    Returns "enemy" or None -- whether a scanned contact is worth a voice
    callout at all (any callout, not which words to use).

    Callout-worthy: LegalStatus Hostile or Enemy (unconditional -- the game
    has already decided this is fair game), a Wanted ship still worth
    non-zero Combat rank progress against the player's own rank (see
    _wanted_rank_meets_player -- a Wanted ship far enough below our own
    rank earns nothing, not worth a callout), or a rival PowerPlay power's
    ship while we hold PP stake in this system
    (control it, are one of the contesting powers, or it's Contested).

    Combat rank alone (outside the Wanted-rank check above) is never a
    reason to call a ship out -- an earlier version added a rank-tier-in-
    relevant-system trigger, but live testing showed it fired for plenty
    of Clean, non-wanted ships the player had no reason to act on.
    Removed; rank still affects phrase wording (CombatPhrases.ship_targeted's
    "High value target" clause).

    Never fires for a Clean ship that's ours -- our pledged PowerPlay
    power, or our squadron-aligned faction -- we don't shoot our own. But
    that protection doesn't extend to a Hostile/Enemy/Wanted ship even
    from our own faction/power: LegalStatus already means the game (or
    that faction's own bounty system) has decided this one is fair game,
    membership be damned (confirmed live: 500k+ bounty Wanted ships
    belonging to our own squadron-aligned faction -- i.e. that faction's
    own criminals -- were being silently suppressed here). Also never
    fires for law enforcement/security faction ships, regardless of
    category.
    """
    power_l = (power or "").strip().lower()
    pledged_l = (pledged or "").strip().lower()
    is_own_power = bool(pledged_l and power_l and power_l == pledged_l)
    is_own_faction = bool(squadron_faction and faction and faction == squadron_faction)
    legally_fair_game = hostile or enemy or wanted
    if (is_own_power or is_own_faction) and not legally_fair_game:
        return None

    faction_l = (faction or "").strip().lower()
    if "internal security" in faction_l or "security service" in faction_l:
        return None

    if hostile or enemy:
        return "enemy"
    if wanted and _wanted_rank_meets_player(pilot_rank, player_combat_rank):
        return "enemy"

    in_my_pp_space = bool(pledged_l and (
        (ctrl or "").strip().lower() == pledged_l
        or pledged_l in [p.strip().lower() for p in (system_powers or [])]
        or (pp_state or "").strip().lower() == "contested"
    ))
    pp_enemy = bool(pledged_l and power_l and power_l != pledged_l)
    if in_my_pp_space and pp_enemy:
        return "enemy"

    return None


class EventEngine:
    def __init__(
        self,
        state: GameState,
        settings_base: Path,
        planet_values: PlanetValueTable | None = None,
        exo_values: ExoValueTable | None = None,
        external_intel: ExternalIntel | None = None,
    ):
        self.state = state
        self.planet_values = PlanetValueTable.load_from_paths(settings_base / "planet_values.json")
        self.exo_values = ExoValueTable.load_from_paths(settings_base / "exo_values.json")
        self.external_intel = external_intel

    def _apply_external_intel(self, system_name: str | None, system_address: Any = None) -> None:
        # Advisory only; never overrides journal truth.
        try:
            if not system_name or not self.external_intel:
                self.state.external_pois = []
                return
            addr = system_address if isinstance(system_address, int) else None
            self.state.external_pois = self.external_intel.get_pois(system_name, addr)
        except Exception:
            self.state.external_pois = []

    def _classify_system_signal(self, signal_name: str, uss_type: str, is_station: Any, signal_type: Any = None) -> str:
        """
        Journal-derived classification to keep UI low-noise.
        Categories: Megaship | FleetCarrier | Station | Installation
                    | NavBeacon | TouristBeacon | USS | Phenomena | Other
        """
        try:
            st = (signal_type or "").strip().lower()
            if st == "megaship":
                return "Megaship"
            if st == "fleetcarrier":
                return "FleetCarrier"
            if st == "installation":
                return "Installation"
            if st == "navbeacon":
                return "NavBeacon"
            if st == "touristbeacon":
                return "TouristBeacon"
            if isinstance(is_station, bool) and is_station:
                return "Station"
            if uss_type == "$USS_Type_NonHuman;":
                return "NHSS"
            if isinstance(uss_type, str) and uss_type.strip():
                return "USS"
            s = signal_name if isinstance(signal_name, str) else ""
            sl = s.lower()
            if any(k in sl for k in (
                "lagrange", "cloud", "anomal", "phenomen",
                "notable", "stellar"
            )):
                return "Phenomena"
            if sl.startswith("crashed") or "wreckage" in sl or "distress call" in sl:
                return "Wreckage"
        except Exception:
            pass
        return "Other"

    def _norm_text(self, v: Any) -> str:
        """
        Normalize journal-provided strings for stable dict keys and dedupe.
        Collapses internal whitespace and strips leading/trailing spaces.
        """
        if not isinstance(v, str):
            return ""
        try:
            return " ".join(v.split())
        except Exception:
            return v.strip()

    def _parse_materials_category(self, items: Any) -> tuple[Dict[str, int], Dict[str, str]]:
        """
        Parse Materials event category list into:
        counts: name(lower) -> Count(int)
        loc:    name(lower) -> Name_Localised (or best-effort display)
        """
        counts: Dict[str, int] = {}
        loc: Dict[str, str] = {}
        if not isinstance(items, list):
            return counts, loc
        for rec in items:
            if not isinstance(rec, dict):
                continue
            nm = rec.get("Name")
            cnt = rec.get("Count")
            if not isinstance(nm, str) or not isinstance(cnt, int):
                continue
            key = nm.strip().lower()
            if not key:
                continue
            counts[key] = cnt
            nl = rec.get("Name_Localised")
            if isinstance(nl, str) and nl.strip():
                loc[key] = nl.strip()
            else:
                # Best-effort display (raw usually has no Name_Localised)
                loc[key] = key.replace("_", " ").title()
        return counts, loc

    def _parse_shiplocker_items(self, items: Any) -> tuple[Dict[str, int], Dict[str, str]]:
        """
        Parse ShipLocker.Items into aggregated inventory:
        counts: name(lower) -> total Count(int)
        loc:    name(lower) -> Name_Localised (best-effort display)
        Notes:
        - Items can repeat with different MissionID; we aggregate totals by Name.
        """
        counts: Dict[str, int] = {}
        loc: Dict[str, str] = {}
        if not isinstance(items, list):
            return counts, loc
        for rec in items:
            if not isinstance(rec, dict):
                continue
            nm = rec.get("Name")
            cnt = rec.get("Count")
            if not isinstance(nm, str) or not isinstance(cnt, int):
                continue
            key = nm.strip().lower()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + cnt
            nl = rec.get("Name_Localised")
            if isinstance(nl, str) and nl.strip():
                loc[key] = nl.strip()
            else:
                loc[key] = key.replace("_", " ").title()
        return counts, loc           

    def _credit_cz_kill(self, event: Dict[str, Any]) -> None:
        """A FactionKillBond landing inside the pending-CZ window confirms
        the zone was real (not just a settlement/warzone we passed near)
        and credits the awarding faction's CZ tally at the inferred size."""
        reward = event.get("Reward")
        faction_name = event.get("AwardingFaction")
        ts = event.get("timestamp") or ""
        if not isinstance(reward, int) or not isinstance(faction_name, str) or not faction_name:
            return

        pending_settlement = self.state.cz_pending_settlement
        pending_space = self.state.cz_pending_space

        if pending_settlement and _journal_age_seconds(pending_settlement.get("timestamp") or "", ts) <= _CZ_PENDING_TIMEOUT_S:
            pending_settlement["timestamp"] = ts
            previous_size = pending_settlement.get("size")
            if reward < _CZ_GROUND_LOW_CB_MAX:
                new_size = "l"
            elif reward < _CZ_GROUND_MED_CB_MAX:
                new_size = "m"
            else:
                new_size = "h"
            # Self-corrects upward only (team kills can split a bond low at
            # first) — never downgrades an already-confirmed larger size.
            size_rank = {"l": 1, "m": 2, "h": 3}
            if previous_size is None or size_rank[new_size] > size_rank[previous_size]:
                tally = self.state.cz_kills.setdefault(faction_name, {})
                if previous_size is not None:
                    key = f"ground_{previous_size}"
                    tally[key] = max(0, tally.get(key, 0) - 1)
                tally[f"ground_{new_size}"] = tally.get(f"ground_{new_size}", 0) + 1
                pending_settlement["size"] = new_size
            return

        if pending_space and _journal_age_seconds(pending_space.get("timestamp") or "", ts) <= _CZ_PENDING_TIMEOUT_S:
            pending_space["timestamp"] = ts
            if not pending_space.get("counted"):
                pending_space["counted"] = True
                size = pending_space.get("type", "l")
                tally = self.state.cz_kills.setdefault(faction_name, {})
                tally[f"space_{size}"] = tally.get(f"space_{size}", 0) + 1

    def _at_squadron_faction_station(self) -> bool:
        """True if the current system's controlling faction is the
        squadron-aligned faction — the BGS crediting rule for bounty
        redemption and trading (verified: influence is credited to
        whichever faction owns the station you transact at)."""
        faction = self.state.controlling_faction
        return bool(faction) and faction == squadron_faction_name(self.state.factions)

    def process(self, event: Dict[str, Any]) -> Tuple[GameState, List[str]]:
        """
        Returns: (updated_state, ui_messages)
        """
        msgs: List[str] = []
        name = event.get("event")
        self.state.last_event = name

        # ---- DEBUG TRACE: Event start snapshot ----
        try:
            log.debug(
                "EVENT START: %s | bodies=%d exo=%d signals=%d combat=%d",
                name,
                len(self.state.bodies),
                len(self.state.exo),
                len(self.state.system_signals),
                len(self.state.combat_contacts),
            )
        except Exception:
            pass

        credits_now = event.get("Credits")
        if isinstance(credits_now, int):
            self.state.credits = credits_now

        if name == "Location":
            # Happens on login; great for HUD
            new_sys = event.get("StarSystem", self.state.system)
            new_system_address = event.get("SystemAddress")
            if new_sys and new_sys != self.state.system:
                self.state.bodies.clear()
                self.state.exo.clear()
                self.state.body_id_to_name.clear()
                self.state.resolved_body_ids.clear()
                self.state.bio_signals.clear()
                self.state.human_signals.clear()
                self.state.bio_genuses.clear()
                self.state.geo_signals.clear()
                self.state.thargoid_signals.clear()
                self.state.other_signals.clear()
                self.state.non_body_count = None
                self.state.system_signals = []
                self.state.external_pois = []
                self.state.system_body_count = None
                self.state.system_allegiance = None
                self.state.system_government = None
                self.state.system_economy = None
                self.state.system_economy_secondary = None
                self.state.system_state = None
                self.state.system_security = None
                self.state.population = None
                self.state.controlling_faction = None
                self.state.factions = []
                self.state.system_controlling_power = None
                self.state.system_powerplay_state = None
                self.state.system_powers = []
                self.state.system_powerplay_conflict_progress = {}
                self.state.system_powerplay_control_progress = None
                self.state.system_powerplay_reinforcement = None
                self.state.system_powerplay_undermining = None
                self.state.pp_enemy_alerts.clear()
                self.state.combat_contacts.clear()
                self.state.combat_current_key = ""

                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_contacts.clear()
                self.state.combat_current_key = ""
            self.state.system = new_sys
            if isinstance(new_system_address, int):
                self.state.system_address = new_system_address
            entry_body_id = event.get("BodyID")
            if isinstance(entry_body_id, int):
                self.state.resolved_body_ids.add(entry_body_id)
            self.state.in_hyperspace = False
            self.state.jump_star_class = None

            self.state.system_allegiance = event.get("SystemAllegiance")
            self.state.system_government = event.get("SystemGovernment_Localised") or event.get("SystemGovernment")
            self.state.system_economy = (
                event.get("SystemEconomy_Localised")
                or event.get("SystemEconomy")
                or None
            )
            self.state.system_economy_secondary = (
                event.get("SystemSecondEconomy_Localised")
                or event.get("SystemSecondEconomy")
                or None
            )
            self.state.system_state = event.get("SystemState") or None
            self.state.system_security = event.get("SystemSecurity_Localised") or event.get("SystemSecurity")
            self.state.population = event.get("Population")
            cf = event.get("SystemFaction", {}) or {}
            self.state.controlling_faction = cf.get("Name")
            self.state.factions = event.get("Factions", []) or []
            self.state.factions_timestamp = event.get("timestamp") or ""
            conflicts_raw = event.get("Conflicts")
            if conflicts_raw is not None:
                self.state.system_conflicts = [c for c in conflicts_raw if isinstance(c, dict)]
            else:
                self.state.system_conflicts = _derive_conflicts_from_factions(self.state.factions)

            # Powerplay (if present in this system)
            cp = event.get("ControllingPower")
            self.state.system_controlling_power = cp if cp else None

            pps = event.get("PowerplayState")
            self.state.system_powerplay_state = pps if pps else None

            cprog = event.get("PowerplayStateControlProgress")
            self.state.system_powerplay_control_progress = cprog if cprog is not None else None

            rein = event.get("PowerplayStateReinforcement")
            self.state.system_powerplay_reinforcement = rein if rein is not None else None

            und = event.get("PowerplayStateUndermining")
            self.state.system_powerplay_undermining = und if und is not None else None

            # Only update powers if event actually includes them
            pw = event.get("Powers")
            self.state.system_powers = [p for p in pw if isinstance(p, str)] if isinstance(pw, list) else []

            star_pos = event.get("StarPos")
            if isinstance(star_pos, list) and len(star_pos) == 3:
                try:
                    self.state.system_x = float(star_pos[0])
                    self.state.system_y = float(star_pos[1])
                    self.state.system_z = float(star_pos[2])
                except (TypeError, ValueError):
                    pass

            # Force PowerPlay UI refresh after Location update
            msgs.append("refresh_powerplay")
            prog = {}
            for rec in (event.get("PowerplayConflictProgress") or []):
                if isinstance(rec, dict) and isinstance(rec.get("Power"), str):
                    cp = rec.get("ConflictProgress")
                    if isinstance(cp, (int, float)):
                        prog[rec["Power"]] = float(cp)
            self.state.system_powerplay_conflict_progress = prog
            self._apply_external_intel(self.state.system, event.get("SystemAddress"))
            if self.state.system:
                msgs.append(f"Location: {self.state.system}")

        elif name == "FSDJump":
            new_sys = event.get("StarSystem", self.state.system)
            new_system_address = event.get("SystemAddress")
            # FSDJump can re-fire for the system we're already in (e.g.
            # journal replay after a disconnect/reconnect) -- clearing
            # unconditionally dropped resolved_body_ids to just the entry
            # body every time, producing a false "bodies unresolved"
            # regression despite nothing having changed. Only clear on a
            # genuine system change, like Location does.
            system_changed = new_sys != self.state.system or (
                isinstance(new_system_address, int)
                and new_system_address != self.state.system_address
            )
            self.state.system = new_sys
            if isinstance(new_system_address, int):
                self.state.system_address = new_system_address
            if system_changed:
                self.state.resolved_body_ids.clear()
            entry_body_id = event.get("BodyID")
            if isinstance(entry_body_id, int):
                self.state.resolved_body_ids.add(entry_body_id)
            self.state.in_hyperspace = False
            self.state.jump_star_class = None

            # PowerPlay data is often present directly on FSDJump.
            cp = event.get("ControllingPower")
            self.state.system_controlling_power = cp if cp else None

            pps = event.get("PowerplayState")
            self.state.system_powerplay_state = pps if pps else None

            cprog = event.get("PowerplayStateControlProgress")
            self.state.system_powerplay_control_progress = cprog if cprog is not None else None

            rein = event.get("PowerplayStateReinforcement")
            self.state.system_powerplay_reinforcement = rein if rein is not None else None

            und = event.get("PowerplayStateUndermining")
            self.state.system_powerplay_undermining = und if und is not None else None

            pw = event.get("Powers")
            self.state.system_powers = [p for p in pw if isinstance(p, str)] if isinstance(pw, list) else []

            prog = {}
            for rec in (event.get("PowerplayConflictProgress") or []):
                if isinstance(rec, dict) and isinstance(rec.get("Power"), str):
                    cpct = rec.get("ConflictProgress")
                    if isinstance(cpct, (int, float)):
                        prog[rec["Power"]] = float(cpct)
            self.state.system_powerplay_conflict_progress = prog

            cf = event.get("SystemFaction", {}) or {}
            self.state.controlling_faction = cf.get("Name")
            self.state.system_allegiance = event.get("SystemAllegiance")
            self.state.system_government = event.get("SystemGovernment_Localised") or event.get("SystemGovernment")
            self.state.system_economy = event.get("SystemEconomy_Localised") or event.get("SystemEconomy") or None
            self.state.system_economy_secondary = event.get("SystemSecondEconomy_Localised") or event.get("SystemSecondEconomy") or None
            self.state.system_security = event.get("SystemSecurity_Localised") or event.get("SystemSecurity")
            self.state.population = event.get("Population")
            factions = event.get("Factions") or []
            self.state.factions = [f for f in factions if isinstance(f, dict)]
            self.state.factions_timestamp = event.get("timestamp") or ""
            conflicts_raw = event.get("Conflicts")
            if conflicts_raw is not None:
                self.state.system_conflicts = [c for c in conflicts_raw if isinstance(c, dict)]
            else:
                self.state.system_conflicts = _derive_conflicts_from_factions(self.state.factions)

            star_pos = event.get("StarPos")
            if isinstance(star_pos, list) and len(star_pos) == 3:
                try:
                    self.state.system_x = float(star_pos[0])
                    self.state.system_y = float(star_pos[1])
                    self.state.system_z = float(star_pos[2])
                except (TypeError, ValueError):
                    pass

            self._apply_external_intel(self.state.system, new_system_address)
            msgs.append("refresh_powerplay")
            if self.state.system:
                msgs.append(f"FSDJump: {self.state.system}")

        elif name == "FSDTarget":
            target_name = event.get("Name")
            target_star_class = event.get("StarClass")
            remaining_jumps = event.get("RemainingJumpsInRoute")

            self.state.route_target_system = (
                target_name if isinstance(target_name, str) and target_name.strip() else None
            )
            self.state.route_target_star_class = (
                target_star_class if isinstance(target_star_class, str) and target_star_class.strip() else None
            )
            self.state.route_remaining_jumps = (
                remaining_jumps if isinstance(remaining_jumps, int) else None
            )

        elif name == "StartJump":
            # Clear live per-system state as soon as hyperspace starts and show destination.
            if event.get("JumpType") == "Hyperspace":
                target = event.get("StarSystem")
                star_class = event.get("StarClass")

                # Clear per-system exploration / scan state
                self.state.bodies.clear()
                self.state.exo.clear()
                self.state.body_id_to_name.clear()
                self.state.resolved_body_ids.clear()
                self.state.bio_signals.clear()
                self.state.human_signals.clear()
                self.state.bio_genuses.clear()
                self.state.geo_signals.clear()
                self.state.non_body_count = None
                self.state.system_signals = []
                self.state.external_pois = []
                self.state.system_body_count = None
                self.state.fss_complete = False

                # Clear per-system info
                self.state.system_allegiance = None
                self.state.system_government = None
                self.state.system_economy = None
                self.state.system_economy_secondary = None
                self.state.system_state = None
                self.state.system_security = None
                self.state.population = None
                self.state.controlling_faction = None
                self.state.factions = []
                self.state.system_conflicts = []

                # Clear per-system PowerPlay info
                self.state.system_controlling_power = None
                self.state.system_powerplay_state = None
                self.state.system_powers = []
                self.state.system_powerplay_conflict_progress = {}
                self.state.system_powerplay_control_progress = None
                self.state.system_powerplay_reinforcement = None
                self.state.system_powerplay_undermining = None

                # Clear per-system combat / alerts
                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_contacts.clear()
                self.state.combat_current_key = ""

                # Enter hyperspace transitional state
                self.state.system = target or self.state.system
                self.state.in_hyperspace = True
                self.state.jump_star_class = star_class
                self._apply_external_intel(self.state.system, None)

                # Force UI refresh so old system info disappears immediately
                msgs.append("refresh_powerplay")

                if target:
                    msgs.append(f"Jumping to: {target} ({star_class})")

        elif name == "NavRouteClear":
            self.state.route_target_system = None
            self.state.route_target_star_class = None
            self.state.route_remaining_jumps = None
            self.state.route_destination_system = None

        elif name == "ShipTargeted":
            # Clear current contact info when target is dropped
            if event.get("TargetLocked") is False:
                self.state.current_contact_alert = ""
                try:
                    self.state.pp_enemy_alerts.clear()
                except Exception:
                    self.state.pp_enemy_alerts = []
                self.state.combat_last_key = self.state.combat_current_key
                self.state.combat_current_key = ""
                self.state.combat_last_alerted_key = None
                return self.state, msgs

            scan_stage = event.get("ScanStage")
            if isinstance(scan_stage, int) and scan_stage < 3:
                return self.state, msgs

            # Update Combat contacts list (always, regardless of PP pledge)
            target_power = event.get("Power")
            if not isinstance(target_power, str):
                target_power = ""
            legal = event.get("LegalStatus") or ""
            legal_lower = legal.strip().lower() if isinstance(legal, str) else ""
            is_wanted = bool(legal_lower == "wanted")
            # "Hostile" is a distinct LegalStatus from "Wanted": confirmed via
            # Elite Dangerous's own Crime & Punishment rules, a Hostile ship
            # is already trying to kill you and there's no bounty/notoriety
            # consequence to killing it back — true regardless of whether
            # that's PowerPlay combat or a BGS Conflict Zone. This is the
            # authoritative "safe to engage" signal, not faction membership
            # alone (a ship merely belonging to a faction at war elsewhere in
            # the BGS isn't fair game outside an actual Conflict Zone).
            is_hostile = bool(legal_lower == "hostile")
            # "Enemy" (an opposing PowerPlay power's own combatant) is safe
            # to kill wherever encountered, not just in the player's own
            # controlled territory -- confirmed externally, see
            # _engage_risk()'s docstring.
            is_enemy_status = bool(legal_lower == "enemy")
            bounty = event.get("Bounty")

            rank_val = event.get("PilotRank")
            rank_name = ""
            if isinstance(rank_val, int):
                rank_map = {
                    0: "Harmless",
                    1: "Mostly Harmless",
                    2: "Novice",
                    3: "Competent",
                    4: "Expert",
                    5: "Master",
                    6: "Dangerous",
                    7: "Deadly",
                    8: "Elite",
                }
                rank_name = rank_map.get(rank_val, "")
            elif isinstance(rank_val, str):
                rank_name = rank_val.strip()

            pilot = event.get("PilotName_Localised") or event.get("PilotName") or ""
            ship = event.get("Ship_Localised") or event.get("Ship") or ""
            faction = event.get("Faction") or ""
            ts = event.get("timestamp") or ""

            # Build a stable-ish dedupe key.
            # IMPORTANT: do NOT include Power in the key (it may appear later and cause duplicate rows).
            pilot_key = self._norm_text(event.get("PilotName") or pilot or "UNKNOWN").lower()
            ship_key = self._norm_text(event.get("Ship") or ship or "UNKNOWN").lower()
            faction_key = self._norm_text(faction or "UNKNOWN").lower()

            key = f"{pilot_key}|{ship_key}|{faction_key}"
            try:
                self.state.combat_contacts[key] = {
                    "Pilot": pilot,
                    "Rank": rank_name,
                    "Ship": ship,
                    "Faction": faction,
                    "Power": target_power,
                    "Wanted": bool(is_wanted),
                    "Hostile": bool(is_hostile),
                    "Enemy": bool(is_enemy_status),
                    "Bounty": bounty if isinstance(bounty, int) else None,
                    "EngageRisk": _engage_risk(
                        is_wanted, is_hostile, target_power,
                        getattr(self.state, "pp_power", None),
                        getattr(self.state, "system_controlling_power", None),
                        getattr(self.state, "system_government", None),
                        enemy=is_enemy_status,
                    ),
                    "LastSeen": ts,
                }
                self.state.combat_current_key = key
            except Exception:
                pass

            # BGS war context: does this ship's faction oppose our squadron-
            # aligned faction in an active War/CivilWar right here? This is
            # informational context only — a ship merely belonging to that
            # faction isn't a sanctioned kill unless it's also Hostile (i.e.
            # actually engaged in a Conflict Zone); shooting a random Clean
            # NPC from that faction outside a CZ just earns a bounty.
            war_enemy_faction = find_squadron_war_enemy(
                self.state.factions, self.state.system_conflicts
            )
            bgs_war_faction_match = bool(faction and war_enemy_faction and faction == war_enemy_faction)

            pledged = getattr(self.state, "pp_power", None)

            # "My PP space" == systems where my power actually has a stake:
            # controls it, is one of the active contesting/undermining
            # powers there (system_powers), or the system's PP state is
            # Contested — not just systems it already controls outright.
            ctrl = getattr(self.state, "system_controlling_power", None)
            pp_state = str(getattr(self.state, "system_powerplay_state", "") or "").strip().lower()
            system_powers = getattr(self.state, "system_powers", None) or []
            in_my_pp_space = bool(pledged and (
                (isinstance(ctrl, str) and ctrl == pledged)
                or pledged in system_powers
                or pp_state == "contested"
            ))

            bounty_ok = bool(isinstance(bounty, int) and bounty >= 500_000)

            rank_ok = bool(rank_name.lower() in {"dangerous", "deadly", "elite"})
            bounty_target = bool(is_wanted and bounty_ok and rank_ok)

            pp_enemy = bool(pledged and target_power and target_power != pledged)

            # Rules:
            # 1) Hostile is authoritative and unconditional — the game has
            #    already determined this ship is fair game, anywhere.
            # 2) In my PP space: also alert PP enemies even if Clean/no
            #    bounty (Power Bounty applies there, not a criminal one).
            # 3) Anywhere: also alert very high-value bounty targets.
            if is_hostile:
                pass
            elif in_my_pp_space:
                if not (pp_enemy or bounty_target):
                    return self.state, msgs
            else:
                if not bounty_target:
                    return self.state, msgs

            who_bits = [x for x in [pilot, ship, faction] if isinstance(x, str) and x.strip()]
            who = " — ".join(who_bits) if who_bits else "Unknown target"

            if is_hostile:
                label = "Hostile contact"
            elif pp_enemy:
                label = "PP enemy"
            else:
                label = "High bounty"

            parts = []
            parts.append(f"⚔️ {label} scan: {who}")
            if rank_name:
                parts.append(f"Rank: {rank_name}")
            if target_power:
                parts.append(f"Power: {target_power}")
            if is_wanted:
                parts.append("Wanted")
            if isinstance(bounty, int) and bounty > 0:
                parts.append(f"Bounty: {bounty:,} cr")
            if bgs_war_faction_match:
                parts.append(f"At war with your squadron faction ({faction})")
            if self.state.ship_has_weapons is False:
                parts.append("⚠️ You have no weapons fitted — do not engage")

            alert = " | ".join(parts)

            try:
                last_alerted = getattr(self.state, "combat_last_alerted_key", None)

                # Only alert once per fully scanned unique target
                if key != last_alerted:
                    self.state.current_contact_alert = alert
                    self.state.pp_enemy_alerts = [alert]
                    self.state.combat_last_alerted_key = key
                    msgs.append(alert)
            except Exception:
                self.state.current_contact_alert = alert
                self.state.pp_enemy_alerts = [alert]
                self.state.combat_last_alerted_key = key
                msgs.append(alert)

        elif name == "Loadout":
            # Fires on ship swap, docking, and any module change — always
            # reflects the ship you're currently flying. Used to caveat
            # enemy-contact alerts with "you have no weapons fitted" when
            # relevant (e.g. flying an unarmed hauler/explorer).
            self.state.ship_has_weapons = has_any_weapon(event.get("Modules"))
            cargo_cap = event.get("CargoCapacity")
            if isinstance(cargo_cap, int):
                self.state.cargo_capacity = cargo_cap

        elif name == "Powerplay":
            self.state.pp_power = event.get("Power")
            self.state.pp_rank = event.get("Rank")
            self.state.pp_merits = event.get("Merits")
            if self.state.pp_merits_start is None and isinstance(
                self.state.pp_merits, int
            ):
                self.state.pp_merits_start = self.state.pp_merits
                self.state.pp_merits_session = 0
            if self.state.pp_power:
                msgs.append(
                    f"PP: {self.state.pp_power} "
                    f"(Rank {self.state.pp_rank}, "
                    f"Merits {self.state.pp_merits:,})"
                )

        elif name == "PowerplayMerits":
            gained = event.get("MeritsGained")
            total = event.get("TotalMerits")
            if isinstance(total, int):
                self.state.pp_merits = total
            if isinstance(gained, int) and gained > 0:
                self.state.pp_merits_session += gained
                msgs.append(
                    f"PP Merits: +{gained:,} this action "
                    f"| Session: +{self.state.pp_merits_session:,} "
                    f"| Total: {self.state.pp_merits:,}"
                )
                # A large gain here used to be treated as proof of a PP-enemy
                # kill (no dedicated kill event exists for one) -- dropped:
                # PP commodity-trade delivery also grants large single-gain
                # merit chunks (confirmed live: a dockside MarketSell of a PP
                # trade good produced a 3960-merit gain, miscounted as a
                # phantom kill), and merit size alone can't tell the two
                # apart. session_kills now only counts an actual kill event
                # (Bounty, FactionKillBond, CommitCrime murder) -- a PP-enemy
                # kill with no such event goes uncounted rather than guessed.

        elif name == "Cargo":
            self.state.cargo_count = event.get("Count")
            limpets = 0
            for item in event.get("Inventory", []) or []:
                if item.get("Name") == "drones":
                    limpets = int(item.get("Count", 0) or 0)
                    break
            self.state.limpets = limpets
            msgs.append(f"Cargo: {self.state.cargo_count} (Limpets {self.state.limpets})")

        elif name == "Bounty":
            victim_faction = event.get("VictimFaction")
            if isinstance(victim_faction, str) and victim_faction:
                # One kill credits every currently-stacked massacre mission
                # against that faction in this system simultaneously — real
                # game behavior, not per-mission independent progress.
                for rec in (self.state.active_missions or {}).values():
                    kill_count = rec.get("kill_count")
                    if (
                        isinstance(kill_count, int)
                        and rec.get("target_faction") == victim_faction
                        and rec.get("destination_system") == self.state.system
                        and rec.get("kills_credited", 0) < kill_count
                    ):
                        rec["kills_credited"] = rec.get("kills_credited", 0) + 1

            reward = event.get("TotalReward")
            if isinstance(reward, int):
                ts = event.get("timestamp") or ""
                cur_key = (getattr(self.state, "combat_current_key", "") or
                           getattr(self.state, "combat_last_key", "")) or ""
                reward_key = f"{ts}|{reward}|{cur_key}"
                if reward_key not in self.state.counted_combat_keys:
                    self.state.counted_combat_keys.add(reward_key)
                    self.state.combat_session_collected += reward
                    self.state.combat_unsold_total += reward
                    try:
                        self.state.session_bounties += reward
                    except Exception:
                        pass
                kill_key = f"kill|{ts}|{cur_key}"
                if kill_key not in self.state.counted_combat_keys:
                    self.state.counted_combat_keys.add(kill_key)
                    try:
                        self.state.session_kills += 1
                    except Exception:
                        pass

            try:
                cur_key = (getattr(self.state, "combat_current_key", "") or
                           getattr(self.state, "combat_last_key", "")) or ""
                contacts = getattr(self.state, "combat_contacts", None) or {}
                if cur_key and cur_key in contacts and isinstance(contacts[cur_key], dict):
                    contacts[cur_key]["Destroyed"] = True
                    self.state.combat_contacts = contacts
            except Exception:
                pass

        elif name == "FactionKillBond":
            reward = event.get("Reward")
            if isinstance(reward, int):
                ts = event.get("timestamp") or ""
                cur_key = (getattr(self.state, "combat_current_key", "") or
                           getattr(self.state, "combat_last_key", "")) or ""
                reward_key = f"{ts}|{reward}|{cur_key}"
                if reward_key not in self.state.counted_combat_keys:
                    self.state.counted_combat_keys.add(reward_key)
                    self.state.combat_session_collected += reward
                    self.state.combat_unsold_total += reward
                    try:
                        self.state.session_bounties += reward
                    except Exception:
                        pass
                kill_key = f"kill|{ts}|{cur_key}"
                if kill_key not in self.state.counted_combat_keys:
                    self.state.counted_combat_keys.add(kill_key)
                    try:
                        self.state.session_kills += 1
                    except Exception:
                        pass

            try:
                cur_key = (getattr(self.state, "combat_current_key", "") or
                           getattr(self.state, "combat_last_key", "")) or ""
                contacts = getattr(self.state, "combat_contacts", None) or {}
                if cur_key and cur_key in contacts and isinstance(contacts[cur_key], dict):
                    contacts[cur_key]["Destroyed"] = True
                    self.state.combat_contacts = contacts
            except Exception:
                pass

            self._credit_cz_kill(event)

        elif name == "ApproachSettlement":
            settlement_name = event.get("Name")
            if isinstance(settlement_name, str) and settlement_name:
                self.state.cz_pending_settlement = {
                    "timestamp": event.get("timestamp"), "name": settlement_name, "size": None,
                }
                self.state.cz_pending_space = None

        elif name == "SupercruiseExit":
            zone_type = (event.get("Type") or "").lower()
            for prefix, size in (("$warzone_pointrace_low", "l"), ("$warzone_pointrace_med", "m"), ("$warzone_pointrace_high", "h")):
                if zone_type.startswith(prefix):
                    self.state.cz_pending_space = {"timestamp": event.get("timestamp"), "type": size}
                    self.state.cz_pending_settlement = None
                    break

        elif name == "SupercruiseEntry":
            # Leaving the CZ instance (jumping to supercruise) — any further
            # kill bonds belong to whatever comes next, not this zone.
            self.state.cz_pending_settlement = None
            self.state.cz_pending_space = None

        elif name == "MarketBuy":
            cost = event.get("TotalCost")
            if isinstance(cost, int):
                self.state.session_trade_spent += cost
                if self._at_squadron_faction_station():
                    self.state.squadron_bgs_trade_cr += cost

        elif name == "MarketSell":
            # Profit uses the game's own AvgPricePaid cost basis per sale
            # (not a running buy/sell subtraction) — correctly nets out to
            # full profit for cargo that was never bought (mined, looted,
            # mission reward), where AvgPricePaid is 0.
            sale = event.get("TotalSale")
            count = event.get("Count")
            avg_paid = event.get("AvgPricePaid")
            if isinstance(sale, int):
                self.state.session_trade_revenue += sale
                cost_basis = avg_paid * count if isinstance(avg_paid, (int, float)) and isinstance(count, int) else 0
                self.state.session_trade_profit += sale - cost_basis
                if self._at_squadron_faction_station():
                    # BGS credits transaction volume at the controlling
                    # station, not personal profit margin — both buy and
                    # sell value count toward that faction's economy.
                    self.state.squadron_bgs_trade_cr += sale

        elif name == "Rank":
            self.state.ranks = {
                k: v for k, v in event.items() if k not in ("timestamp", "event") and isinstance(v, int)
            }

        elif name == "Progress":
            self.state.rank_progress = {
                k: v for k, v in event.items() if k not in ("timestamp", "event") and isinstance(v, int)
            }

        elif name == "CommitCrime":
            bounty = event.get("Bounty")
            faction = event.get("Faction")
            if isinstance(bounty, int) and isinstance(faction, str) and faction:
                try:
                    active = dict(getattr(self.state, "active_bounties", None) or {})
                    active[faction] = active.get(faction, 0) + bounty
                    self.state.active_bounties = active
                except Exception:
                    pass

            if event.get("CrimeType") == "murder":
                ts = event.get("timestamp") or ""
                cur_key = (getattr(self.state, "combat_current_key", "") or
                           getattr(self.state, "combat_last_key", "")) or ""
                kill_key = f"kill|{ts}|{cur_key}"
                if kill_key not in self.state.counted_combat_keys:
                    self.state.counted_combat_keys.add(kill_key)
                    try:
                        self.state.session_kills += 1
                    except Exception:
                        pass
                try:
                    cur_key = (getattr(self.state, "combat_current_key", "") or
                               getattr(self.state, "combat_last_key", "")) or ""
                    contacts = getattr(self.state, "combat_contacts", None) or {}
                    if cur_key and cur_key in contacts and isinstance(contacts[cur_key], dict):
                        contacts[cur_key]["Destroyed"] = True
                        self.state.combat_contacts = contacts
                except Exception:
                    pass

        elif name in SQUADRON_EVENT_NAMES:
            current = {
                "name": self.state.squadron_name,
                "rank": self.state.squadron_rank,
                "rank_history": list(self.state.squadron_rank_history or []),
                "trophies": self.state.squadron_trophies,
                "status": self.state.squadron_status,
                "status_timestamp": self.state.squadron_status_timestamp,
            }
            apply_squadron_event(current, event)
            self.state.squadron_name = current["name"]
            self.state.squadron_rank = current["rank"]
            self.state.squadron_rank_history = current["rank_history"]
            self.state.squadron_trophies = current["trophies"]
            self.state.squadron_status = current["status"]
            self.state.squadron_status_timestamp = current["status_timestamp"]

        elif name in MISSION_EVENT_NAMES:
            apply_mission_event(self.state.active_missions, event)

        elif name == "Statistics":
            crime = event.get("Crime")
            if isinstance(crime, dict) and isinstance(crime.get("Notoriety"), int):
                self.state.notoriety = crime["Notoriety"]
                self.state.notoriety_timestamp = event.get("timestamp")

        elif name == "PayBounties":
            try:
                active = dict(getattr(self.state, "active_bounties", None) or {})
                faction = event.get("Faction")
                if isinstance(faction, str) and faction:
                    active.pop(faction, None)
                else:
                    active.clear()
                self.state.active_bounties = active
            except Exception:
                pass

        elif name == "RedeemVoucher":
            if event.get("Type") in ("bounty", "CombatBond"):
                amount = event.get("Amount")
                if isinstance(amount, int) and self._at_squadron_faction_station():
                    self.state.squadron_bgs_bounty_cr += amount
                try:
                    self.state.session_bounties = 0
                    self.state.session_kills = 0
                    self.state.combat_session_collected = 0
                    self.state.combat_unsold_total = 0
                    self.state.counted_combat_keys.clear()
                except Exception:
                    pass

        elif name == "Scan":
            body = self._norm_text(event.get("BodyName"))
            if body:
                # Rings can belong to stars as well as planets, so this must
                # run before the planet_class early-return below (stars have
                # no PlanetClass and would otherwise never reach this code).
                distance_ls = event.get("DistanceFromArrivalLS")

                ring_match = _RING_NAME_RE.match(body)
                if ring_match:
                    # The ring's own Scan event (AutoScan/Detailed) — always
                    # present, unlike the parent's Rings array.
                    rec = self.state.rings.get(body, {})
                    rec.setdefault("scanned", False)
                    rec.setdefault("hotspots", [])
                    rec.setdefault("ring_class", "")
                    rec.update({
                        "system_address": self.state.system_address,
                        "parent_body": ring_match.group(1),
                        "distance_ls": distance_ls,
                    })
                    self.state.rings[body] = rec

                for ring in (event.get("Rings") or []):
                    if not isinstance(ring, dict):
                        continue
                    ring_name = self._norm_text(ring.get("Name"))
                    if not ring_name:
                        continue
                    # The journal's "Rings" array also lists asteroid Belts
                    # (e.g. "...A Belt") alongside real planetary/stellar
                    # rings (e.g. "...A Ring") -- Belts have no hotspots and
                    # can't be SAA-probed, so they don't belong in the
                    # Exploration tab's "Rings in this system" list.
                    if not _RING_NAME_RE.match(ring_name):
                        continue
                    rec = self.state.rings.get(ring_name, {})
                    rec.setdefault("scanned", False)
                    rec.setdefault("hotspots", [])
                    rec.update({
                        "system_address": self.state.system_address,
                        "parent_body": body,
                        "ring_class": ring.get("RingClass") or rec.get("ring_class") or "",
                        "distance_ls": rec.get("distance_ls", distance_ls),
                    })
                    self.state.rings[ring_name] = rec

                body_id = event.get("BodyID")
                if isinstance(body_id, int) and not ring_match and "Belt Cluster" not in body:
                    # Stars scan with no PlanetClass and used to hit the
                    # early-return below before ever reaching this, so a
                    # system's own star(s) never counted as "resolved" —
                    # confirmed live: 25/26 resolved, 1 unknown, on a
                    # fully-discovered single-star system. Rings and belt
                    # clusters get their own BodyID too but aren't counted
                    # in system_body_count (FSSDiscoveryScan.BodyCount), so
                    # both are excluded here the same way.
                    self.state.resolved_body_ids.add(body_id)

                planet_class = event.get("PlanetClass") or ""
                if not planet_class:
                    return self.state, msgs
                if isinstance(body_id, int):
                    self.state.body_id_to_name[body_id] = body
                terraform_state = event.get("TerraformState") or ""
                terraformable = bool(terraform_state) and terraform_state.lower() != "not terraformable"
                distance_ls = event.get("DistanceFromArrivalLS")
                landable_raw = event.get("Landable")
                landable = landable_raw if isinstance(landable_raw, bool) else None
                volcanism = event.get("Volcanism_Localised") or event.get("Volcanism") or ""
                if not isinstance(volcanism, str):
                    volcanism = ""
                materials = event.get("Materials")
                if not isinstance(materials, dict):
                    materials = {}
                # Journal provides these flags in Scan
                was_discovered = bool(event.get("WasDiscovered", False))
                was_mapped     = bool(event.get("WasMapped", False))
                was_footfalled = bool(event.get("WasFootfalled", False))
                # WasDiscovered can be unreliable (server lag / sync issues).
                # WasFootfalled and WasMapped are definitive proof of prior discovery —
                # use them to veto a false first-discovery flag.
                first_discovered = not was_discovered and not was_footfalled and not was_mapped

                est = None
                if self.planet_values and planet_class:
                    est = self.planet_values.estimate(
                        planet_class=planet_class,
                        terraformable=terraformable,
                        mapped=was_mapped,
                        first_discovered=first_discovered,
                    )

                rec = self.state.bodies.get(body, {})
                rec.update(
                    {
                        "BodyName": body,
                        "BodyID": body_id if isinstance(body_id, int) else None,
                        "PlanetClass": planet_class,
                        "Terraformable": terraformable,
                        "DistanceLS": distance_ls,
                        "Landable": landable,
                        "Volcanism": volcanism,
                        "Materials": materials,
                        "FirstDiscovered": first_discovered,
                        "WasMapped": was_mapped,
                        "DSSMapped": bool(rec.get("DSSMapped", False)),
                        "EstimatedValue": est,
                        "MassEM":            event.get("MassEM"),
                        "Radius":            event.get("Radius"),
                        "SurfaceGravity":    event.get("SurfaceGravity"),
                        "SurfaceTemperature": event.get("SurfaceTemperature"),
                        "SurfacePressure":   event.get("SurfacePressure"),
                        "AtmosphereType":    event.get("AtmosphereType_Localised") or event.get("AtmosphereType") or "",
                        "Atmosphere":        event.get("Atmosphere_Localised") or event.get("Atmosphere") or "",
                        "AxialTilt":              event.get("AxialTilt"),
                        "OrbitalPeriod":          event.get("OrbitalPeriod"),
                        "RotationPeriod":         event.get("RotationPeriod"),
                        "TidalLock":              bool(event.get("TidalLock", False)),
                        "WasFootfalled":          bool(event.get("WasFootfalled", False)),
                        "AtmosphereComposition":  event.get("AtmosphereComposition") or [],
                        "Composition":            event.get("Composition") or {},
                    }
                )
                if body in self.state.bio_signals:
                    rec["BioSignals"] = self.state.bio_signals.get(body, 0)
                if body in self.state.bio_genuses:
                    rec["BioGenuses"] = self.state.bio_genuses.get(body, [])
                if body in self.state.geo_signals:
                    rec["GeoSignals"] = self.state.geo_signals.get(body, 0)
                self.state.bodies[body] = rec

                if isinstance(est, int) and est > 0:
                    body_key = f"{self.state.system_address}|{body}"
                    if body_key not in self.state.counted_exploration_keys:
                        self.state.counted_exploration_keys.add(body_key)
                        self.state.exploration_session_collected_est += est
                        self.state.exploration_unsold_total_est += est

        elif name in ("MultiSellExplorationData", "SellExplorationData"):
            self.state.exploration_unsold_total_est = 0

        elif name == "SAAScanComplete":
            body = self._norm_text(event.get("BodyName"))

            ring_match = _RING_NAME_RE.match(body) if body else None
            if ring_match:
                # Confirmed via real journal data: SAASignalsFound only
                # fires when there's at least one signal to report — a ring
                # that's genuinely, fully probed but has zero hotspots gets
                # ONLY this event, never SAASignalsFound. Without handling
                # it here too, such a ring would show as "missing hotspot
                # data" forever despite having already been correctly
                # scanned to completion.
                rec = self.state.rings.get(body, {})
                rec.setdefault("system_address", self.state.system_address)
                rec.setdefault("parent_body", ring_match.group(1))
                rec.setdefault("ring_class", "")
                rec.setdefault("distance_ls", None)
                rec.setdefault("hotspots", [])
                rec["scanned"] = True
                self.state.rings[body] = rec

            if body and body in self.state.bodies:
                rec = self.state.bodies[body]
                rec["DSSMapped"] = True
                rec["FirstMapped"] = not bool(event.get("WasMapped", True))
                planet_class = rec.get("PlanetClass", "")
                terraformable = bool(rec.get("Terraformable", False))
                first_discovered = bool(rec.get("FirstDiscovered", False))
                if self.planet_values and planet_class:
                    rec["EstimatedValue"] = self.planet_values.estimate(
                        planet_class=planet_class,
                        terraformable=terraformable,
                        mapped=True,
                        first_discovered=first_discovered,
                    )
                self.state.bodies[body] = rec

        elif name == "Disembark":
            if bool(event.get("OnPlanet", False)):
                body = self._norm_text(event.get("Body") or event.get("BodyName"))
                if body:
                    rec = self.state.bodies.get(body) or {}
                    # "FirstFootfall" isn't a real Disembark field (confirmed
                    # against the official journal schema and a live game
                    # session) -- WasFootfalled from the body's last scan is
                    # the real signal: if nobody had footfalled there as of
                    # that scan, this disembark is (almost certainly) the
                    # first one. Defaults to True (first) when the body was
                    # never scanned at all, same as this codebase's other
                    # "no evidence of prior status" defaults.
                    first_footfall = not bool(rec.get("WasFootfalled", False))
                    rec["HasFootfall"]   = True
                    rec["FirstFootfall"] = first_footfall
                    self.state.bodies[body] = rec

        elif name == "FSSDiscoveryScan":
            # "Honk" result: tells us how many bodies exist, not what they are
            bc = event.get("BodyCount")
            if isinstance(bc, int):
                self.state.system_body_count = bc

            nb = event.get("NonBodyCount")
            prog = event.get("Progress")

            # If FSS scan is complete, mark system as resolved
            if isinstance(prog, (int, float)) and prog >= 1.0:
                self.state.fss_complete = True
            else:
                self.state.fss_complete = False
    
            # When FSS scan is complete, there are no unresolved signals
            if isinstance(prog, (int, float)) and prog >= 1.0:
                self.state.non_body_count = 0
            elif isinstance(nb, int):
                self.state.non_body_count = nb

        elif name == "FSSAllBodiesFound":
            count = event.get("Count")

            if isinstance(count, int):
                self.state.system_body_count = count

            # System fully resolved
            self.state.fss_complete = True
            self.state.non_body_count = 0

        elif name == "FSSSignalDiscovered":
            # Discovered via FSS zoom; includes USS/Stations/Phenomena etc.
            sig_name = event.get("SignalName_Localised") or event.get("SignalName") or ""
            sig_type = event.get("SignalType") or event.get("SignalType_Localised") or ""
            uss_raw = event.get("USSType") or ""
            uss = event.get("USSType_Localised") or uss_raw or ""
            threat = event.get("ThreatLevel")
            is_station = event.get("IsStation")
            time_rem = event.get("TimeRemaining")
            ts = event.get("timestamp") or ""

            key = f"{sig_name}|{sig_type}|{uss}|{threat}|{is_station}"
            category = self._classify_system_signal(sig_name, uss_raw, is_station, sig_type)

            entry = {
                "Key": key,
                "SignalName": sig_name,
                "SignalType": sig_type,
                "USSType": uss,
                "Category": category,
                "ThreatLevel": threat if isinstance(threat, int) else None,
                "IsStation": bool(is_station) if isinstance(is_station, bool) else None,
                "TimeRemaining": time_rem if isinstance(time_rem, (int, float)) else None,
                "LastSeen": ts if isinstance(ts, str) else "",
            }

            sigs = getattr(self.state, "system_signals", None)
            if not isinstance(sigs, list):
                sigs = []
            idx = None
            for i, s in enumerate(sigs):
                if isinstance(s, dict) and s.get("Key") == key:
                    idx = i
                    break
            if idx is None:
                sigs.append(entry)
            else:
                try:
                    sigs[idx].update(entry)
                except Exception:
                    sigs[idx] = entry

            # Keep bounded per-system (prevents long-session growth/noise)
            max_sigs = 200
            if len(sigs) > max_sigs:
                sigs = sigs[-max_sigs:]
            self.state.system_signals = sigs

        elif name == "FSSBodySignals":
            # Early hint: body has Biological and Geological signals (counts)
            body = self._norm_text(event.get("BodyName"))
            if not body:
                return self.state, msgs

            body_id = event.get("BodyID")
            if isinstance(body_id, int):
                self.state.body_id_to_name[body_id] = body

            bio      = 0
            geo      = 0
            human    = 0
            guardian = 0
            thargoid = 0
            other    = 0
            for sig in (event.get("Signals") or []):
                t  = (sig.get("Type") or "")
                tl = (sig.get("Type_Localised") or "")
                tl_low = tl.strip().lower()
                t_low  = t.lower()
                if ("biological" in t_low) or (tl_low == "biological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        bio = c
                elif ("geological" in t_low) or (tl_low == "geological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        geo = c
                elif ("human" in t_low) or (tl_low == "human"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        human = c
                elif ("guardian" in t_low) or (tl_low == "guardian"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        guardian = c
                elif ("thargoid" in t_low) or (tl_low == "thargoid"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        thargoid = c
                elif ("other" in t_low) or (tl_low == "other"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        other = c
            self.state.bio_signals[body]      = bio
            self.state.geo_signals[body]      = geo
            self.state.human_signals[body]    = human
            self.state.guardian_signals[body] = guardian
            self.state.thargoid_signals[body] = thargoid
            self.state.other_signals[body]    = other

            # Create or update a placeholder record so the UI can show Bio immediately
            rec = self.state.bodies.get(body)
            if not isinstance(rec, dict):
                rec = {
                    "BodyName": body,
                    "BodyID": body_id if isinstance(body_id, int) else None,
                    "PlanetClass": "",
                    "DistanceLS": None,
                    "EstimatedValue": None,
                    "Terraformable": False,
                    "FirstDiscovered": False,
                    "WasMapped": False,
                    "DSSMapped": False,
                }
            if isinstance(body_id, int):
                rec["BodyID"] = body_id
            rec["BioSignals"] = bio
            rec["GeoSignals"] = geo
            rec["HumanSignals"] = human
            rec["GuardianSignals"] = guardian
            rec["ThargoidSignals"] = thargoid
            rec["OtherSignals"]    = other
            # IMPORTANT: preserve DSS-confirmed genera if we already have them.
            # FSSBodySignals can arrive after SAASignalsFound and would otherwise overwrite the body record.
            rec["BioGenuses"] = self.state.bio_genuses.get(body, rec.get("BioGenuses", []))
            self.state.bodies[body] = rec

        elif name == "Status":
            # Live telemetry from Status.json (lat/lon/radius) - used for CCR distance tracking.
            self.state.surface_timestamp = event.get("timestamp")
            self.state.surface_body_name = self._norm_text(event.get("BodyName")) or event.get("BodyName")

            try:
                if event.get("Latitude") is not None:
                    self.state.surface_lat = float(event.get("Latitude"))
            except Exception:
                pass
            try:
                if event.get("Longitude") is not None:
                    self.state.surface_lon = float(event.get("Longitude"))
            except Exception:
                pass
            try:
                if event.get("PlanetRadius") is not None:
                    self.state.surface_radius_m = float(event.get("PlanetRadius"))
            except Exception:
                pass

            # CCR baseline-after-Status:
            # If ScanOrganic(Log) occurred before we had Status lat/lon, we defer baseline until the
            # first Status event that has valid surface coordinates.
            try:
                lat = self.state.surface_lat
                lon = self.state.surface_lon
                R = self.state.surface_radius_m
                body_nm = self._norm_text(self.state.surface_body_name or "")

                if (
                    isinstance(lat, float)
                    and isinstance(lon, float)
                    and isinstance(R, float)
                    and R > 0
                    and body_nm
                    and isinstance(self.state.exo, dict)
                ):
                    for _k, rec in self.state.exo.items():
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("Complete"):
                            continue
                        if not rec.get("CCRPendingBaseline"):
                            continue

                        # Only apply to records that match current body (best-effort).
                        rec_body_id = rec.get("BodyID")
                        rec_body_name = ""
                        if isinstance(rec_body_id, int):
                            rec_body_name = self._norm_text(self.state.body_id_to_name.get(rec_body_id, "") or "")
                        if rec_body_name and rec_body_name != body_nm:
                            continue

                        # Initialize baseline point now.
                        pts = rec.get("SamplePoints")
                        if not isinstance(pts, list):
                            pts = []
                        if len(pts) == 0:
                            pts.append({"t": self.state.surface_timestamp, "lat": lat, "lon": lon})
                            rec["SamplePoints"] = pts

                            req = rec.get("CCRRequiredM")
                            if isinstance(req, int) and req > 0:
                                rec["CCRDistanceM"] = 0
                                rec["CCRRemainingM"] = req

                        rec["CCRPendingBaseline"] = False
            except Exception:
                pass

            # Update CCR remaining for any active exo targets on this body (best-effort).
            try:
                lat = self.state.surface_lat
                lon = self.state.surface_lon
                R = self.state.surface_radius_m
                body_nm = self._norm_text(self.state.surface_body_name or "")
                if (
                    isinstance(lat, float)
                    and isinstance(lon, float)
                    and isinstance(R, float)
                    and R > 0
                    and body_nm
                    and isinstance(self.state.exo, dict)
                ):
                    for _k, rec in self.state.exo.items():
                        if not isinstance(rec, dict):
                            continue
                        if rec.get("Complete"):
                            continue
                        req = rec.get("CCRRequiredM")
                        pts = rec.get("SamplePoints") or []
                        if not isinstance(req, int) or req <= 0:
                            continue
                        if not isinstance(pts, list) or not pts:
                            continue

                        # Only update if body seems to match current status body.
                        rec_body_id = rec.get("BodyID")
                        rec_body_name = ""
                        if isinstance(rec_body_id, int):
                            rec_body_name = self._norm_text(self.state.body_id_to_name.get(rec_body_id, "") or "")
                        if rec_body_name and rec_body_name != body_nm:
                            continue

                        # CCR is measured from the most recent sample point only.
                        # (The game requires each scan to be CCR metres from the previous, not all prior scans.)
                        last_pt = pts[-1]
                        if not (isinstance(last_pt, dict) and "lat" in last_pt and "lon" in last_pt):
                            continue
                        try:
                            d = self._surface_distance_m(
                                lat, lon,
                                float(last_pt["lat"]), float(last_pt["lon"]),
                                R,
                            )
                        except Exception:
                            continue
                        rec["CCRDistanceM"] = int(round(d))
                        rec["CCRRemainingM"] = int(max(0, req - rec["CCRDistanceM"]))
                        genus = str(rec.get("Genus") or "").strip()
                        if rec["CCRRemainingM"] == 0:
                            if not rec.get("CCRAnnounced", False):
                                msgs.append(f"CCR distance reached for {genus}")
                                rec["CCRAnnounced"] = True
                                rec["CCRTooClose"] = False
                        elif rec.get("CCRAnnounced", False) and not rec.get("CCRTooClose", False):
                            msgs.append(f"CCR too close for {genus}")
                            rec["CCRAnnounced"] = False
                            rec["CCRTooClose"] = True
            except Exception:
                pass

        elif name == "SAASignalsFound":
            # DSS-confirmed: includes Biological count and (most importantly) confirmed Genuses list
            body = self._norm_text(event.get("BodyName"))
            if not body:
                return self.state, msgs

            ring_match = _RING_NAME_RE.match(body)
            if ring_match:
                # Confirmed via live journal data: SAASignalsFound for a ring
                # can arrive BEFORE that ring's own Scan event — so the rec
                # must be created here if missing, not just looked up.
                rec = self.state.rings.get(body, {})
                rec.setdefault("system_address", self.state.system_address)
                rec.setdefault("parent_body", ring_match.group(1))
                rec.setdefault("ring_class", "")
                rec.setdefault("distance_ls", None)
                rec["scanned"] = True
                rec["hotspots"] = parse_ring_hotspots(event.get("Signals"))
                self.state.rings[body] = rec
                # Not a planetary body — skip the bio/geo/human bucket parsing
                # and state.bodies record creation below (journal_importer.py's
                # equivalent already does this; confirmed live this was
                # missing here, inflating the Exploration tab's "detailed"
                # body count with ring names, e.g. 14 vs a real total of 10).
                return self.state, msgs

            body_id = event.get("BodyID")
            if isinstance(body_id, int):
                self.state.body_id_to_name[body_id] = body

            bio      = 0
            geo      = 0
            human    = 0
            thargoid = 0
            other    = 0

            for sig in (event.get("Signals") or []):
                t  = (sig.get("Type") or "")
                tl = (sig.get("Type_Localised") or "")
                if ("biological" in t.lower()) or (tl.strip().lower() == "biological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        bio = c
                if ("geological" in t.lower()) or (tl.strip().lower() == "geological"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        geo = c
                if ("human" in t.lower()) or (tl.strip().lower() == "human"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        human = c
                if ("thargoid" in t.lower()) or (tl.strip().lower() == "thargoid"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        thargoid = c
                if ("other" in t.lower()) or (tl.strip().lower() == "other"):
                    c = sig.get("Count", 0)
                    if isinstance(c, int):
                        other = c
            if bio:
                self.state.bio_signals[body] = bio
            if geo:
                self.state.geo_signals[body] = geo
            if human:
                self.state.human_signals[body] = human
            if thargoid:
                self.state.thargoid_signals[body] = thargoid
            if other:
                self.state.other_signals[body] = other

            genuses: List[str] = []
            for g in (event.get("Genuses") or []):
                if not isinstance(g, dict):
                    continue
                gn = g.get("Genus_Localised") or g.get("Genus")
                gn = self._norm_text(gn)
                if gn:
                    genuses.append(gn)

            if genuses:
                # De-dup while keeping order
                seen = set()
                cleaned = []
                for x in genuses:
                    if x not in seen:
                        cleaned.append(x)
                        seen.add(x)
                self.state.bio_genuses[body] = cleaned

            # Create or update record so UI can show DSS-confirmed genera immediately
            rec = self.state.bodies.get(body)
            if not isinstance(rec, dict):
                rec = {
                    "BodyName": body,
                    "BodyID": body_id if isinstance(body_id, int) else None,
                    "PlanetClass": "",
                    "DistanceLS": None,
                    "EstimatedValue": None,
                    "Terraformable": False,
                    "FirstDiscovered": False,
                    "WasMapped": False,
                    "DSSMapped": False,
                }
            if isinstance(body_id, int):
                rec["BodyID"] = body_id

            rec["BioSignals"] = self.state.bio_signals.get(body, rec.get("BioSignals", 0))
            rec["BioGenuses"] = self.state.bio_genuses.get(body, rec.get("BioGenuses", []))
            rec["GeoSignals"] = self.state.geo_signals.get(body, rec.get("GeoSignals", 0))
            rec["HumanSignals"] = self.state.human_signals.get(body, rec.get("HumanSignals", 0))
            rec["ThargoidSignals"] = self.state.thargoid_signals.get(body, rec.get("ThargoidSignals", 0))
            rec["OtherSignals"] = self.state.other_signals.get(body, rec.get("OtherSignals", 0))
            rec["DSSMapped"] = True
            self.state.bodies[body] = rec

        elif name == "CommunityGoal":
            # Journal Community Goal event
            goals = event.get("CurrentGoals", [])

            if not isinstance(self.state.community_goals, dict):
                self.state.community_goals = {}

            for goal in goals:

                cgid = goal.get("CGID")
                if not isinstance(cgid, int):
                    continue

                self.state.community_goals[cgid] = {
                    "CGID": cgid,
                    "Title": goal.get("Title"),
                    "SystemName": goal.get("SystemName"),
                    "MarketName": goal.get("MarketName"),
                    "Expiry": goal.get("Expiry"),
                    "IsComplete": goal.get("IsComplete"),
                    "TierReached": goal.get("TierReached"),
                    "TopTierName": (goal.get("TopTier") or {}).get("Name"),
                    "PlayerContribution": goal.get("PlayerContribution"),
                    "NumContributors": goal.get("NumContributors"),
                    "PlayerPercentileBand": goal.get("PlayerPercentileBand"),
                }

                # track CG the player is participating in
                if goal.get("PlayerContribution"):
                    self.state.last_cg_joined = cgid

            msgs.append("Community Goal updated")

        elif name == "ScanOrganic":
            # Journal Manual: ScanType Log/Sample/Analyse + Genus + Species + Body (ID)
            scan_type = (event.get("ScanType") or "").strip()
            st = scan_type.lower()
            genus = self._norm_text(event.get("Genus_Localised") or event.get("Genus")) or "Unknown Genus"
            species = self._norm_text(event.get("Species_Localised") or event.get("Species")) or "Unknown Species"
            variant = self._norm_text(event.get("Variant_Localised") or event.get("Variant") or "")
            body_id = event.get("Body")
            if not isinstance(body_id, int):
                return self.state, msgs

            # If we previously created any Codex-only placeholders for this body+genus, remove them now.
            # Support both legacy keys (Body|Genus|CODEX|...) and the compact key (Body|Genus|CODEX).
            prefix = f"{body_id}|"
            for k in list(self.state.exo.keys()):
                try:
                    if not (isinstance(k, str) and k.startswith(prefix)):
                        continue
                    parts = k.split("|")
                    if len(parts) >= 3 and parts[0] == str(body_id) and parts[2] == "CODEX":
                        gk = self._norm_text(parts[1])
                        if gk == genus:
                            del self.state.exo[k]
                except Exception:
                    pass

            # Keying by (BodyID, Genus, Species) avoids duplicate rows when Variant is missing/inconsistent.
            key = f"{body_id}|{genus}|{species}|{variant}"
            rec = self.state.exo.get(key, {})
            if not isinstance(rec, dict):
                rec = {}
            progress = int(rec.get("Samples", 0) or 0)

            # Elite does not let you partially scan one genus/species,
            # switch to another, and then continue the old one from 1/3 or 2/3.
            # When a new ScanOrganic target becomes active, reset any other
            # incomplete live-progress rows back to 0/3 and UNSCANNED.
            if st in {"log", "sample", "analyse"}:
                for other_key, other_rec in self.state.exo.items():
                    if other_key == key:
                        continue
                    if not isinstance(other_rec, dict):
                        continue
                    if other_rec.get("Complete"):
                        continue

                    other_last = str(other_rec.get("LastScanType") or "").upper()
                    if other_last in {"LOG", "SAMPLE", "ANALYSE"}:
                        other_rec["Samples"] = 0
                        other_rec["Complete"] = False
                        other_rec["LastScanType"] = "UNSCANNED"
                        other_rec.pop("CCRDistanceM", None)
                        other_rec.pop("CCRRemainingM", None)
                        other_rec["CCRPendingBaseline"] = False
                        other_rec["SamplePoints"] = []

            # Migrate any legacy per-variant keys into the new per-species key.
            legacy_prefix = f"{key}|"
            for k in list(self.state.exo.keys()):
                try:
                    if not (isinstance(k, str) and k.startswith(legacy_prefix)):
                        continue
                    old = self.state.exo.get(k)
                    if isinstance(old, dict):
                        try:
                            rec["Samples"] = max(int(rec.get("Samples", 0) or 0), int(old.get("Samples", 0) or 0))
                        except Exception:
                            pass
                        rec["Complete"] = bool(rec.get("Complete") or old.get("Complete"))
                        for fld in ("Variant", "BaseValue", "PotentialValue", "LastScanType"):
                            if rec.get(fld) in (None, "", 0) and old.get(fld) not in (None, "", 0):
                                rec[fld] = old.get(fld)
                    self.state.exo.pop(k, None)
                except Exception:
                    pass

            rec.update(
                {
                    "BodyID": body_id,
                    "Genus": genus,
                    "Species": species,
                    "Variant": variant if variant else (rec.get("Variant") or ""),
                    "LastScanType": scan_type,
                }
            )
            if self.exo_values:
                val = self.exo_values.get_value(variant) or self.exo_values.get_value(species)
                if val is not None:
                    rec["BaseValue"] = val

            # CCR (minimum distance between samples) comes from exo_values.json per species. :contentReference[oaicite:1]{index=1}
            # We store sample positions from Status.json at the time of sampling.
            try:
                if "CCRRequiredM" not in rec or not isinstance(rec.get("CCRRequiredM"), int):
                    if self.exo_values and hasattr(self.exo_values, "by_species"):
                        exo_rec = self.exo_values.by_species.get(species)
                        if exo_rec is None and isinstance(species, str) and " - " in species:
                            exo_rec = self.exo_values.by_species.get(species.split(" - ", 1)[0].strip())
                        ccr = getattr(exo_rec, "ccr_m", None) if exo_rec is not None else None
                        if isinstance(ccr, int) and ccr > 0:
                            rec["CCRRequiredM"] = ccr
                if "SamplePoints" not in rec or not isinstance(rec.get("SamplePoints"), list):
                    rec["SamplePoints"] = []
            except Exception:
                pass

            # Your real process is:
            # - Log = 1/3
            # - Sample + Sample = 2/3 and 3/3
            # - Analyse confirms completion
            if st == "log":
                progress = max(progress, 1)

                # CCR baseline must be initialised AFTER Status provides lat/lon
                rec["CCRPendingBaseline"] = True

                # Full CCR state reset for this walk
                rec.pop("CCRDistanceM", None)
                rec.pop("CCRRemainingM", None)
                rec["CCRAnnounced"] = False
                rec["CCRTooClose"]  = False

            elif st == "sample":
                # Each Sample advances progress by 1 (0→1→2→3). If "Log" was missed, first sample becomes 1/3.
                progress = min(3, max(progress, 0) + 1)

                # After Sample 1 (progress==2), reset full CCR state so the walk to
                # Sample 2 starts fresh. Force CCRRemainingM back to the required distance
                # so Status re-tracks from Sample 1's position, not from a stale 0.
                # After Sample 2 (progress==3) Analyse fires immediately — no reset needed.
                if progress == 2:
                    rec["CCRAnnounced"] = False
                    rec["CCRTooClose"]  = False
                    req_m = rec.get("CCRRequiredM")
                    if isinstance(req_m, int) and req_m > 0:
                        rec["CCRDistanceM"] = 0
                        rec["CCRRemainingM"] = req_m

                # Record sampling position (best-effort) for CCR.
                try:
                    lat = self.state.surface_lat
                    lon = self.state.surface_lon
                    R = self.state.surface_radius_m
                    pts = rec.get("SamplePoints")
                    if not isinstance(pts, list):
                        pts = []

                    if isinstance(lat, float) and isinstance(lon, float) and isinstance(R, float) and R > 0:
                        pts.append({"t": self.state.surface_timestamp, "lat": lat, "lon": lon})
                        if len(pts) > 3:
                            pts = pts[-3:]
                        rec["SamplePoints"] = pts

                    # If we still haven't got a baseline from Status, consider first sample as baseline (fallback).
                    if rec.get("CCRPendingBaseline") and len(pts) >= 1:
                        rec["CCRPendingBaseline"] = False
                        req = rec.get("CCRRequiredM")
                        if isinstance(req, int) and req > 0:
                            rec["CCRDistanceM"] = 0
                            rec["CCRRemainingM"] = req

                    # After adding, compute min distance from newest point to all previous points.
                    req = rec.get("CCRRequiredM")
                    if isinstance(req, int) and req > 0 and isinstance(pts, list) and len(pts) >= 2:
                        newest = pts[-1]
                        dmin = None
                        for p in pts[:-1]:
                            try:
                                d = self._surface_distance_m(
                                    float(newest["lat"]),
                                    float(newest["lon"]),
                                    float(p["lat"]),
                                    float(p["lon"]),
                                    R,
                                )
                            except Exception:
                                continue
                            if dmin is None or d < dmin:
                                dmin = d
                        if dmin is not None:
                            rec["CCRDistanceM"] = int(round(dmin))
                            rec["CCRRemainingM"] = int(max(0, req - rec["CCRDistanceM"]))

                except Exception:
                    pass
            elif st == "analyse":
                # Analyse confirms completion (treat as 3/3 to keep UI consistent).
                progress = max(progress, 3)

            rec["Samples"] = progress
            rec["Complete"] = (progress >= 3)

            exo_key = f"{body_id}|{genus}|{species}|{variant}"
            if rec["Complete"] and exo_key not in self.state.counted_exobiology_keys:
                self.state.counted_exobiology_keys.add(exo_key)
                est_val = rec.get("BaseValue")
                if not isinstance(est_val, int):
                    est_val = rec.get("PotentialValue")
                if isinstance(est_val, int) and est_val > 0:
                    self.state.exobiology_session_collected_est += est_val
                    self.state.exobiology_unsold_total_est += est_val

            # ---- 3/3 completion (announce once) ----
            try:
                if rec["Complete"] and not rec.get("CompletionAnnounced", False):
                    msgs.append(f"Exobiology complete: {genus}")
                    rec["CompletionAnnounced"] = True
            except Exception:
                pass

            if rec["Complete"]:
                rec["CCRDistanceM"] = None
                rec["CCRRemainingM"] = None

            self.state.exo[key] = rec

        elif name == "SellOrganicData":
            self.state.exobiology_unsold_total_est = 0

        elif name == "CodexEntry":
            # CodexEntry is NOT sampling progress, but it's a useful early hint.
            # We create a placeholder entry so the UI can show genus you discovered.
            body_id = event.get("BodyID")
            name_loc = event.get("Name_Localised") or ""
            entry_id = event.get("EntryID")
            v = event.get("VoucherAmount")
            if isinstance(v, int) and v > 0:
                self.state.session_codex_collected += v
            if not isinstance(body_id, int) or not isinstance(name_loc, str) or not name_loc.strip():
                return self.state, msgs

            # Genus is the first word in the localized name (e.g., "Stratum Tectonicas - Lime")
            genus = self._norm_text(name_loc.strip().split(" ", 1)[0].strip())
            if not genus:
                return self.state, msgs

            # If we already have a real ScanOrganic record for this body+genus, do NOT create a CODEX placeholder.
            # This prevents "completed" scans from re-appearing as CODEX noise.
            try:
                for _k, _r in (self.state.exo or {}).items():
                    if not isinstance(_r, dict):
                        continue
                    if _r.get("BodyID") != body_id:
                        continue
                    g = str(_r.get("Genus", "") or "").strip()
                    last = str(_r.get("LastScanType", "") or "").strip().upper()
                    if last != "CODEX" and g == genus:
                        return self.state, msgs
            except Exception:
                pass

            # Potential value: journal doesn't provide this for CodexEntry. Best-effort derive from exo_values.json.
            pot = None
            if self.exo_values:
                try:
                    nm = name_loc.strip()
                    exo_rec = self.exo_values.by_species.get(nm) if hasattr(self.exo_values, "by_species") else None
                    if exo_rec is None and " - " in nm:
                        exo_rec = self.exo_values.by_species.get(nm.split(" - ", 1)[0].strip())
                    if exo_rec:
                        genus = exo_rec.genus or genus
                        pot = exo_rec.base_value
                    else:
                        pot = self.exo_values.get_value(nm) or (
                            self.exo_values.get_value(nm.split(" - ", 1)[0].strip()) if " - " in nm else None
                        )
                except Exception:
                    pot = None

            # Best-effort: populate Species/Variant for CODEX placeholders so the UI isn't blank.
            # Typical format: "<Species> - <Variant>" (e.g., "Stratum Tectonicas - Lime")
            species_txt = name_loc.strip()
            variant_txt = ""
            try:
                nm_full = name_loc.strip()
                if " - " in nm_full:
                    left, right = nm_full.split(" - ", 1)
                    species_txt = left.strip()
                    variant_txt = right.strip()
            except Exception:
                species_txt = name_loc.strip()
                variant_txt = ""

            # If exo_values has canonical fields, prefer those (guarded).
            try:
                if self.exo_values:
                    nm = name_loc.strip()
                    exo_rec = self.exo_values.by_species.get(nm) if hasattr(self.exo_values, "by_species") else None
                    if exo_rec:
                        species_txt = getattr(exo_rec, "species", None) or species_txt
                        variant_txt = getattr(exo_rec, "variant", None) or variant_txt
            except Exception:
                pass

            # Dedupe: CodexEntry can fire multiple times for the same body+genus. Keep exactly one placeholder.
            codex_key = f"{body_id}|{genus}|CODEX"
            try:
                legacy_prefix = f"{body_id}|{genus}|CODEX|"
                for k in list((self.state.exo or {}).keys()):
                    if isinstance(k, str) and k.startswith(legacy_prefix):
                        self.state.exo.pop(k, None)
            except Exception:
                pass

            rec = self.state.exo.get(codex_key, {})

            # Add localized fields so UI matching/labels stay consistent with SAASignalsFound.
            # Example Name_Localised: "Bacterium Cerbrus - Teal"
            variant_loc = (name_loc or "").strip()
            species_loc = variant_loc.split(" - ", 1)[0].strip() if variant_loc else ""
            genus_loc = species_loc.split(" ", 1)[0].strip() if species_loc else ""

            # NearestDestination is only populated for entries anchored to a
            # Notable Stellar Phenomena (e.g. Metallic Crystals in a
            # Lagrange cloud) -- confirmed via real journal data: planetary
            # organisms carry Latitude/Longitude and an empty
            # NearestDestination, NSP entities carry NearestDestination
            # (e.g. "Notable stellar phenomena") and no coordinates. Those
            # are single-scan Codex confirmations (Short Range Composition
            # Scanner, no 3-sample Genetic Sampler cycle) -- the CodexEntry
            # itself IS the completion, not a hint toward one.
            is_phenomena = bool((event.get("NearestDestination") or "").strip())

            # NSP names (e.g. "Purpureum Metallic Crystals") have no " - "
            # separator, so variant_txt above is empty -- fall back to the
            # full name so _save_exobiology_to_db()'s non-empty check on
            # both Species and Variant doesn't silently drop the save.
            if is_phenomena and not variant_txt:
                variant_txt = species_txt

            rec.update(
                {
                    "BodyID": body_id,
                    # Floats in a Lagrange cloud, not on the body's surface --
                    # "Body N" reads as a planet/star we scanned, which is
                    # misleading for something found in open space near it.
                    "BodyName": "Space" if is_phenomena else "",
                    "Genus": genus,
                    "Genus_Localised": genus_loc,
                    "Species": species_txt,
                    "Species_Localised": species_loc,
                    "Variant": variant_txt,
                    "Variant_Localised": variant_loc,
                    "Samples": 0,
                    "Complete": is_phenomena,
                    "IsPhenomena": is_phenomena,
                    "LastScanType": "CODEX",
                    "CodexEntryID": entry_id,
                    "CodexName": name_loc.strip(),
                    "BaseValue": pot,
                    "PotentialValue": pot,
                }
            )
            self.state.exo[codex_key] = rec

            # A CodexEntry never goes through ScanOrganic's own "Exobiology
            # complete" messaging (that only fires for the 3-sample cycle),
            # so without this an NSP confirmation's Complete=True above
            # would never actually reach _save_exobiology_to_db() -- that
            # save is itself gated on seeing this exact message.
            if is_phenomena and not rec.get("CompletionAnnounced", False):
                msgs.append(f"Exobiology complete: {genus}")
                rec["CompletionAnnounced"] = True

        # Dispatch order matters slightly: inventory first, then exploration/exobio, then PP, then misc.
        handled = False
        for fn in (
            inventory.handle,
            exploration.handle,
            exobio.handle,
            powerplay.handle,
            fleet_carrier.handle,
            mining.handle,
            engineers.handle,
            misc.handle,
        ):
            try:
                if fn(self, name, event, msgs):
                    handled = True
                    break
            except Exception:
                log.exception("Handler error for event=%s in %s", name, getattr(fn, "__module__", "handler"))
                handled = True
                break

        # ---- DEBUG TRACE: Event end snapshot ----
        try:
            log.debug(
                "EVENT END: %s | bodies=%d exo=%d signals=%d combat=%d msgs=%d",
                name,
                len(self.state.bodies),
                len(self.state.exo),
                len(self.state.system_signals),
                len(self.state.combat_contacts),
                len(msgs),
            )
        except Exception:
            pass

        return self.state, msgs

    def _surface_distance_m(
        self,
        lat1_deg: float,
        lon1_deg: float,
        lat2_deg: float,
        lon2_deg: float,
        radius_m: float,
    ) -> float:
        """
        Great-circle distance between two lat/lon points on a sphere (meters).
        """
        lat1 = math.radians(lat1_deg)
        lon1 = math.radians(lon1_deg)
        lat2 = math.radians(lat2_deg)
        lon2 = math.radians(lon2_deg)
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * (math.sin(dlon / 2.0) ** 2)
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return float(radius_m) * c
