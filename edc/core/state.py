from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set

@dataclass
class GameState:
    commander: Optional[str] = None
    ship: Optional[str] = None
    odyssey: bool = True
    ship_id: Optional[int] = None
    credits: Optional[int] = None
    system: Optional[str] = None
    system_address: Optional[int] = None
    system_x: Optional[float] = None
    system_y: Optional[float] = None
    system_z: Optional[float] = None
    system_allegiance: Optional[str] = None
    system_economy: Optional[str] = None
    system_economy_secondary: Optional[str] = None
    system_state: Optional[str] = None
    system_security: Optional[str] = None
    population: Optional[int] = None
    pp_power: Optional[str] = None
    pp_rank: Optional[int] = None
    pp_merits: Optional[int] = None
    pp_merits_session: int = 0
    pp_merits_start: Optional[int] = None
    system_controlling_power: Optional[str] = None
    system_powerplay_state: Optional[str] = None
    system_powers: List[str] = field(default_factory=list)
    # None until the first Loadout event this session — deliberately not
    # assumed False by default, since "unknown" and "confirmed unarmed" are
    # different things for the enemy-alert caveat that reads this.
    ship_has_weapons: Optional[bool] = None
    system_powerplay_conflict_progress: Dict[str, float] = field(default_factory=dict)
    system_conflicts: List[dict] = field(default_factory=list)
    system_powerplay_control_progress: Optional[float] = None
    system_powerplay_reinforcement: Optional[int] = None
    system_powerplay_undermining: Optional[int] = None
    pp_enemy_alerts: List[str] = field(default_factory=list)
    current_contact_alert: str = ""
    combat_contacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    combat_current_key: str = ""
    combat_last_key: str = ""
    cargo_count: Optional[int] = None
    limpets: Optional[int] = None
    system_government: Optional[str] = None
    controlling_faction: Optional[str] = None
    factions: List[Dict[str, Any]] = field(default_factory=list)
    bodies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    system_body_count: Optional[int] = None
    body_id_to_name: Dict[int, str] = field(default_factory=dict)
    resolved_body_ids: Set[int] = field(default_factory=set)
    exo: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    bio_signals: Dict[str, int] = field(default_factory=dict)          # BodyName -> biological count
    bio_genuses: Dict[str, List[str]] = field(default_factory=dict)    # BodyName -> confirmed genera list
    geo_signals: Dict[str, int] = field(default_factory=dict)          # BodyName -> geological count
    human_signals: Dict[str, int] = field(default_factory=dict)        # BodyName -> human signal count
    guardian_signals: Dict[str, int] = field(default_factory=dict)
    thargoid_signals: Dict[str, int] = field(default_factory=dict)
    other_signals: Dict[str, int] = field(default_factory=dict)
    saa_signals: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    # RingName -> {system_address, parent_body, ring_class, distance_ls,
    # scanned, hotspots: [{name, count}]}. Populated from Scan events' Rings
    # array (planets and stars both — stars carry no PlanetClass so this is
    # tracked separately from the bodies dict) and marked scanned/populated
    # with material types once SAASignalsFound is reported for that ring.
    rings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    non_body_count: Optional[int] = None                               # FSSDiscoveryScan.NonBodyCount
    fss_complete: bool = False
    route_target_system: Optional[str] = None
    route_target_star_class: Optional[str] = None
    route_remaining_jumps: Optional[int] = None
    system_signals: List[Dict[str, Any]] = field(default_factory=list) # FSSSignalDiscovered entries
    external_pois: List[Dict[str, Any]] = field(default_factory=list)  # advisory (local file), per-system
    last_event: Optional[str] = None
    last_body: Optional[str] = None
    last_codex: Optional[str] = None
    last_organic_scan: Optional[Dict[str, Any]] = None
    last_organic_value: Optional[Any] = None
    in_hyperspace: bool = False
    jump_star_class: Optional[str] = None
    star_class: Optional[str] = None

    # Live position from Status.json (Odyssey/SRV/surface)
    surface_timestamp: Optional[str] = None
    surface_body_name: Optional[str] = None
    surface_lat: Optional[float] = None
    surface_lon: Optional[float] = None
    surface_radius_m: Optional[float] = None

    # Jump bookkeeping (used by handler split)
    pending_system: Optional[str] = None
    last_jump_type: Optional[str] = None

    # Simple session ledgers
    session_exo_earnings: int = 0              # legacy name used previously
    session_exobio_earnings: int = 0           # new handler name
    session_exploration_earnings: int = 0
    session_codex_earnings: int = 0
    session_codex_collected: int = 0
    session_voucher_earnings: int = 0
    community_goals: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    last_cg_joined: Optional[int] = None

    # Bounty session ledgers
    session_bounties: int = 0
    session_kills: int = 0

    # Bounties incurred BY the player (CommitCrime), per issuing faction —
    # distinct from Notoriety, which can't be cleared this way. Persists
    # across restarts (loaded/saved via SessionLedger) since a real bounty
    # doesn't go away just because the app restarted.
    active_bounties: Dict[str, int] = field(default_factory=dict)
    # Closest known station offering Interstellar Factors, not owned by any
    # currently-bounty-issuing faction — see main_window._refresh_bounty_status.
    closest_interstellar_factors: Optional[Dict[str, Any]] = None

    # Notoriety (from the "Statistics" event's Crime.Notoriety) — distinct
    # from bounties: decays 1 point per 2 hours of active in-game time, not
    # clearable by paying. notoriety_timestamp is when this reading was taken.
    notoriety: Optional[int] = None
    notoriety_timestamp: Optional[str] = None

    # Squadron (journal-exposed data only: name/rank/membership transitions —
    # no member roster, chat, or wing-mission data is available from the game).
    squadron_name: Optional[str] = None
    squadron_rank: Optional[int] = None
    squadron_rank_history: List[Dict[str, Any]] = field(default_factory=list)
    squadron_trophies: int = 0
    squadron_status: Optional[str] = None            # last membership transition event name
    squadron_status_timestamp: Optional[str] = None

    # Misc targeting/combat helpers (safe defaults)
    last_target_ship: Optional[str] = None
    last_target_pilot: Optional[str] = None

    # Cargo snapshot (safe defaults)
    cargo_inventory: List[Dict[str, Any]] = field(default_factory=list)

    # Current station's commodity market (Market.json, read on the "Market" event)
    current_market_id: Optional[int] = None
    current_market_station: Optional[str] = None
    current_market_system: Optional[str] = None
    current_market_items: List[Dict[str, Any]] = field(default_factory=list)

    # Visited systems tracking (safe defaults)
    visited_systems: Set[str] = field(default_factory=set)
    
    # Commander-wide inventory (journal-derived; NOT per-system)
    materials_raw: Dict[str, int] = field(default_factory=dict)           # internal name -> count
    materials_manufactured: Dict[str, int] = field(default_factory=dict)  # internal name -> count
    materials_encoded: Dict[str, int] = field(default_factory=dict)       # internal name -> count
    materials_localised: Dict[str, str] = field(default_factory=dict)     # internal name -> display
    materials_last_update: Optional[str] = None                           # journal timestamp

    # Handler split expects per-category localisation dicts (aliases; keep both styles)
    materials_raw_loc: Dict[str, str] = field(default_factory=dict)
    materials_manufactured_loc: Dict[str, str] = field(default_factory=dict)
    materials_encoded_loc: Dict[str, str] = field(default_factory=dict)

    # Odyssey (on-foot) inventory snapshot (journal-derived)
    shiplocker_items: Dict[str, int] = field(default_factory=dict)        # internal name -> count
    shiplocker_localised: Dict[str, str] = field(default_factory=dict)    # internal name -> display
    shiplocker_last_update: Optional[str] = None                          # journal timestamp

    # Handler split expects this name (alias)
    shiplocker_items_loc: Dict[str, str] = field(default_factory=dict)

    # Convenience: internal name -> category (raw/manufactured/encoded/odyssey)
    # Used as a fallback when an item has no explicit category.
    item_category: Dict[str, str] = field(default_factory=dict)

    # Session collected this run only (resets on app start)
    combat_session_collected: int = 0
    exploration_session_collected_est: int = 0
    exobiology_session_collected_est: int = 0

    # Persistent unsold totals (loaded from JSON on startup)
    combat_unsold_total: int = 0
    exploration_unsold_total_est: int = 0
    exobiology_unsold_total_est: int = 0

    # Session dedupe sets (do not persist initially)
    counted_combat_keys: Set[str] = field(default_factory=set)
    counted_exploration_keys: Set[str] = field(default_factory=set)

    # Fleet Carrier (journal-derived; only present if the commander owns one)
    carrier_market_id: Optional[int] = None
    carrier_callsign: Optional[str] = None
    carrier_name: Optional[str] = None
    carrier_docking_access: Optional[str] = None       # all/none/friends/squadron/squadronfriends
    carrier_allow_notorious: Optional[bool] = None
    carrier_fuel_level: Optional[int] = None           # tritium, tons
    carrier_jump_range_curr: Optional[float] = None
    carrier_jump_range_max: Optional[float] = None
    carrier_pending_decommission: Optional[bool] = None
    carrier_space_usage: Dict[str, int] = field(default_factory=dict)   # TotalCapacity/Crew/Cargo/CargoSpaceReserved/ShipPacks/ModulePacks/FreeSpace
    carrier_finance: Dict[str, int] = field(default_factory=dict)       # CarrierBalance/ReserveBalance/AvailableBalance/ReservePercent/TaxRate
    carrier_current_system: Optional[str] = None       # from CarrierJump
    carrier_next_jump_system: Optional[str] = None      # from CarrierJumpRequest (cleared on jump/cancel)
    carrier_next_jump_body: Optional[str] = None
    carrier_trade_orders: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # commodity(lower) -> order details
    # Confirmed-owned carrier's market/carrier ID — squadron members can now
    # see CarrierStats for their SQUADRON's shared carrier too (CarrierType:
    # "SquadronCarrier"), which must not be displayed as the player's own.
    carrier_owned_market_id: Optional[int] = None

    # Squadron's shared carrier (CarrierType:"SquadronCarrier"), tracked
    # separately from the player's own so the two are never conflated.
    # Keys: market_id, name, callsign, current_system, fuel_level,
    # jump_range_curr, jump_range_max, docking_access, allow_notorious,
    # pending_decommission, space_usage, finance, next_jump_system,
    # next_jump_body, last_updated. Trade orders aren't split out here —
    # CarrierTradeOrder events carry no CarrierID, so they can't be
    # reliably attributed between a personal and squadron carrier.
    squadron_carrier: Optional[Dict[str, Any]] = None

    # Currently-active (accepted, not yet completed/failed/abandoned)
    # missions, keyed by MissionID — see edc.core.mission_events.
    active_missions: Dict[int, Dict[str, Any]] = field(default_factory=dict)

    # CMDR rank/progress per category (Combat, Trade, Explore, Soldier,
    # Exobiologist, Empire, Federation, CQC) — from Rank/Progress journal
    # events, see edc.core.rank_scanner for startup backfill.
    ranks: Dict[str, int] = field(default_factory=dict)
    rank_progress: Dict[str, int] = field(default_factory=dict)

    # Trade profit (session-scoped; resets on app start, like mining_refined_totals)
    session_trade_profit: int = 0
    session_trade_spent: int = 0
    session_trade_revenue: int = 0

    # BGS activity credited to the squadron-aligned faction this session —
    # bounty redemptions and trade transactions at a station it controls.
    # See event_engine.py::_at_squadron_faction_station.
    squadron_bgs_bounty_cr: int = 0
    squadron_bgs_trade_cr: int = 0

    # Mining (session-scoped; resets on app start, like the other session_collected fields)
    mining_refined_totals: Dict[str, int] = field(default_factory=dict)     # material(lower) -> units refined this session
    mining_prospected_count: int = 0
    mining_cracked_count: int = 0
    mining_last_prospect_materials: List[Dict[str, Any]] = field(default_factory=list)  # [{"Name":..., "Proportion":...}]
    mining_last_prospect_content: Optional[str] = None       # High/Medium/Low
    mining_last_motherlode_material: Optional[str] = None

    # Engineer unlock progress (journal-derived, EngineerProgress)
    # name -> {"engineer_id": int, "rank": int|None, "progress": str, "rank_progress": int|None}
    engineer_progress: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    counted_exobiology_keys: Set[str] = field(default_factory=set)