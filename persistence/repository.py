import json
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .database import Database
from edc.core.station_pads import effective_pad_size
from edc.core.bgs_conflicts import is_multistate_faction

# 21 days, not the original 14 -- this data now lives in the disposable
# cache DB (network_cache.db), not the personal one, so there's no
# backup-size cost to keeping it a bit longer (requested 2026-08-27, see
# docs/superpowers/specs/2026-08-27-db-split-design.md).
_MARKET_DATA_MAX_AGE_DAYS = 21


def _market_data_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_MARKET_DATA_MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


_FLEET_CARRIER_MAX_AGE_DAYS = 7


def _fleet_carrier_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_FLEET_CARRIER_MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


# War/CivilWar conflicts run a fixed 7-day cycle before Frontier resolves
# them (whichever faction won more days wins outright) -- a War/CivilWar
# entry older than that is guaranteed already over, not just possibly
# stale, so this is tighter than _MARKET_DATA_MAX_AGE_DAYS rather than
# reusing it. Multi-state factions (the other half of system_bgs_status)
# aren't tied to that cycle, but sharing one cutoff for the whole row is
# simpler than tracking per-field freshness for a single upsert row.
_BGS_STATUS_MAX_AGE_DAYS = 7


def _bgs_status_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_BGS_STATUS_MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_data_timestamp(value) -> str:
    """Normalizes an EDSM Unix epoch (int/float) or an ISO8601 string
    (with a 'Z' or '+00:00' suffix) into one consistent
    "YYYY-MM-DDTHH:MM:SSZ" string, so lexical string comparison in SQL
    sorts chronologically correctly regardless of which pipeline
    produced the value -- otherwise a 'Z' and a '+00:00' suffix on the
    same real instant would compare unequal/out of order, since 'Z'
    (ASCII 90) and '+' (ASCII 43) differ as characters. Falls back to
    "now" (UTC) if the input is missing or unparseable, rather than
    storing an unusable value that would always lose the freshness
    comparison."""
    from datetime import datetime, timezone

    dt = None
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        elif isinstance(value, str) and value.strip():
            ts = value.strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OSError):
        dt = None

    if dt is None:
        dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_states(raw) -> List[str]:
    """Parses a faction_snapshots active_states/pending_states/recovering_states
    JSON column (a list of {"State": ..., "Trend": ...} dicts) into a flat
    list of State strings. Mirrors player_faction_panel.py's identical
    helper -- duplicated here rather than imported, since persistence must
    not depend on the UI layer."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        str(s.get("State"))
        for s in data
        if isinstance(s, dict) and s.get("State")
    ]


def _row_is_at_war(faction_state, active_states) -> bool:
    """True if a faction_snapshots row's own faction_state or active_states
    shows War or CivilWar -- mirrors player_faction_panel.py's
    _bgs_action_core() war check, duplicated as logic (not imported) for
    the same layering reason as _parse_states() above."""
    states = {s.lower() for s in _parse_states(active_states)}
    if isinstance(faction_state, str) and faction_state.strip():
        states.add(faction_state.strip().lower())
    return "war" in states or "civilwar" in states


class Repository:
    def __init__(self, db: Database):
        self.db = db

    def save_system(
        self,
        system_address: int,
        system_name: str | None,
        body_count: int | None,
        fss_complete: int | None,
        first_visit: str | None,
        last_visit: str | None,
        visit_count: int | None,
    ):
        self.db.execute(
            """
            INSERT INTO systems (
                system_address,
                system_name,
                body_count,
                fss_complete,
                first_visit,
                last_visit,
                visit_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO UPDATE SET
                system_name = excluded.system_name,
                body_count = excluded.body_count,
                fss_complete = excluded.fss_complete,
                first_visit = excluded.first_visit,
                last_visit = excluded.last_visit,
                visit_count = excluded.visit_count
            """,
            (
                system_address,
                system_name,
                body_count,
                fss_complete,
                first_visit,
                last_visit,
                visit_count,
            ),
        )

    def save_body(
        self,
        system_address: int,
        body_id: int,
        body_name: str,
        planet_class: str,
        terraformable: int,
        landable,
        was_mapped: int,
        dss_mapped: int,
        estimated_value,
        distance_ls,
        volcanism: str = None,
        materials: str = None,
        mass_em=None,
        radius=None,
        surface_gravity=None,
        surface_temperature=None,
        surface_pressure=None,
        atmosphere_type: str = None,
        atmosphere: str = None,
        atmosphere_composition: str = None,
        composition: str = None,
        tidal_lock=None,
        first_discovered=None,
        first_mapped=None,
        was_footfalled: int = 0,
    ):
        self.db.execute(
            """
            INSERT INTO bodies (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped, was_footfalled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                body_name               = excluded.body_name,
                planet_class            = excluded.planet_class,
                terraformable           = excluded.terraformable,
                landable                = excluded.landable,
                was_mapped              = excluded.was_mapped,
                dss_mapped              = excluded.dss_mapped,
                estimated_value         = excluded.estimated_value,
                distance_ls             = excluded.distance_ls,
                volcanism               = COALESCE(excluded.volcanism, bodies.volcanism),
                materials               = COALESCE(excluded.materials, bodies.materials),
                mass_em                 = COALESCE(excluded.mass_em, bodies.mass_em),
                radius                  = COALESCE(excluded.radius, bodies.radius),
                surface_gravity         = COALESCE(excluded.surface_gravity, bodies.surface_gravity),
                surface_temperature     = COALESCE(excluded.surface_temperature, bodies.surface_temperature),
                surface_pressure        = COALESCE(excluded.surface_pressure, bodies.surface_pressure),
                atmosphere_type         = COALESCE(excluded.atmosphere_type, bodies.atmosphere_type),
                atmosphere              = COALESCE(excluded.atmosphere, bodies.atmosphere),
                atmosphere_composition  = COALESCE(excluded.atmosphere_composition, bodies.atmosphere_composition),
                composition             = COALESCE(excluded.composition, bodies.composition),
                tidal_lock              = COALESCE(excluded.tidal_lock, bodies.tidal_lock),
                first_discovered        = COALESCE(excluded.first_discovered, bodies.first_discovered),
                first_mapped            = COALESCE(excluded.first_mapped, bodies.first_mapped),
                was_footfalled          = excluded.was_footfalled
            """,
            (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped, was_footfalled,
            ),
        )

    def save_body_footfall(
        self,
        system_address: int,
        body_name: str,
        first_footfall: int,
        has_footfall: int,
    ):
        self.db.execute(
            """
            UPDATE bodies
            SET first_footfall = ?,
                has_footfall   = ?
            WHERE system_address = ? AND body_name = ?
            """,
            (first_footfall, has_footfall, system_address, body_name),
        )

    def save_body_signals(
        self,
        system_address: int,
        body_name: str,
        bio_signals: int | None,
        geo_signals: int | None,
        human_signals: int | None,
        surface_mining_signals: int | None = None,
    ):
        self.db.execute(
            """
            INSERT INTO body_signals (
                system_address,
                body_name,
                bio_signals,
                geo_signals,
                human_signals,
                surface_mining_signals
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name) DO UPDATE SET
                bio_signals = excluded.bio_signals,
                geo_signals = excluded.geo_signals,
                human_signals = excluded.human_signals,
                surface_mining_signals = excluded.surface_mining_signals
            """,
            (
                system_address,
                body_name,
                bio_signals,
                geo_signals,
                human_signals,
                surface_mining_signals,
            ),
        )

    def save_dss_genus_discovery(
        self,
        system_address: int,
        body_name: str,
        genus: str,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO dss_genus_discovery (
                system_address,
                body_name,
                genus
            )
            VALUES (?, ?, ?)
            ON CONFLICT(system_address, body_name, genus) DO NOTHING
            """,
            (system_address, body_name, genus),
        )

    def get_dss_genus_discovery(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_name,
                genus
            FROM dss_genus_discovery
            WHERE system_address = ?
            ORDER BY body_name, genus
            """,
            (system_address,),
        ).fetchall()

    def save_exobiology(
        self,
        system_address: int,
        body_name: str,
        genus: str,
        species: str,
        variant: str,
        samples: int | None,
    ):
        self.db.execute(
            """
            INSERT INTO exobiology (
                system_address,
                body_name,
                genus,
                species,
                variant,
                samples
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name, genus, species, variant) DO UPDATE SET
                samples = excluded.samples
            """,
            (
                system_address,
                body_name,
                genus,
                species,
                variant,
                samples,
            ),
        )

    def save_codex_entry(
        self,
        system_address: int,
        body_id: int,
        genus: str,
        species: str,
        variant: str,
        codex_entry_id: int | None,
        codex_name: str | None,
        base_value: int | None,
        is_phenomena: int = 0,
    ):
        self.db.execute(
            """
            INSERT INTO codex_entries (
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value, is_phenomena
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, genus) DO UPDATE SET
                species        = excluded.species,
                variant        = excluded.variant,
                codex_entry_id = excluded.codex_entry_id,
                codex_name     = excluded.codex_name,
                base_value     = excluded.base_value,
                is_phenomena   = excluded.is_phenomena
            """,
            (
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value, is_phenomena,
            ),
        )

    def save_resolved_body(self, system_address: int, body_id: int) -> None:
        """Personal FSS/Scan resolution for a body with no PlanetClass (a
        star) -- `bodies` can't hold it, so this is the only durable record
        that it was ever resolved."""
        self.db.execute(
            """
            INSERT INTO resolved_bodies (system_address, body_id)
            VALUES (?, ?)
            ON CONFLICT(system_address, body_id) DO NOTHING
            """,
            (system_address, body_id),
        )

    def get_resolved_body_ids(self, system_address: int) -> list[int]:
        rows = self.db.execute(
            "SELECT body_id FROM resolved_bodies WHERE system_address = ?",
            (system_address,),
        ).fetchall()
        return [row["body_id"] for row in rows]

    def save_system_name_if_missing(self, system_address: int, system_name: str):
        """
        Ensures a systems row (and its system_name) exists for a system the
        player has never personally visited — e.g. one only known from an
        EDDN faction sighting — without touching visit_count/first_visit/
        last_visit/body_count on an existing row (those have real meaning
        for systems the player actually jumped into; ON CONFLICT DO NOTHING
        leaves them alone).
        """
        self.db.execute(
            """
            INSERT INTO systems (system_address, system_name, body_count, fss_complete, first_visit, last_visit, visit_count)
            VALUES (?, ?, NULL, 0, NULL, NULL, 0)
            ON CONFLICT(system_address) DO NOTHING
            """,
            (system_address, system_name),
        )

    def save_system_from_flight_log(
        self,
        system_address: int,
        system_name: str,
        first_visit: str,
        last_visit: str,
        visit_count: int,
        first_discovery: int,
    ):
        """One-time backfill from the commander's personal EDSM flight log
        (tools/import_edsm_flight_log.py) -- only for a system with no
        existing row (ON CONFLICT DO NOTHING). A journal-derived save_system()
        row is always more precise (real body_count/fss_complete, exact visit
        history) and must never be overwritten by an EDSM summary."""
        self.db.execute(
            """
            INSERT INTO systems (
                system_address, system_name, body_count, fss_complete,
                first_visit, last_visit, visit_count, first_discovery
            )
            VALUES (?, ?, NULL, 0, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO NOTHING
            """,
            (system_address, system_name, first_visit, last_visit, visit_count, first_discovery),
        )

    def save_faction_snapshot(
        self,
        system_address: int,
        faction: dict,
        snapshot_date: str,
        is_controlling: bool,
        data_timestamp: str,
        source: str,
    ):
        name = faction.get("Name")
        if not isinstance(name, str) or not name:
            return

        influence = faction.get("Influence")
        my_reputation = faction.get("MyReputation")
        is_squadron_faction = faction.get("SquadronFaction") is True
        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO faction_snapshots (
                system_address, faction_name, snapshot_date,
                influence, government, allegiance, faction_state, happiness,
                active_states, pending_states, recovering_states, is_controlling,
                my_reputation, is_squadron_faction, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, faction_name, snapshot_date) DO UPDATE SET
                influence           = excluded.influence,
                government          = excluded.government,
                allegiance          = excluded.allegiance,
                faction_state       = excluded.faction_state,
                happiness           = excluded.happiness,
                active_states       = excluded.active_states,
                pending_states      = excluded.pending_states,
                recovering_states   = excluded.recovering_states,
                is_controlling      = excluded.is_controlling,
                my_reputation       = excluded.my_reputation,
                is_squadron_faction = excluded.is_squadron_faction,
                data_timestamp      = excluded.data_timestamp,
                source              = excluded.source
            WHERE faction_snapshots.data_timestamp IS NULL
               OR excluded.data_timestamp >= faction_snapshots.data_timestamp
            """,
            (
                system_address,
                name,
                snapshot_date,
                float(influence) if isinstance(influence, (int, float)) else None,
                faction.get("Government"),
                faction.get("Allegiance"),
                faction.get("FactionState"),
                faction.get("Happiness_Localised") or faction.get("Happiness"),
                json.dumps(faction.get("ActiveStates")) if faction.get("ActiveStates") else None,
                json.dumps(faction.get("PendingStates")) if faction.get("PendingStates") else None,
                json.dumps(faction.get("RecoveringStates")) if faction.get("RecoveringStates") else None,
                1 if is_controlling else 0,
                float(my_reputation) if isinstance(my_reputation, (int, float)) else None,
                1 if is_squadron_faction else 0,
                normalized_timestamp,
                source,
            ),
        )
        # Rolling 30-day retention — one row/day already matches the real
        # BGS tick rate, so this just bounds DB growth over time. Never
        # prunes a squadron-faction row though: that flag is an identity
        # fact (which faction the player is aligned to), not a BGS
        # snapshot that goes stale -- a historical backfill (journal
        # replay, EDSM sync, Inara CSV) legitimately writes dates far
        # older than 30 days, and get_player_faction_overview() needs
        # that row to still be there (confirmed live: it was deleted in
        # the same breath it got inserted).
        self.db.execute(
            """
            DELETE FROM faction_snapshots
            WHERE system_address = ? AND faction_name = ?
              AND snapshot_date < date('now', '-30 days')
              AND is_squadron_faction = 0
            """,
            (system_address, name),
        )

    def save_system_bgs_status(
        self, system_address: int, system_name: str, conflicts: list, factions: list,
        data_timestamp: str, source: str,
    ) -> None:
        """
        Upserts current War/CivilWar conflicts and multi-state factions for
        a system -- skipped entirely if there's nothing combat/BGS-relevant
        to show. Freshness-guarded like save_faction_snapshot: whichever
        pipeline (own journal vs EDDN) has the more recent underlying data
        wins regardless of write order.
        """
        war_conflicts = []
        for c in (conflicts or []):
            if not isinstance(c, dict):
                continue
            war_type = str(c.get("WarType", "")).lower()
            if war_type not in ("war", "civilwar"):
                continue
            f1 = c.get("Faction1") or {}
            f2 = c.get("Faction2") or {}
            war_conflicts.append({
                "faction1": f1.get("Name"), "faction2": f2.get("Name"),
                "war_type": war_type, "status": c.get("Status"),
                "won_days1": f1.get("WonDays"), "won_days2": f2.get("WonDays"),
            })

        multistate_factions = []
        for f in (factions or []):
            if not isinstance(f, dict):
                continue
            if is_multistate_faction(f):
                multistate_factions.append({
                    "name": f.get("Name"), "faction_state": f.get("FactionState"),
                    "active_states": f.get("ActiveStates"), "pending_states": f.get("PendingStates"),
                    "recovering_states": f.get("RecoveringStates"),
                })

        if not war_conflicts and not multistate_factions:
            return

        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO net.system_bgs_status (
                system_address, system_name, conflicts, faction_states, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO UPDATE SET
                system_name    = excluded.system_name,
                conflicts      = excluded.conflicts,
                faction_states = excluded.faction_states,
                data_timestamp = excluded.data_timestamp,
                source         = excluded.source
            WHERE net.system_bgs_status.data_timestamp IS NULL
               OR excluded.data_timestamp >= net.system_bgs_status.data_timestamp
            """,
            (
                system_address, system_name,
                json.dumps(war_conflicts), json.dumps(multistate_factions),
                normalized_timestamp, source,
            ),
        )

    def save_system_res_tiers(
        self, system_address: int, system_name: str, tiers: list, data_timestamp: str, source: str,
    ) -> None:
        """Upserts the RES tiers currently known present in a system --
        same freshness-guarded upsert as save_system_bgs_status. Skipped if
        tiers is empty (nothing to show)."""
        clean_tiers = sorted({t for t in (tiers or []) if isinstance(t, str) and t})
        if not clean_tiers:
            return

        normalized_timestamp = _normalize_data_timestamp(data_timestamp)
        self.db.execute(
            """
            INSERT INTO net.system_res_sites (
                system_address, system_name, tiers, data_timestamp, source
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_address) DO UPDATE SET
                system_name    = excluded.system_name,
                tiers          = excluded.tiers,
                data_timestamp = excluded.data_timestamp,
                source         = excluded.source
            WHERE net.system_res_sites.data_timestamp IS NULL
               OR excluded.data_timestamp >= net.system_res_sites.data_timestamp
            """,
            (system_address, system_name, json.dumps(clean_tiers), normalized_timestamp, source),
        )

    def search_bgs_status_near(self, x: float, y: float, z: float, radius_ly: float) -> list[dict]:
        """War/CivilWar + multi-state faction status for every tracked
        system within radius_ly, closest-first. Same bounding-box-then-
        Euclidean-filter pattern as search_market_prices (system_coords is
        galaxy-wide and unbounded, fed continuously by the EDDN listener).
        Rows older than _BGS_STATUS_MAX_AGE_DAYS are excluded -- wars/civil
        wars resolve within a fixed 7-day cycle, so anything older is
        guaranteed already over, not just possibly stale."""
        cutoff = _bgs_status_cutoff()
        rows = self.db.conn.execute(
            """
            SELECT b.system_address, b.system_name, b.conflicts, b.faction_states,
                   b.data_timestamp, sc.x, sc.y, sc.z
            FROM net.system_bgs_status b
            INNER JOIN system_coords sc ON sc.system_name = b.system_name
            WHERE b.data_timestamp >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (cutoff, x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
        ).fetchall()

        results = []
        for r in rows:
            dist = ((r["x"] - x) ** 2 + (r["y"] - y) ** 2 + (r["z"] - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            results.append({
                "system_address": r["system_address"],
                "system_name": r["system_name"],
                "distance_ly": dist,
                "conflicts": json.loads(r["conflicts"]) if r["conflicts"] else [],
                "faction_states": json.loads(r["faction_states"]) if r["faction_states"] else [],
                "data_timestamp": r["data_timestamp"],
            })
        results.sort(key=lambda r: r["distance_ly"])
        return results

    def search_res_sites_near(self, x: float, y: float, z: float, radius_ly: float) -> list[dict]:
        """RES tier presence for every tracked system within radius_ly,
        closest-first. Same pattern/cutoff as search_bgs_status_near."""
        cutoff = _market_data_cutoff()
        rows = self.db.conn.execute(
            """
            SELECT r.system_address, r.system_name, r.tiers, r.data_timestamp, sc.x, sc.y, sc.z
            FROM net.system_res_sites r
            INNER JOIN system_coords sc ON sc.system_name = r.system_name
            WHERE r.data_timestamp >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (cutoff, x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
        ).fetchall()

        results = []
        for r in rows:
            dist = ((r["x"] - x) ** 2 + (r["y"] - y) ** 2 + (r["z"] - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            results.append({
                "system_address": r["system_address"],
                "system_name": r["system_name"],
                "distance_ly": dist,
                "tiers": json.loads(r["tiers"]) if r["tiers"] else [],
                "data_timestamp": r["data_timestamp"],
            })
        results.sort(key=lambda r: r["distance_ly"])
        return results

    def get_bgs_status_for_system(self, system_address: int) -> Optional[dict]:
        """Current War/CivilWar conflicts + multi-state factions for one
        system, if any is on record -- same shape as one entry of
        search_bgs_status_near()'s results, minus distance. Unlike the
        radius search, this has no freshness cutoff: it's a targeted
        single-system lookup the caller already chose to open, so showing
        stale-but-known data alongside its own timestamp is more useful
        than showing nothing."""
        row = self.db.conn.execute(
            "SELECT conflicts, faction_states, data_timestamp FROM net.system_bgs_status WHERE system_address = ?",
            (system_address,),
        ).fetchone()
        if not row:
            return None
        return {
            "conflicts": json.loads(row["conflicts"]) if row["conflicts"] else [],
            "faction_states": json.loads(row["faction_states"]) if row["faction_states"] else [],
            "data_timestamp": row["data_timestamp"],
        }

    def get_player_faction_overview(self) -> Optional[dict]:
        """
        Detects the player's squadron-aligned minor faction (if any, from
        SquadronFaction:true in the journal) and returns its most recent
        recorded status in every system it's ever been seen in — not just
        the current system. Returns None if no squadron faction has ever
        been recorded.

        Tiebroken by data_timestamp, not just snapshot_date -- confirmed
        live: a same-day manual entry (e.g. typed in different case/
        spelling than the game's own exact string) and a same-day real
        journal detection tie on snapshot_date alone, and SQLite's tie
        order for that is unspecified rather than "whichever is actually
        more recent." A mismatched faction_name string silently breaks
        every downstream case-sensitive comparison against the real
        journal Factions[] name.
        """
        row = self.db.conn.execute(
            """
            SELECT faction_name FROM faction_snapshots
            WHERE is_squadron_faction = 1
            ORDER BY snapshot_date DESC, data_timestamp DESC
            LIMIT 1
            """
        ).fetchone()
        if not row:
            return None
        faction_name = row["faction_name"]

        systems = self.db.conn.execute(
            """
            SELECT fs.system_address, s.system_name, fs.influence, fs.faction_state,
                   fs.active_states, fs.pending_states, fs.recovering_states,
                   fs.is_controlling, fs.my_reputation, fs.snapshot_date
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.faction_name = ?
              AND fs.system_address != 0
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.faction_name = fs.faction_name
              )
              AND NOT EXISTS (
                  SELECT 1 FROM dismissed_faction_systems d
                  WHERE d.faction_name = fs.faction_name AND d.system_address = fs.system_address
              )
            ORDER BY fs.is_controlling DESC, fs.influence DESC
            """,
            (faction_name,),
        ).fetchall()

        return {
            "faction_name": faction_name,
            "systems": [dict(r) for r in systems],
        }

    def get_player_faction_system_status(self, faction_name: str, system_address: int) -> Optional[dict]:
        """
        Same shape as one entry of get_player_faction_overview()'s "systems"
        list, but scoped to a single system — used when arriving in-game so
        only that one row needs checking/updating, not the whole ~hundreds
        of tracked systems.
        """
        row = self.db.conn.execute(
            """
            SELECT fs.system_address, s.system_name, fs.influence, fs.faction_state,
                   fs.active_states, fs.pending_states, fs.recovering_states,
                   fs.is_controlling, fs.my_reputation, fs.snapshot_date
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.faction_name = ? AND fs.system_address = ?
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.faction_name = fs.faction_name
              )
              AND NOT EXISTS (
                  SELECT 1 FROM dismissed_faction_systems d
                  WHERE d.faction_name = fs.faction_name AND d.system_address = fs.system_address
              )
            """,
            (faction_name, system_address),
        ).fetchone()
        return dict(row) if row else None

    def get_faction_predictions(self, faction_name: str) -> List[dict]:
        """
        BGS expansion/retreat/conflict prediction, per tracked system, built
        entirely from faction_snapshots history already being collected —
        no new data source. Thresholds are the real Elite Dangerous BGS
        mechanics (not guessed): expansion triggers at >=75% influence,
        retreat triggers below 2.5% (with a 5-6 day grace window), and a
        conflict (War/CivilWar/Election) triggers when two factions'
        influence converges within a few points, both above a 7% floor.

        Each entry:
          system_address, system_name, influence, trend ("up"/"down"/"flat"/None),
          days_in_expansion_range (int or None), days_in_retreat_range (int or None),
          conflict_risk (None or {"faction_name", "influence", "diff"}),
          active_war (None, or {"faction_name", "influence"} where
          faction_name/influence are None if no opponent could be
          identified)

        trend/day-counts are None when there isn't enough history yet (a
        system seen only once) — deliberately not guessed from a single
        data point.
        """
        systems = self.db.conn.execute(
            """
            SELECT DISTINCT fs.system_address, s.system_name
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.faction_name = ?
              AND NOT EXISTS (
                  SELECT 1 FROM dismissed_faction_systems d
                  WHERE d.faction_name = fs.faction_name AND d.system_address = fs.system_address
              )
            """,
            (faction_name,),
        ).fetchall()

        out: List[dict] = []
        for row in systems:
            system_address = row["system_address"]
            system_name = row["system_name"]
            prediction = self._predict_faction_in_system(system_address, faction_name)
            out.append({
                "system_address": system_address,
                "system_name": system_name,
                **prediction,
            })
        return out

    def _predict_faction_in_system(self, system_address: int, faction_name: str) -> dict:
        """
        Single-(system, faction) half of get_faction_predictions()'s
        computation — extracted so it can also be run for every faction in
        a system (see get_all_faction_predictions_for_system), not just one
        tracked faction. Same fields as one get_faction_predictions() entry,
        minus system_address/system_name (the caller already has those).
        """
        history = [
            dict(h) for h in self.db.conn.execute(
                """
                SELECT snapshot_date, influence FROM faction_snapshots
                WHERE system_address = ? AND faction_name = ? AND influence IS NOT NULL
                ORDER BY snapshot_date DESC
                LIMIT 14
                """,
                (system_address, faction_name),
            ).fetchall()
        ]

        trend = None
        if len(history) >= 2:
            newest, oldest = history[0]["influence"], history[-1]["influence"]
            if newest - oldest > 0.02:
                trend = "up"
            elif oldest - newest > 0.02:
                trend = "down"
            else:
                trend = "flat"

        our_influence = history[0]["influence"] if history else None

        days_in_expansion_range = None
        if our_influence is not None and our_influence >= 0.70:
            days_in_expansion_range = 0
            for h in history:
                if h["influence"] >= 0.70:
                    days_in_expansion_range += 1
                else:
                    break

        days_in_retreat_range = None
        if our_influence is not None and our_influence < 0.05:
            days_in_retreat_range = 0
            for h in history:
                if h["influence"] < 0.05:
                    days_in_retreat_range += 1
                else:
                    break

        conflict_risk = None
        if our_influence is not None and our_influence >= 0.07:
            rivals = self.db.conn.execute(
                """
                SELECT fs.faction_name, fs.influence
                FROM faction_snapshots fs
                WHERE fs.system_address = ? AND fs.faction_name != ?
                  AND fs.influence IS NOT NULL AND fs.influence >= 0.07
                  AND fs.snapshot_date = (
                      SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                      WHERE fs2.system_address = fs.system_address
                        AND fs2.faction_name = fs.faction_name
                  )
                """,
                (system_address, faction_name),
            ).fetchall()
            best, best_diff = None, None
            for r in rivals:
                diff = abs(r["influence"] - our_influence)
                if diff <= 0.05 and (best_diff is None or diff < best_diff):
                    best, best_diff = r, diff
            if best is not None:
                conflict_risk = {
                    "faction_name": best["faction_name"],
                    "influence": best["influence"],
                    "diff": best_diff,
                }

        active_war = None
        own_row = self.db.conn.execute(
            """
            SELECT faction_state, active_states, snapshot_date
            FROM faction_snapshots
            WHERE system_address = ? AND faction_name = ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (system_address, faction_name),
        ).fetchone()
        if own_row is not None and _row_is_at_war(own_row["faction_state"], own_row["active_states"]):
            war_rivals = self.db.conn.execute(
                """
                SELECT fs.faction_name, fs.influence, fs.faction_state, fs.active_states
                FROM faction_snapshots fs
                WHERE fs.system_address = ? AND fs.faction_name != ?
                  AND fs.snapshot_date = ?
                """,
                (system_address, faction_name, own_row["snapshot_date"]),
            ).fetchall()
            best_opponent = None
            for r in war_rivals:
                if not _row_is_at_war(r["faction_state"], r["active_states"]):
                    continue
                r_influence = r["influence"] if isinstance(r["influence"], (int, float)) else 0.0
                best_influence = best_opponent["influence"] if best_opponent and isinstance(best_opponent["influence"], (int, float)) else -1.0
                if best_opponent is None or r_influence > best_influence:
                    best_opponent = r
            if best_opponent is not None:
                active_war = {"faction_name": best_opponent["faction_name"], "influence": best_opponent["influence"]}
            else:
                active_war = {"faction_name": None, "influence": None}

        return {
            "influence": our_influence,
            "trend": trend,
            "days_in_expansion_range": days_in_expansion_range,
            "days_in_retreat_range": days_in_retreat_range,
            "conflict_risk": conflict_risk,
            "active_war": active_war,
        }

    def get_all_faction_predictions_for_system(self, system_address: int) -> List[dict]:
        """
        Prediction (trend/expansion/retreat/conflict/active-war) for every
        faction with a snapshot in this system, not just one tracked
        faction — used by the Player Faction tab's per-system history
        drill-down. Same fields as one get_faction_predictions() entry,
        minus system_address/system_name, plus faction_name. Sorted by
        current influence descending; entries with no known influence
        (None) sort last.
        """
        rows = self.db.conn.execute(
            "SELECT DISTINCT faction_name FROM faction_snapshots WHERE system_address = ?",
            (system_address,),
        ).fetchall()

        out: List[dict] = []
        for row in rows:
            faction_name = row["faction_name"]
            prediction = self._predict_faction_in_system(system_address, faction_name)
            prediction["faction_name"] = faction_name
            out.append(prediction)

        out.sort(key=lambda p: (p["influence"] is None, -(p["influence"] or 0.0)))
        return out

    def save_ring(
        self,
        system_address: int,
        ring_name: str,
        parent_body: Optional[str],
        ring_class: Optional[str],
        distance_ls: Optional[float],
        scanned: bool,
        hotspots: Optional[list],
    ) -> None:
        """
        Upserts one ring's known state. scanned only ever moves False->True
        (MAX), and hotspots/ring_class/distance_ls only overwrite the stored
        value when the new data actually has something — so a later Scan
        event (which knows distance but not hotspots) can't clobber hotspot
        data an earlier SAASignalsFound already recorded, or vice versa.
        """
        hotspots_json = json.dumps(hotspots) if hotspots else None
        self.db.execute(
            """
            INSERT INTO rings (
                system_address, ring_name, parent_body, ring_class,
                distance_ls, scanned, hotspots
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, ring_name) DO UPDATE SET
                parent_body = COALESCE(excluded.parent_body, rings.parent_body),
                ring_class  = COALESCE(NULLIF(excluded.ring_class, ''), rings.ring_class),
                distance_ls = COALESCE(excluded.distance_ls, rings.distance_ls),
                scanned     = MAX(rings.scanned, excluded.scanned),
                hotspots    = COALESCE(excluded.hotspots, rings.hotspots)
            """,
            (
                system_address, ring_name, parent_body, ring_class,
                distance_ls, int(bool(scanned)), hotspots_json,
            ),
        )

    def get_rings_for_system(self, system_address: int) -> list[dict]:
        rows = self.db.conn.execute(
            """
            SELECT ring_name, parent_body, ring_class, distance_ls, scanned, hotspots
            FROM rings WHERE system_address = ?
            """,
            (system_address,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["hotspots"] = json.loads(d["hotspots"]) if d.get("hotspots") else []
            except (TypeError, ValueError):
                d["hotspots"] = []
            d["scanned"] = bool(d["scanned"])
            out.append(d)
        return out

    def get_known_system_names(self, faction_name: str) -> set[str]:
        """
        Lowercased system names we already have faction_snapshots data for,
        for this faction — regardless of dismissed status (a dismissed
        system is still "known"; skipping it on a bulk re-import leaves it
        dismissed rather than silently reviving it). Used to skip redundant
        EDSM re-lookups on a repeat CSV import.
        """
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT s.system_name
            FROM faction_snapshots fs
            JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.faction_name = ? AND s.system_name IS NOT NULL
            """,
            (faction_name,),
        ).fetchall()
        return {r["system_name"].strip().lower() for r in rows if r["system_name"]}

    def get_faction_system_names_missing_coords(self, faction_name: str, limit: int = 10) -> list[str]:
        """
        Tracked systems for this faction that never got a system_coords
        row — confirmed live: EDSM's coords endpoint used to be one-shot
        with no retry, so a bulk CSV import hitting even a single
        transient rate-limit blip could leave a system permanently
        coordinate-less until someone manually clicked "Recheck via
        EDSM". This is what a periodic background backfill sweep queries
        to find its next batch. limit bounds one sweep tick's EDSM
        request cost, not the total gap — repeated ticks work through it.
        """
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT s.system_name
            FROM faction_snapshots fs
            JOIN systems s ON s.system_address = fs.system_address
            LEFT JOIN system_coords sc ON sc.system_name = s.system_name
            WHERE fs.faction_name = ? AND s.system_name IS NOT NULL AND sc.system_name IS NULL
            LIMIT ?
            """,
            (faction_name, limit),
        ).fetchall()
        return [r["system_name"] for r in rows if r["system_name"]]

    def get_stale_faction_systems(self, faction_name: str, current_names: set[str]) -> list[dict]:
        """
        Currently-visible systems (see get_player_faction_overview — already
        excludes dismissed ones) for faction_name whose name isn't in
        current_names (case-insensitive) — i.e. systems we're tracking that
        a fresh "complete" export no longer lists, suggesting the faction
        may have lost presence there. Advisory only — caller decides
        whether to dismiss them, this doesn't touch the database.
        """
        lowered = {n.strip().lower() for n in current_names if n}
        overview = self.get_player_faction_overview()
        if not overview or overview["faction_name"] != faction_name:
            return []
        return [
            s for s in overview["systems"]
            if (s.get("system_name") or "").strip().lower() not in lowered
        ]

    def dismiss_faction_system(self, faction_name: str, system_address: int):
        """
        Hides a system from get_player_faction_overview() without deleting
        its faction_snapshots history — for when the squadron loses presence
        there ("kicked out") and it shouldn't keep showing in the current
        list. Sticky/permanent until manually undone — new snapshots for
        the same system don't automatically clear it, since EDDN sightings
        can lag real-world presence changes.
        """
        self.db.execute(
            """
            INSERT INTO dismissed_faction_systems (faction_name, system_address)
            VALUES (?, ?)
            ON CONFLICT(faction_name, system_address) DO NOTHING
            """,
            (faction_name, system_address),
        )

    def undismiss_faction_system(self, faction_name: str, system_address: int):
        """Reverses dismiss_faction_system — used when the same system is
        deliberately re-added (manually, or a fresh EDDN sighting), which
        should override an earlier "kicked out" dismissal."""
        self.db.execute(
            "DELETE FROM dismissed_faction_systems WHERE faction_name = ? AND system_address = ?",
            (faction_name, system_address),
        )

    def save_system_coords_batch(self, records: list[tuple[str, float, float, float, str]]):
        """records: [(system_name, x, y, z, last_seen), ...]"""
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO system_coords (system_name, x, y, z, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_name) DO UPDATE SET
                x = excluded.x, y = excluded.y, z = excluded.z, last_seen = excluded.last_seen
            """,
            records,
        )
        self.db.conn.commit()

    def get_system_coords_for_names(self, names: list[str]) -> dict:
        """{system_name: (x, y, z)} for whichever of `names` we have EDDN-
        harvested coords for — used to distance-sort a bucket of tracked
        systems from the player's current location."""
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        rows = self.db.conn.execute(
            f"SELECT system_name, x, y, z FROM system_coords WHERE system_name IN ({placeholders})",
            names,
        ).fetchall()
        return {r["system_name"]: (r["x"], r["y"], r["z"]) for r in rows}

    def save_market_snapshot_batch(self, records: list[tuple]):
        """
        records: [(market_id, commodity_name, station_name, station_type,
                    system_name, sell_price, buy_price, mean_price, demand,
                    demand_bracket, stock, stock_bracket, last_updated), ...]
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.market_prices (
                market_id, commodity_name, station_name, station_type, system_name,
                sell_price, buy_price, mean_price, demand, demand_bracket,
                stock, stock_bracket, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id, commodity_name) DO UPDATE SET
                station_name   = excluded.station_name,
                station_type   = excluded.station_type,
                system_name    = excluded.system_name,
                sell_price     = excluded.sell_price,
                buy_price      = excluded.buy_price,
                mean_price     = excluded.mean_price,
                demand         = excluded.demand,
                demand_bracket = excluded.demand_bracket,
                stock          = excluded.stock,
                stock_bracket  = excluded.stock_bracket,
                last_updated   = excluded.last_updated
            """,
            records,
        )
        self.db.conn.commit()

    def save_fleet_carrier_materials_batch(self, records: list[tuple]):
        """
        records: [(market_id, material_symbol, carrier_name, carrier_id,
                    price, stock, demand, last_updated), ...]
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.fleet_carrier_materials (
                market_id, material_symbol, carrier_name, carrier_id,
                price, stock, demand, last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id, material_symbol) DO UPDATE SET
                carrier_name = excluded.carrier_name,
                carrier_id   = excluded.carrier_id,
                price        = excluded.price,
                stock        = excluded.stock,
                demand       = excluded.demand,
                last_updated = excluded.last_updated
            """,
            records,
        )
        self.db.conn.commit()

    def save_carrier_docking_access_batch(self, records: list[tuple]):
        """
        records: [(market_id, docking_access, timestamp), ...] -- from EDDN
        commodity/3's optional carrierDockingAccess field. Upserts only the
        carrier_docking_access column on station_info; if no row exists yet
        for this market_id (no Docked sighting seen), inserts a skeletal
        row with just market_id + this column -- a later Docked sighting's
        own upsert (save_station_info_batch) fills in the rest without
        touching this column. Harmless either arrival order.
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.station_info (market_id, carrier_docking_access)
            VALUES (?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                carrier_docking_access = excluded.carrier_docking_access
            """,
            [(market_id, access) for market_id, access, _ts in records],
        )
        self.db.conn.commit()

    def prune_stale_market_prices(self, batch_size: int = 20_000) -> int:
        """
        Deletes rows already excluded from search results by
        _market_data_cutoff() — a stale row is dead weight once nothing
        can ever surface it, not just hidden. Same 21-day threshold as the
        search filter, so this doesn't change what search can find, only
        what's still sitting on disk. Call from a worker thread only — a
        DELETE across the whole market_prices table is not instant at
        galaxy-wide scale (millions of rows).

        Deleted in batches, each its own committed transaction, rather
        than one giant DELETE — a single multi-million-row DELETE holds
        SQLite's write lock for its entire duration (confirmed live: ~2
        minutes at 1.5M+ rows), which starves every OTHER concurrent
        background writer (the historical journal importer, the Player
        Faction daily EDSM refresh) past their 30s busy_timeout, failing
        with "database is locked". Committing after every batch releases
        the lock repeatedly, giving other writers a real chance to
        interleave instead of one long exclusive hold.
        """
        cutoff = _market_data_cutoff()
        total_deleted = 0
        while True:
            cur = self.db.conn.execute(
                "DELETE FROM net.market_prices WHERE rowid IN "
                "(SELECT rowid FROM net.market_prices WHERE last_updated < ? LIMIT ?)",
                (cutoff, batch_size),
            )
            self.db.conn.commit()
            deleted = cur.rowcount
            total_deleted += deleted
            if deleted < batch_size:
                break
            time.sleep(0.05)
        return total_deleted

    def prune_stale_fleet_carrier_materials(self, batch_size: int = 20_000) -> int:
        """
        Deletes rows already excluded from search results by
        _fleet_carrier_cutoff() — same reasoning as prune_stale_market_prices():
        a stale row is dead weight once nothing can ever surface it, not
        just hidden. Same 7-day threshold as the search filter, so this
        doesn't change what search can find, only what's still sitting on
        disk. Call from a worker thread only. Batched the same way and for
        the same reason as prune_stale_market_prices()."""
        cutoff = _fleet_carrier_cutoff()
        total_deleted = 0
        while True:
            cur = self.db.conn.execute(
                "DELETE FROM net.fleet_carrier_materials WHERE rowid IN "
                "(SELECT rowid FROM net.fleet_carrier_materials WHERE last_updated < ? LIMIT ?)",
                (cutoff, batch_size),
            )
            self.db.conn.commit()
            deleted = cur.rowcount
            total_deleted += deleted
            if deleted < batch_size:
                break
            time.sleep(0.05)
        return total_deleted

    def prune_stale_system_bgs_status(self, batch_size: int = 20_000) -> int:
        """
        Deletes rows already excluded from search results by
        _bgs_status_cutoff() -- same reasoning as prune_stale_market_prices(),
        matching search_bgs_status_near's own 7-day cutoff (wars/civil wars
        resolve within a fixed 7-day cycle), so this doesn't change what
        search can find, only what's still sitting on disk. system_bgs_status
        is fed unconditionally by EDDN network-wide, so it's genuinely
        unbounded without this. Batched the same way and for the same
        reason as prune_stale_market_prices()."""
        cutoff = _bgs_status_cutoff()
        total_deleted = 0
        while True:
            cur = self.db.conn.execute(
                "DELETE FROM net.system_bgs_status WHERE rowid IN "
                "(SELECT rowid FROM net.system_bgs_status WHERE data_timestamp < ? LIMIT ?)",
                (cutoff, batch_size),
            )
            self.db.conn.commit()
            deleted = cur.rowcount
            total_deleted += deleted
            if deleted < batch_size:
                break
            time.sleep(0.05)
        return total_deleted

    def prune_stale_system_res_sites(self, batch_size: int = 20_000) -> int:
        """Same reasoning/cutoff/batching as prune_stale_system_bgs_status(),
        for system_res_sites."""
        cutoff = _market_data_cutoff()
        total_deleted = 0
        while True:
            cur = self.db.conn.execute(
                "DELETE FROM net.system_res_sites WHERE rowid IN "
                "(SELECT rowid FROM net.system_res_sites WHERE data_timestamp < ? LIMIT ?)",
                (cutoff, batch_size),
            )
            self.db.conn.commit()
            deleted = cur.rowcount
            total_deleted += deleted
            if deleted < batch_size:
                break
            time.sleep(0.05)
        return total_deleted

    def save_commodity_names_batch(self, pairs: list[tuple[str, str]]):
        """
        pairs: [(internal_name, display_name), ...] — captured from the
        player's own Market.json (which has both), used to build a proper
        autocomplete list instead of guessing display names from EDDN's
        internal-only commodity symbols.
        """
        if not pairs:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.commodity_names (internal_name, display_name)
            VALUES (?, ?)
            ON CONFLICT(internal_name) DO UPDATE SET display_name = excluded.display_name
            """,
            pairs,
        )
        self.db.conn.commit()

    def get_all_commodity_display_names(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT display_name FROM net.commodity_names ORDER BY display_name"
        ).fetchall()
        return [r["display_name"] for r in rows]

    def get_commodity_display_name_map(self) -> dict[str, str]:
        """{internal_name: display_name} — market_prices only ever stores
        EDDN's internal commodity symbol (e.g. "lowtemperaturediamond"),
        never the pretty name, so anything rendering a commodity_name
        straight from that table needs this to show real names."""
        rows = self.db.conn.execute(
            "SELECT internal_name, display_name FROM net.commodity_names"
        ).fetchall()
        return {r["internal_name"]: r["display_name"] for r in rows}

    def save_station_info(
        self,
        market_id: int,
        station_name: Optional[str],
        system_name: Optional[str],
        station_type: Optional[str],
        pads_small: Optional[int],
        pads_medium: Optional[int],
        pads_large: Optional[int],
        last_visited: Optional[str],
        station_services: Optional[list] = None,
        station_faction: Optional[str] = None,
    ):
        """Ground truth from our own Docked events — ON CONFLICT keeps the latest visit's data."""
        self.db.execute(
            """
            INSERT INTO net.station_info (
                market_id, station_name, system_name, station_type,
                pads_small, pads_medium, pads_large, last_visited,
                station_services, station_faction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                station_name     = excluded.station_name,
                system_name      = excluded.system_name,
                station_type     = excluded.station_type,
                pads_small       = excluded.pads_small,
                pads_medium      = excluded.pads_medium,
                pads_large       = excluded.pads_large,
                last_visited     = excluded.last_visited,
                station_services = excluded.station_services,
                station_faction  = excluded.station_faction
            """,
            (market_id, station_name, system_name, station_type,
             pads_small, pads_medium, pads_large, last_visited,
             json.dumps(station_services) if station_services else None,
             station_faction),
        )

    def save_station_info_batch(self, records: list[dict]) -> None:
        """
        Same upsert as save_station_info, batched — for EDDN-sourced Docked
        sightings from other commanders (buffered and flushed periodically,
        same pattern as save_market_snapshot_batch). Each record is a dict
        shaped like edc.core.station_pads.extract_station_info()'s return
        value. A later sighting (ours or another commander's) always wins;
        EDDN traffic is near-live, so this keeps station services/pad sizes
        current without being limited to only our own past visits.
        """
        if not records:
            return
        rows = [
            (
                r["market_id"], r.get("station_name"), r.get("system_name"), r.get("station_type"),
                r.get("pads_small"), r.get("pads_medium"), r.get("pads_large"), r.get("timestamp"),
                json.dumps(r["station_services"]) if r.get("station_services") else None,
                r.get("station_faction"), r.get("economies"), r.get("dist_from_star_ls"),
                r.get("station_government"), r.get("station_allegiance"),
            )
            for r in records
        ]
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.station_info (
                market_id, station_name, system_name, station_type,
                pads_small, pads_medium, pads_large, last_visited,
                station_services, station_faction, economies,
                dist_from_star_ls, station_government, station_allegiance
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(market_id) DO UPDATE SET
                station_name       = excluded.station_name,
                system_name        = excluded.system_name,
                station_type       = excluded.station_type,
                pads_small         = excluded.pads_small,
                pads_medium        = excluded.pads_medium,
                pads_large         = excluded.pads_large,
                last_visited       = excluded.last_visited,
                station_services   = excluded.station_services,
                station_faction    = excluded.station_faction,
                economies          = excluded.economies,
                dist_from_star_ls  = excluded.dist_from_star_ls,
                station_government = excluded.station_government,
                station_allegiance = excluded.station_allegiance
            """,
            rows,
        )
        self.db.conn.commit()

    def save_codex_species_sightings_batch(self, records: list[tuple]) -> None:
        """
        Each record: (system_address, body_id, species_name_localised,
        species_symbol, timestamp) — from EddnMarketCache's codex buffer.
        Species are deterministic per body, so a later sighting can only
        ever confirm the same species again; no conflict resolution needed
        beyond keeping the freshest timestamp.
        """
        if not records:
            return
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO net.codex_species_sightings (
                system_address, body_id, species_name, species_symbol, last_seen
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                species_name   = excluded.species_name,
                species_symbol = excluded.species_symbol,
                last_seen      = excluded.last_seen
            """,
            records,
        )
        self.db.conn.commit()

    def get_codex_species_sightings_for_system(self, system_address: int) -> dict[int, dict]:
        """{body_id: {"species_name": str, "last_seen": str}} for every body
        in this system another commander (or us, via our own EDDN publish
        loopback) has already logged a biology CodexEntry for."""
        rows = self.db.conn.execute(
            "SELECT body_id, species_name, last_seen FROM net.codex_species_sightings WHERE system_address = ?",
            (system_address,),
        ).fetchall()
        return {r["body_id"]: {"species_name": r["species_name"], "last_seen": r["last_seen"]} for r in rows}

    def find_closest_interstellar_factors(
        self, x: float, y: float, z: float, exclude_factions: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """
        Closest known station (from our own past Docked visits) confirmed to
        offer Interstellar Factors ("Facilitator" in StationServices), in a
        SYSTEM where none of exclude_factions has any presence at all —
        confirmed against Elite Dangerous's actual rule (cross-checked
        multiple sources): Interstellar Factors refuses to clear a bounty
        or fine if the issuing faction is present anywhere in that system,
        not merely if it controls the specific station. A non-controlling
        5%-influence minor presence still blocks it, so this checks every
        faction_snapshots row for the system, not just station_faction.
        Distance computed in Python against system_coords, same pattern as
        search_market_prices — dataset is bounded to stations we've visited.

        Interstellar Factors presence is BGS-driven (only spawns in Low
        Security/Anarchy stations, and disappears if the system's security
        or controlling faction changes), so this is only as fresh as our
        last recorded visit — last_visited is returned so the caller can
        surface that caveat rather than presenting it as guaranteed-current.
        The system-presence exclusion carries the same freshness caveat:
        a system with no faction_snapshots history for an excluded faction
        looks clear here even if that faction is quietly present but never
        personally observed or EDDN-reported there.
        """
        excluded = [f.strip() for f in (exclude_factions or []) if f]
        excluded_lower = {f.lower() for f in excluded}

        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            exclusion_clause = f"""
                AND NOT EXISTS (
                    SELECT 1 FROM systems sy
                    JOIN faction_snapshots fs ON fs.system_address = sy.system_address
                    WHERE sy.system_name = si.system_name
                      AND fs.faction_name IN ({placeholders})
                      AND fs.snapshot_date = (
                          SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                          WHERE fs2.system_address = fs.system_address AND fs2.faction_name = fs.faction_name
                      )
                )
            """
            params: tuple = tuple(excluded)
        else:
            exclusion_clause = ""
            params = ()

        rows = self.db.conn.execute(
            f"""
            SELECT si.market_id, si.station_name, si.system_name, si.station_faction,
                   si.station_type, si.pads_small, si.pads_medium, si.pads_large,
                   si.last_visited, c.x, c.y, c.z
            FROM net.station_info si
            JOIN system_coords c ON c.system_name = si.system_name
            WHERE si.station_services LIKE '%Facilitator%'
            {exclusion_clause}
            """,
            params,
        ).fetchall()

        best = None
        best_dist = None
        for r in rows:
            # Belt-and-suspenders alongside the SQL system-presence
            # exclusion above: covers a station whose own station_faction
            # we know (from a personal Docked visit) even in a system
            # faction_snapshots has no history for at all.
            station_faction = (r["station_faction"] or "").strip().lower()
            if station_faction and station_faction in excluded_lower:
                continue
            rx, ry, rz = r["x"], r["y"], r["z"]
            if rx is None or ry is None or rz is None:
                continue
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = dict(r)

        if best is None:
            return None
        best["distance_ly"] = best_dist
        best["pad_size"] = effective_pad_size(
            best["station_type"], best.get("pads_small"), best.get("pads_medium"), best.get("pads_large")
        )
        return best

    def find_closest_station_for_faction(
        self, x: float, y: float, z: float, faction_name: str,
    ) -> Optional[dict]:
        """
        Closest known station (from our own past Docked visits) controlled
        by faction_name — e.g. for redeeming combat bonds/bounty vouchers
        somewhere that actually credits that faction's BGS influence.
        Same bounded-to-visited-stations caveat as find_closest_interstellar_factors.
        """
        target = (faction_name or "").strip().lower()
        if not target:
            return None

        rows = self.db.conn.execute(
            """
            SELECT si.market_id, si.station_name, si.system_name, si.station_faction,
                   si.station_type, si.pads_small, si.pads_medium, si.pads_large,
                   si.last_visited, c.x, c.y, c.z
            FROM net.station_info si
            JOIN system_coords c ON c.system_name = si.system_name
            WHERE LOWER(si.station_faction) = ?
            """,
            (target,),
        ).fetchall()

        best = None
        best_dist = None
        for r in rows:
            rx, ry, rz = r["x"], r["y"], r["z"]
            if rx is None or ry is None or rz is None:
                continue
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = dict(r)

        if best is None:
            return None
        best["distance_ly"] = best_dist
        best["pad_size"] = effective_pad_size(
            best["station_type"], best.get("pads_small"), best.get("pads_medium"), best.get("pads_large")
        )
        return best

    def get_pad_sizes_for_markets(self, market_ids: list[int]) -> dict[int, str]:
        """
        {market_id: pad_size} for whichever of market_ids we happen to have
        our own station_info row for — used to enrich EDSM's station
        catalog (which has no pad size at all) with our own ground truth
        from actual past Docked visits, where we have it.
        """
        if not market_ids:
            return {}
        placeholders = ",".join("?" for _ in market_ids)
        rows = self.db.conn.execute(
            f"SELECT market_id, station_type, pads_small, pads_medium, pads_large "
            f"FROM net.station_info WHERE market_id IN ({placeholders})",
            market_ids,
        ).fetchall()
        return {
            r["market_id"]: effective_pad_size(
                r["station_type"], r["pads_small"], r["pads_medium"], r["pads_large"]
            )
            for r in rows
        }

    def find_faction_stations_in_system(
        self, system_name: str, faction_name: str,
    ) -> List[dict]:
        """
        Known stations/settlements in system_name (from our own visits +
        the EDDN network feed) controlled by faction_name — for finding
        somewhere in the current system to hand in missions or redeem
        bounties that actually credits this faction.
        """
        target = (faction_name or "").strip().lower()
        if not target or not system_name:
            return []

        rows = self.db.conn.execute(
            """
            SELECT market_id, station_name, system_name, station_faction,
                   station_type, pads_small, pads_medium, pads_large, last_visited
            FROM net.station_info
            WHERE LOWER(station_faction) = ? AND system_name = ?
            ORDER BY station_name
            """,
            (target, system_name),
        ).fetchall()

        out = []
        for r in rows:
            d = dict(r)
            d["pad_size"] = effective_pad_size(
                d["station_type"], d.get("pads_small"), d.get("pads_medium"), d.get("pads_large")
            )
            out.append(d)
        return out

    def get_station_info(self, market_id: int) -> dict | None:
        """Full station_info row (as a dict) for a market_id, or None."""
        row = self.db.conn.execute(
            "SELECT * FROM net.station_info WHERE market_id = ?", (market_id,)
        ).fetchone()
        return dict(row) if row else None

    def find_stations_with_service(
        self, x: float, y: float, z: float, service_tags: list[str],
    ) -> list[dict]:
        """
        Every known station (from our own past Docked visits) whose
        StationServices includes ALL of service_tags (e.g. "pioneersupplies"
        alone finds Pioneer Supplies kiosks generally, but buying something
        like E-Breach specifically also requires "blackmarket" present at
        the same station — pass both when that distinction matters). Same
        bounded-to-visited-stations caveat as find_closest_interstellar_factors.
        """
        where_clause = " AND ".join(["si.station_services LIKE ?"] * len(service_tags))
        params = [f'%"{tag}"%' for tag in service_tags]
        rows = self.db.conn.execute(
            f"""
            SELECT si.market_id, si.station_name, si.system_name, si.station_faction,
                   si.station_type, si.pads_small, si.pads_medium, si.pads_large,
                   si.last_visited, c.x, c.y, c.z
            FROM net.station_info si
            JOIN system_coords c ON c.system_name = si.system_name
            WHERE {where_clause}
            """,
            params,
        ).fetchall()

        results = []
        for r in rows:
            rx, ry, rz = r["x"], r["y"], r["z"]
            if rx is None or ry is None or rz is None:
                continue
            rec = dict(r)
            rec["distance_ly"] = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            rec["pad_size"] = effective_pad_size(
                rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
            )
            results.append(rec)
        results.sort(key=lambda r: r["distance_ly"])
        return results

    def get_known_rare_goods(
        self, rare_items: list[dict], x: float, y: float, z: float,
    ) -> list[dict]:
        """
        Cross-references the real rare-goods reference list (EDCD/FDevIDs,
        each with its one true canonical market_id) against whatever the
        EDDN commodity feed has actually reported for that exact
        (market_id, commodity_name) pair — grounding results in the
        canonical station rather than any station that happens to have a
        stale/noisy listing under the same commodity name. Rare goods we've
        never seen reported are simply omitted, not guessed.
        """
        if not rare_items:
            return []
        market_ids = [it["market_id"] for it in rare_items]
        placeholders = ",".join("?" * len(market_ids))
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.commodity_name, m.station_name, m.station_type, m.system_name,
                   m.sell_price, m.buy_price, m.stock, m.demand, m.last_updated,
                   c.x, c.y, c.z,
                   si.pads_small, si.pads_medium, si.pads_large
            FROM net.market_prices m
            LEFT JOIN system_coords c ON c.system_name = m.system_name
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE m.market_id IN ({placeholders})
            """,
            market_ids,
        ).fetchall()

        by_market: dict[int, list] = {}
        for r in rows:
            by_market.setdefault(r["market_id"], []).append(r)

        results = []
        for it in rare_items:
            match = next(
                (r for r in by_market.get(it["market_id"], []) if r["commodity_name"] == it["symbol"]),
                None,
            )
            if match is None:
                continue
            rec = dict(match)
            rec["rare_name"] = it["name"]
            rec["category"] = it.get("category")
            if match["x"] is not None and match["y"] is not None and match["z"] is not None:
                rec["distance_ly"] = ((match["x"] - x) ** 2 + (match["y"] - y) ** 2 + (match["z"] - z) ** 2) ** 0.5
            else:
                rec["distance_ly"] = None
            rec["pad_size"] = effective_pad_size(
                rec.get("station_type"), rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
            )
            results.append(rec)
        return results

    def search_market_prices(
        self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Best sell prices for a commodity, filtered to radius_ly and joined
        against station_info for a confirmed landing pad size (from our own
        past visits, if any). Sorted with known pad size preferred over
        unknown, and best price within each tier — never silently
        recommends a destination we can't confirm you can physically dock
        at when a known-pad alternative exists. exclude_market_id skips a
        specific station (e.g. the one you're currently docked at).

        Filters system_coords via a bounding-box JOIN rather than fetching
        every nearby system name into Python first and binding one SQL
        parameter per name — system_coords is galaxy-wide and unbounded
        (fed continuously by the EDDN listener), and a per-name IN(...)
        list once exceeded SQLite's bound-parameter limit in production
        (~36k systems within a 200ly search). Bound-parameter count here
        is now fixed regardless of table size.
        """
        rows = self.db.conn.execute(
            """
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.sell_price, m.demand, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
                   sc.x, sc.y, sc.z
            FROM net.market_prices m
            INNER JOIN system_coords sc ON sc.system_name = m.system_name
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                commodity_name, _market_data_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()

        results = []
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = r["x"], r["y"], r["z"]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist

            # Ground truth from our own visits (if any) beats the EDDN-
            # reported stationType; both beat "?".
            pad = effective_pad_size(
                rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
            )
            rec["pad_known"] = pad != "?"
            rec["pad_size"] = pad

            results.append(rec)

        # Known pad size first, then best price within each tier.
        results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
        return results

    def search_market_prices_multi(
        self, commodity_names: list[str], x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
    ) -> dict[str, list[dict]]:
        """
        Same as search_market_prices, but for many commodities in a single
        query — used by Trade Opportunities, which otherwise ran one
        search_market_prices call per purchasable commodity at a station
        (confirmed live: 100+ commodities x ~1s+ each made it take minutes).
        Returns {commodity_name: [results sorted best-first]}, same shape
        per-commodity as search_market_prices.

        Filters system_coords via a bounding-box JOIN — see search_market_prices
        for why (bound-parameter count independent of table size).
        """
        if not commodity_names:
            return {}

        commodity_placeholders = ",".join("?" for _ in commodity_names)
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.commodity_name, m.sell_price, m.demand, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large,
                   sc.x, sc.y, sc.z
            FROM net.market_prices m
            INNER JOIN system_coords sc ON sc.system_name = m.system_name
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name IN ({commodity_placeholders}) AND m.sell_price IS NOT NULL
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                *commodity_names, _market_data_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()

        by_commodity: dict[str, list[dict]] = {name: [] for name in commodity_names}
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = r["x"], r["y"], r["z"]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist
            pad = effective_pad_size(
                rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
            )
            rec["pad_known"] = pad != "?"
            rec["pad_size"] = pad
            by_commodity[rec["commodity_name"]].append(rec)

        for name, results in by_commodity.items():
            results.sort(key=lambda r: (not r["pad_known"], -r["sell_price"]))
        return by_commodity

    def search_fleet_carrier_materials(
        self, material_symbols: list[str], x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
        always_include_market_ids: Optional[set] = None,
    ) -> dict[str, list[dict]]:
        """
        For each symbol in material_symbols, the nearby Fleet Carriers
        currently selling it, closest first. A carrier only appears if we
        have a station_info row for its market_id (from a Docked sighting,
        ours or another commander's via EDDN) -- fcmaterials_journal itself
        carries no location, so this INNER JOIN is the only way to place a
        carrier at all; one with no such row is silently excluded, never
        shown with an unknown location.

        Filters system_coords via a bounding-box JOIN — see search_market_prices
        for why (bound-parameter count independent of table size; this was
        the function that actually crashed in production with "too many
        SQL variables" once system_coords passed ~33k systems in-radius).
        """
        if not material_symbols:
            return {}

        sym_placeholders = ",".join("?" for _ in material_symbols)
        always_include = [mid for mid in (always_include_market_ids or set()) if isinstance(mid, int)]
        access_ok_clause = "(si.carrier_docking_access IS NULL OR si.carrier_docking_access = 'all')"
        if always_include:
            access_ok_clause = f"({access_ok_clause} OR si.market_id IN ({','.join('?' for _ in always_include)}))"
        rows = self.db.conn.execute(
            f"""
            SELECT fcm.material_symbol, fcm.carrier_name, fcm.carrier_id, fcm.price,
                   fcm.stock, fcm.demand, fcm.last_updated,
                   si.market_id, si.system_name, si.last_visited,
                   si.carrier_docking_access AS docking_access,
                   sc.x, sc.y, sc.z
            FROM net.fleet_carrier_materials fcm
            INNER JOIN net.station_info si ON si.market_id = fcm.market_id
            INNER JOIN system_coords sc ON sc.system_name = si.system_name
            WHERE fcm.material_symbol IN ({sym_placeholders})
                  AND fcm.stock > 0
                  AND fcm.last_updated >= ?
                  AND {access_ok_clause}
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                *material_symbols, _fleet_carrier_cutoff(),
                *always_include,
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()

        by_symbol: dict[str, list[dict]] = {sym: [] for sym in material_symbols}
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = r["x"], r["y"], r["z"]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist
            by_symbol[r["material_symbol"]].append(rec)

        for sym in by_symbol:
            by_symbol[sym].sort(key=lambda r: r["distance_ly"])
        return by_symbol

    def search_market_buy_prices(
        self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Cheapest buy prices for a commodity — the mirror of
        search_market_prices, sorted ascending instead of descending, and
        requiring stock > 0 since a listed buy_price with nothing in stock
        isn't actually purchasable.

        Filters system_coords via a bounding-box JOIN — see search_market_prices
        for why (bound-parameter count independent of table size).
        """
        rows = self.db.conn.execute(
            """
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.buy_price, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
                   sc.x, sc.y, sc.z
            FROM net.market_prices m
            INNER JOIN system_coords sc ON sc.system_name = m.system_name
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name = ? AND m.buy_price IS NOT NULL AND m.buy_price > 0
                  AND m.stock IS NOT NULL AND m.stock > 0
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                commodity_name, _market_data_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()

        results = []
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = r["x"], r["y"], r["z"]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist

            pad = effective_pad_size(
                rec["station_type"], rec.get("pads_small"), rec.get("pads_medium"), rec.get("pads_large")
            )
            rec["pad_known"] = pad != "?"
            rec["pad_size"] = pad

            results.append(rec)

        # Known pad size first, then cheapest price within each tier.
        results.sort(key=lambda r: (not r["pad_known"], r["buy_price"]))
        return results

    def get_market_snapshot_in_radius(self, x: float, y: float, z: float, radius_ly: float) -> dict[int, dict]:
        """
        Every station's full buy/sell commodity list within radius_ly, in
        one query — for the Trade Route Loop Planner, which needs to pair
        stations up (does A sell what B buys, and vice versa) rather than
        look up one commodity at a time. One query beats N here for the
        same reason search_market_prices_multi beat looping
        search_market_prices per commodity for Trade Opportunities.

        Returns {market_id: {"station_name", "system_name", "pad_size",
        "controlling_faction", "x", "y", "z", "distance_ly",
        "sells": {commodity: (sell_price, demand, last_updated)},
        "buys": {commodity: (buy_price, stock, last_updated)}}} — station
        metadata repeated per row collapses to one entry per market_id.
        last_updated (ISO timestamp string) lets callers judge/warn on
        crowdsourced-data staleness per commodity, not just per station.

        Filters system_coords via a bounding-box JOIN — see search_market_prices
        for why (bound-parameter count independent of table size).
        """
        rows = self.db.conn.execute(
            """
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.commodity_name, m.sell_price, m.demand, m.buy_price, m.stock,
                   m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large, si.station_faction,
                   sc.x, sc.y, sc.z
            FROM net.market_prices m
            INNER JOIN system_coords sc ON sc.system_name = m.system_name
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE (m.sell_price IS NOT NULL
                     OR (m.buy_price IS NOT NULL AND m.buy_price > 0 AND m.stock IS NOT NULL AND m.stock > 0))
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND sc.x BETWEEN ? AND ? AND sc.y BETWEEN ? AND ? AND sc.z BETWEEN ? AND ?
            """,
            (
                _market_data_cutoff(),
                x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly,
            ),
        ).fetchall()

        stations: dict[int, dict] = {}
        for r in rows:
            rx, ry, rz = r["x"], r["y"], r["z"]
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue

            market_id = r["market_id"]
            station = stations.get(market_id)
            if station is None:
                pad = effective_pad_size(
                    r["station_type"], r["pads_small"], r["pads_medium"], r["pads_large"]
                )
                station = {
                    "station_name": r["station_name"],
                    "system_name": r["system_name"],
                    "pad_size": pad,
                    "controlling_faction": r["station_faction"],
                    "x": rx, "y": ry, "z": rz,
                    "distance_ly": dist,
                    "sells": {}, "buys": {},
                }
                stations[market_id] = station

            commodity = r["commodity_name"]
            if r["sell_price"] is not None:
                station["sells"][commodity] = (r["sell_price"], r["demand"], r["last_updated"])
            # stock > 0 required — a listed buy_price with nothing in
            # stock isn't actually purchasable (confirmed live: a
            # recommended return-leg commodity wasn't actually available
            # at the station, since this check was missing here, unlike
            # the equivalent check already in search_market_buy_prices).
            if r["buy_price"] is not None and r["buy_price"] > 0 and r["stock"] is not None and r["stock"] > 0:
                station["buys"][commodity] = (r["buy_price"], r["stock"], r["last_updated"])

        return stations

    def get_market_snapshot_for_systems(self, system_names: list[str]) -> dict[int, dict]:
        """
        Same per-station shape as get_market_snapshot_in_radius(), but
        filtered to an exact list of system names instead of radius+
        distance -- for the Point-to-Point trade finder, which already
        knows exactly which system it wants (the destination), not "give
        me everything nearby". No x/y/z/distance_ly in the output since
        there's no reference point to measure distance from here.

        Returns {market_id: {"station_name", "system_name", "pad_size",
        "controlling_faction", "sells": {commodity: (sell_price, demand,
        last_updated)}, "buys": {commodity: (buy_price, stock,
        last_updated)}}}.
        """
        if not system_names:
            return {}

        placeholders = ",".join("?" for _ in system_names)
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.commodity_name, m.sell_price, m.demand, m.buy_price, m.stock,
                   m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large, si.station_faction
            FROM net.market_prices m
            LEFT JOIN net.station_info si ON si.market_id = m.market_id
            WHERE (m.sell_price IS NOT NULL
                     OR (m.buy_price IS NOT NULL AND m.buy_price > 0 AND m.stock IS NOT NULL AND m.stock > 0))
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND m.system_name IN ({placeholders})
            """,
            (_market_data_cutoff(), *system_names),
        ).fetchall()

        stations: dict[int, dict] = {}
        for r in rows:
            market_id = r["market_id"]
            station = stations.get(market_id)
            if station is None:
                pad = effective_pad_size(
                    r["station_type"], r["pads_small"], r["pads_medium"], r["pads_large"]
                )
                station = {
                    "station_name": r["station_name"],
                    "system_name": r["system_name"],
                    "pad_size": pad,
                    "controlling_faction": r["station_faction"],
                    "sells": {}, "buys": {},
                }
                stations[market_id] = station

            commodity = r["commodity_name"]
            if r["sell_price"] is not None:
                station["sells"][commodity] = (r["sell_price"], r["demand"], r["last_updated"])
            if r["buy_price"] is not None and r["buy_price"] > 0 and r["stock"] is not None and r["stock"] > 0:
                station["buys"][commodity] = (r["buy_price"], r["stock"], r["last_updated"])

        return stations

    def resolve_system_name_case_insensitive(self, name: str) -> Optional[str]:
        """Resolves a user-typed system name to its exact stored casing,
        via the much smaller system_coords table rather than a
        case-insensitive scan of market_prices' 13M+ rows (which would
        bypass its system_name index). Returns None if no match --
        callers should fall back to using the original input as-is in
        that case, not treat it as a hard failure."""
        name = (name or "").strip()
        if not name:
            return None
        row = self.db.conn.execute(
            "SELECT system_name FROM system_coords WHERE LOWER(system_name) = LOWER(?) LIMIT 1",
            (name,),
        ).fetchone()
        return row["system_name"] if row else None

    def add_colonisation_depot_manual(self, system_name: str, station_name: str) -> None:
        """Adds a squadron construction site to track before ever visiting
        it — no market_id yet, since that's only known once you actually
        dock there. No-op if this system+station is already tracked."""
        system_name = (system_name or "").strip()
        station_name = (station_name or "").strip()
        if not system_name or not station_name:
            return
        existing = self.db.conn.execute(
            "SELECT id FROM colonisation_depots WHERE LOWER(system_name) = ? AND LOWER(station_name) = ?",
            (system_name.lower(), station_name.lower()),
        ).fetchone()
        if existing:
            return
        self.db.conn.execute(
            "INSERT INTO colonisation_depots (system_name, station_name, complete) VALUES (?, ?, 0)",
            (system_name, station_name),
        )
        self.db.conn.commit()

    def save_colonisation_depot_visit(
        self, market_id: int, system_address, system_name: str, station_name: str,
        progress, complete: bool, resources_json: str, timestamp: str,
    ) -> None:
        """Upserts real visit data — matches an existing row by market_id
        first (a revisit), then by system+station name for a manually-added
        row not yet visited (fills in the real market_id), else inserts a
        new row (a depot found by visiting, never manually added first)."""
        row = self.db.conn.execute(
            "SELECT id FROM colonisation_depots WHERE market_id = ?", (market_id,)
        ).fetchone()
        if row is None:
            row = self.db.conn.execute(
                "SELECT id FROM colonisation_depots WHERE market_id IS NULL "
                "AND LOWER(system_name) = ? AND LOWER(station_name) = ?",
                (system_name.strip().lower(), station_name.strip().lower()),
            ).fetchone()

        if row is not None:
            self.db.conn.execute(
                """UPDATE colonisation_depots SET
                       market_id = ?, system_address = ?, system_name = ?, station_name = ?,
                       progress = ?, complete = ?, resources = ?, last_updated = ?
                   WHERE id = ?""",
                (market_id, system_address, system_name, station_name,
                 progress, int(bool(complete)), resources_json, timestamp, row["id"]),
            )
        else:
            self.db.conn.execute(
                """INSERT INTO colonisation_depots
                       (market_id, system_address, system_name, station_name,
                        progress, complete, resources, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (market_id, system_address, system_name, station_name,
                 progress, int(bool(complete)), resources_json, timestamp),
            )
        self.db.conn.commit()

    def find_closest_trailblazer(self, x: float, y: float, z: float) -> Optional[dict]:
        """
        Closest known "Trailblazer" megaship (Brewer Corporation's fixed
        colonisation-materials supply ships — confirmed real via GalNet,
        not a guess) to (x, y, z). Best-effort only: these reportedly move
        occasionally and EDDN coverage of them is patchy (not every
        sighting gets reported), so this is whatever we happen to have on
        file, not a guaranteed-current location. Filters on station_type
        == 'MegaShip' too, since a player-named station can coincidentally
        contain "Trailblazer" without being one (confirmed live: "Harbard's
        Trailblazer Supplys", an ordinary Coriolis station).
        """
        rows = self.db.conn.execute(
            """
            SELECT DISTINCT si.station_name, si.system_name, sc.x, sc.y, sc.z
            FROM net.station_info si
            JOIN system_coords sc ON sc.system_name = si.system_name
            WHERE si.station_name LIKE 'Trailblazer %' AND si.station_type = 'MegaShip'
            """
        ).fetchall()
        if not rows:
            return None

        best = None
        best_dist = None
        for r in rows:
            dist = ((r["x"] - x) ** 2 + (r["y"] - y) ** 2 + (r["z"] - z) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = {"station_name": r["station_name"], "system_name": r["system_name"], "distance_ly": dist}
        return best

    def get_colonisation_depots(self) -> list[dict]:
        rows = self.db.conn.execute(
            "SELECT * FROM colonisation_depots ORDER BY system_name, station_name"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["resources"] = json.loads(d["resources"]) if d.get("resources") else []
            except Exception:
                d["resources"] = []
            out.append(d)
        return out

    def remove_colonisation_depot(self, depot_id: int) -> None:
        self.db.conn.execute("DELETE FROM colonisation_depots WHERE id = ?", (depot_id,))
        self.db.conn.commit()

    def get_faction_history(self, system_address: int, faction_name: Optional[str] = None) -> list[dict]:
        query = """
            SELECT faction_name, snapshot_date, influence, government, allegiance,
                   faction_state, happiness, active_states, pending_states,
                   recovering_states, is_controlling
            FROM faction_snapshots
            WHERE system_address = ?
        """
        params: tuple = (system_address,)
        if faction_name:
            query += " AND faction_name = ?"
            params += (faction_name,)
        query += " ORDER BY snapshot_date DESC, faction_name ASC"
        rows = self.db.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_odyssey_farming_candidates(self, limit: int = 20) -> list[dict]:
        """
        Odyssey on-foot farming candidates: systems whose most recent
        controlling-faction snapshot shows Anarchy government (no local
        law -- safe to loot without a crime/bounty consequence) or a BGS
        state associated with settlement farming opportunities (War/Civil
        War, Pirate Attack, Civil Unrest, Infrastructure Failure).
        Advisory only -- underlying data can be stale, so results are
        ordered freshest data_timestamp first.
        """
        rows = self.db.execute(
            """
            SELECT fs.system_address, s.system_name, fs.government,
                   fs.faction_state, fs.active_states, fs.data_timestamp
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            WHERE fs.is_controlling = 1
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.is_controlling = 1
              )
            """
        ).fetchall()

        candidates = []
        for row in rows:
            r = dict(row)
            signals: List[str] = []

            government = (r.get("government") or "").strip().lower()
            if government == "anarchy":
                signals.append("Anarchy")

            active = {s.lower() for s in _parse_states(r.get("active_states"))}
            faction_state = (r.get("faction_state") or "").strip().lower()
            if faction_state:
                active.add(faction_state)

            if active & {"war", "civilwar"}:
                signals.append("War")
            if "pirateattack" in active:
                signals.append("Pirate Attack")
            if "civilunrest" in active:
                signals.append("Civil Unrest")
            if "infrastructurefailure" in active:
                signals.append("Infrastructure Failure")

            if not signals:
                continue

            candidates.append({
                "system_name": r.get("system_name") or "(unknown system)",
                "matched_signals": signals,
                "data_timestamp": r.get("data_timestamp"),
            })

        # Drop anything we can't bound the age of, or that's aged past the
        # 30-day advisory window (faction_snapshots' own retention delete
        # only prunes on next write for that system+faction, so a system
        # nobody's revisited can otherwise sit here indefinitely).
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        candidates = [c for c in candidates if c["data_timestamp"] and c["data_timestamp"] >= cutoff]

        # BGS-state matches (War/Pirate Attack/Civil Unrest/Infrastructure
        # Failure) are the rare, actionable signal this feature exists for;
        # bare Anarchy is bulk/low-value noise by comparison. Rank state
        # matches first, freshest-first within each tier.
        candidates.sort(
            key=lambda c: (bool(set(c["matched_signals"]) - {"Anarchy"}), c["data_timestamp"] or ""),
            reverse=True,
        )
        return candidates[:limit]

    def get_controlling_faction_snapshots_with_coords(self) -> list[dict]:
        """
        Every system's controlling faction's most recent snapshot, joined
        to its known coordinates -- raw data only, no guide-matching logic
        (that belongs in the UI layer -- see _parse_states()'s docstring
        for why persistence must not depend on it). Systems with no
        system_coords row are excluded, since distance can't be computed
        without one.
        """
        rows = self.db.execute(
            """
            SELECT s.system_name, fs.government, fs.allegiance,
                   fs.faction_state, fs.active_states,
                   sc.x, sc.y, sc.z
            FROM faction_snapshots fs
            LEFT JOIN systems s ON s.system_address = fs.system_address
            INNER JOIN system_coords sc ON sc.system_name = s.system_name
            WHERE fs.is_controlling = 1
              AND fs.snapshot_date = (
                  SELECT MAX(snapshot_date) FROM faction_snapshots fs2
                  WHERE fs2.system_address = fs.system_address
                    AND fs2.is_controlling = 1
              )
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_codex_entries(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value, is_phenomena
            FROM codex_entries
            WHERE system_address = ?
            ORDER BY body_id, genus
            """,
            (system_address,),
        ).fetchall()

    def mark_journal_processed(
        self,
        file_name: str,
        file_size: int,
        processed_at: str,
    ):
        self.db.execute(
            """
            INSERT INTO processed_journals (
                file_name,
                file_size,
                processed_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(file_name, file_size) DO UPDATE SET
                processed_at = excluded.processed_at
            """,
            (
                file_name,
                file_size,
                processed_at,
            ),
        )

    def journal_processed(self, file_name: str, file_size: int) -> bool:
        row = self.db.execute(
            """
            SELECT 1
            FROM processed_journals
            WHERE file_name = ? AND file_size = ?
            """,
            (
                file_name,
                file_size,
            ),
        ).fetchone()
        return row is not None

    def get_system_details(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                first_visit,
                last_visit,
                visit_count
            FROM systems
            WHERE system_address = ?
            """,
            (system_address,),
        ).fetchone()

    def get_system(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                system_name,
                body_count,
                fss_complete,
                first_visit,
                last_visit,
                visit_count,
                first_discovery
            FROM systems
            WHERE system_address = ?
            """,
            (system_address,),
        ).fetchone()

    def get_all_visited_system_names(self) -> list[str]:
        """Every system name ever recorded in `systems` (personally
        visited, from journal history) -- used to cross-reference against
        Frontier's PowerPlay feed for the PowerPlay System Status tab's
        "visited PP-active systems" section."""
        rows = self.db.conn.execute(
            "SELECT system_name FROM systems WHERE system_name IS NOT NULL"
        ).fetchall()
        return [r["system_name"] for r in rows]

    def get_most_recent_system(self):
        return self.db.execute(
            """
            SELECT
                system_address,
                system_name,
                body_count,
                fss_complete,
                first_visit,
                last_visit,
                visit_count
            FROM systems
            ORDER BY
                last_visit IS NULL,
                last_visit DESC,
                first_visit DESC
            LIMIT 1
            """
        ).fetchone()

    def get_bodies(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_id,
                body_name,
                planet_class,
                terraformable,
                landable,
                was_mapped,
                dss_mapped,
                was_footfalled,
                estimated_value,
                distance_ls,
                volcanism,
                materials,
                first_footfall,
                has_footfall,
                mass_em,
                radius,
                surface_gravity,
                surface_temperature,
                surface_pressure,
                atmosphere_type,
                atmosphere,
                atmosphere_composition,
                composition,
                tidal_lock,
                first_discovered,
                first_mapped
            FROM bodies
            WHERE system_address = ?
            ORDER BY distance_ls IS NULL, distance_ls, body_name
            """,
            (system_address,),
        ).fetchall()

    def get_body_signals(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_name,
                bio_signals,
                geo_signals,
                human_signals,
                surface_mining_signals
            FROM body_signals
            WHERE system_address = ?
            ORDER BY body_name
            """,
            (system_address,),
        ).fetchall()

    def save_spansh_body(
        self,
        system_address: int,
        body_name: str,
        planet_class: str | None,
        distance_ls: float | None,
        estimated_value: int | None,
        landable: int | None,
        surface_gravity: float | None = None,
        radius: float | None = None,
        mass_em: float | None = None,
        surface_temperature: float | None = None,
        surface_pressure: float | None = None,
        atmosphere_type: str | None = None,
        volcanism: str | None = None,
        tidal_lock: int | None = None,
        was_mapped: int | None = None,
        updated_at: str | None = None,
    ):
        self.db.execute(
            """
            INSERT INTO net.spansh_bodies (
                system_address, body_name, planet_class, distance_ls, estimated_value, landable,
                surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                atmosphere_type, volcanism, tidal_lock, was_mapped, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name) DO UPDATE SET
                planet_class        = excluded.planet_class,
                distance_ls         = excluded.distance_ls,
                estimated_value     = excluded.estimated_value,
                landable            = excluded.landable,
                surface_gravity     = COALESCE(excluded.surface_gravity,     net.spansh_bodies.surface_gravity),
                radius              = COALESCE(excluded.radius,              net.spansh_bodies.radius),
                mass_em             = COALESCE(excluded.mass_em,             net.spansh_bodies.mass_em),
                surface_temperature = COALESCE(excluded.surface_temperature, net.spansh_bodies.surface_temperature),
                surface_pressure    = COALESCE(excluded.surface_pressure,    net.spansh_bodies.surface_pressure),
                atmosphere_type     = COALESCE(excluded.atmosphere_type,     net.spansh_bodies.atmosphere_type),
                volcanism           = COALESCE(excluded.volcanism,           net.spansh_bodies.volcanism),
                tidal_lock          = COALESCE(excluded.tidal_lock,          net.spansh_bodies.tidal_lock),
                was_mapped          = COALESCE(excluded.was_mapped,          net.spansh_bodies.was_mapped),
                updated_at          = COALESCE(excluded.updated_at,          net.spansh_bodies.updated_at)
            """,
            (
                system_address, body_name, planet_class, distance_ls, estimated_value, landable,
                surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                atmosphere_type, volcanism, tidal_lock, was_mapped, updated_at,
            ),
        )

    def get_spansh_bodies(self, system_address: int):
        return self.db.execute(
            """
            SELECT body_name, planet_class, distance_ls, estimated_value, landable,
                   surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                   atmosphere_type, volcanism, tidal_lock, was_mapped, updated_at
            FROM net.spansh_bodies
            WHERE system_address = ?
            ORDER BY distance_ls IS NULL, distance_ls, body_name
            """,
            (system_address,),
        ).fetchall()

    def count_spansh_bodies(self, system_address: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS cnt FROM net.spansh_bodies WHERE system_address = ?",
            (system_address,),
        ).fetchone()
        return int(row["cnt"] or 0) if row else 0

    def count_real_bodies(self, system_address: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS cnt FROM bodies WHERE system_address = ?",
            (system_address,),
        ).fetchone()
        return int(row["cnt"] or 0) if row else 0

    def get_real_body_names(self, system_address: int) -> set:
        rows = self.db.execute(
            "SELECT body_name FROM bodies WHERE system_address = ?",
            (system_address,),
        ).fetchall()
        return {r["body_name"] for r in rows if r["body_name"]}

    def get_exobiology(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address,
                body_name,
                genus,
                species,
                variant,
                samples
            FROM exobiology
            WHERE system_address = ?
            ORDER BY body_name, genus, species, variant
            """,
            (system_address,),
        ).fetchall()