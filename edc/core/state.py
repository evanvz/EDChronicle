from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Set

@dataclass
class GameState:
    commander: Optional[str] = None
    ship: Optional[str] = None
    ship_id: Optional[int] = None
    credits: Optional[int] = None
    system: Optional[str] = None
    system_address: Optional[int] = None
    system_allegiance: Optional[str] = None
    system_economy: Optional[str] = None
    system_security: Optional[str] = None
    population: Optional[int] = None
    pp_power: Optional[str] = None
    pp_rank: Optional[int] = None
    pp_merits: Optional[int] = None
    power: Optional[str] = None
    power_state: Optional[str] = None
    power_rank: Optional[int] = None
    power_merits: Optional[int] = None
    system_controlling_power: Optional[str] = None
    system_powerplay_state: Optional[str] = None
    system_powers: List[str] = field(default_factory=list)
    system_powerplay_conflict_progress: Dict[str, float] = field(default_factory=dict)
    system_powerplay_control_progress: Optional[float] = None
    system_powerplay_reinforcement: Optional[int] = None
    system_powerplay_undermining: Optional[int] = None
    pp_enemy_alerts: List[str] = field(default_factory=list)
    current_contact_alert: str = ""
    combat_contacts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    combat_current_key: str = ""
    cargo_count: Optional[int] = None
    limpets: Optional[int] = None
    system_government: Optional[str] = None
    controlling_faction: Optional[str] = None
    factions: List[Dict[str, Any]] = field(default_factory=list)
    bodies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    system_body_count: Optional[int] = None
    body_id_to_name: Dict[int, str] = field(default_factory=dict)
    exo: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    bio_signals: Dict[str, int] = field(default_factory=dict)          # BodyName -> biological count
    bio_genuses: Dict[str, List[str]] = field(default_factory=dict)    # BodyName -> confirmed genera list
    geo_signals: Dict[str, int] = field(default_factory=dict)          # BodyName -> geological count
    saa_signals: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    non_body_count: Optional[int] = None                               # FSSDiscoveryScan.NonBodyCount
    fss_complete: bool = False
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

    # Misc targeting/combat helpers (safe defaults)
    last_target_ship: Optional[str] = None
    last_target_pilot: Optional[str] = None

    # Cargo snapshot (safe defaults)
    cargo_inventory: List[Dict[str, Any]] = field(default_factory=list)

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
