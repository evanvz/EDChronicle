import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from .database import Database
from edc.core.station_pads import effective_pad_size

# A commodity price this old is excluded from buy/sell search results
# entirely — a BGS state change (war outcome, boom/bust, faction takeover)
# or a station nobody's visited in a while can make it flatly wrong, and
# unlike a Fleet Carrier's arbitrary price this isn't visible as an obvious
# outlier, so it's safer to disallow it than merely flag it.
_MARKET_DATA_MAX_AGE_DAYS = 30


def _market_data_cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=_MARKET_DATA_MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    ):
        self.db.execute(
            """
            INSERT INTO bodies (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                first_mapped            = COALESCE(excluded.first_mapped, bodies.first_mapped)
            """,
            (
                system_address, body_id, body_name, planet_class, terraformable,
                landable, was_mapped, dss_mapped, estimated_value, distance_ls,
                volcanism, materials, mass_em, radius, surface_gravity,
                surface_temperature, surface_pressure, atmosphere_type, atmosphere,
                atmosphere_composition, composition, tidal_lock, first_discovered,
                first_mapped,
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
    ):
        self.db.execute(
            """
            INSERT INTO body_signals (
                system_address,
                body_name,
                bio_signals,
                geo_signals,
                human_signals
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name) DO UPDATE SET
                bio_signals = excluded.bio_signals,
                geo_signals = excluded.geo_signals,
                human_signals = excluded.human_signals
            """,
            (
                system_address,
                body_name,
                bio_signals,
                geo_signals,
                human_signals,
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
    ):
        self.db.execute(
            """
            INSERT INTO codex_entries (
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id, genus) DO UPDATE SET
                species        = excluded.species,
                variant        = excluded.variant,
                codex_entry_id = excluded.codex_entry_id,
                codex_name     = excluded.codex_name,
                base_value     = excluded.base_value
            """,
            (
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value,
            ),
        )

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

    def save_faction_snapshot(
        self,
        system_address: int,
        faction: dict,
        snapshot_date: str,
        is_controlling: bool,
    ):
        name = faction.get("Name")
        if not isinstance(name, str) or not name:
            return

        influence = faction.get("Influence")
        my_reputation = faction.get("MyReputation")
        is_squadron_faction = faction.get("SquadronFaction") is True
        self.db.execute(
            """
            INSERT INTO faction_snapshots (
                system_address, faction_name, snapshot_date,
                influence, government, allegiance, faction_state, happiness,
                active_states, pending_states, recovering_states, is_controlling,
                my_reputation, is_squadron_faction
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                is_squadron_faction = excluded.is_squadron_faction
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
            ),
        )

    def get_player_faction_overview(self) -> Optional[dict]:
        """
        Detects the player's squadron-aligned minor faction (if any, from
        SquadronFaction:true in the journal) and returns its most recent
        recorded status in every system it's ever been seen in — not just
        the current system. Returns None if no squadron faction has ever
        been recorded.
        """
        row = self.db.conn.execute(
            """
            SELECT faction_name FROM faction_snapshots
            WHERE is_squadron_faction = 1
            ORDER BY snapshot_date DESC
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
          conflict_risk (None or {"faction_name", "influence", "diff"})

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

            out.append({
                "system_address": system_address,
                "system_name": system_name,
                "influence": our_influence,
                "trend": trend,
                "days_in_expansion_range": days_in_expansion_range,
                "days_in_retreat_range": days_in_retreat_range,
                "conflict_risk": conflict_risk,
            })
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
            INSERT INTO market_prices (
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
            INSERT INTO commodity_names (internal_name, display_name)
            VALUES (?, ?)
            ON CONFLICT(internal_name) DO UPDATE SET display_name = excluded.display_name
            """,
            pairs,
        )
        self.db.conn.commit()

    def get_all_commodity_display_names(self) -> list[str]:
        rows = self.db.conn.execute(
            "SELECT DISTINCT display_name FROM commodity_names ORDER BY display_name"
        ).fetchall()
        return [r["display_name"] for r in rows]

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
            INSERT INTO station_info (
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
                r.get("station_faction"),
            )
            for r in records
        ]
        cur = self.db.conn.cursor()
        cur.executemany(
            """
            INSERT INTO station_info (
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
            rows,
        )
        self.db.conn.commit()

    def find_closest_interstellar_factors(
        self, x: float, y: float, z: float, exclude_factions: Optional[list[str]] = None,
    ) -> Optional[dict]:
        """
        Closest known station (from our own past Docked visits) confirmed to
        offer Interstellar Factors ("Facilitator" in StationServices), whose
        controlling faction is not one of exclude_factions — a bounty can't
        be cleared at a station owned by the faction that issued it.
        Distance computed in Python against system_coords, same pattern as
        search_market_prices — dataset is bounded to stations we've visited.

        Interstellar Factors presence is BGS-driven (only spawns in Low
        Security/Anarchy stations, and disappears if the system's security
        or controlling faction changes), so this is only as fresh as our
        last recorded visit — last_visited is returned so the caller can
        surface that caveat rather than presenting it as guaranteed-current.
        """
        excluded = {f.strip().lower() for f in (exclude_factions or []) if f}

        rows = self.db.conn.execute(
            """
            SELECT si.market_id, si.station_name, si.system_name, si.station_faction,
                   si.station_type, si.pads_small, si.pads_medium, si.pads_large,
                   si.last_visited, c.x, c.y, c.z
            FROM station_info si
            JOIN system_coords c ON c.system_name = si.system_name
            WHERE si.station_services LIKE '%Facilitator%'
            """
        ).fetchall()

        best = None
        best_dist = None
        for r in rows:
            faction = (r["station_faction"] or "").strip().lower()
            if faction and faction in excluded:
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
            FROM station_info si
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
            f"FROM station_info WHERE market_id IN ({placeholders})",
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
            FROM station_info
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
            FROM station_info si
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
            FROM market_prices m
            LEFT JOIN system_coords c ON c.system_name = m.system_name
            LEFT JOIN station_info si ON si.market_id = m.market_id
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

    def _nearby_system_coords(self, x: float, y: float, z: float, radius_ly: float) -> dict:
        """
        Pre-filters system_coords to a bounding cube around (x,y,z) — cheap,
        since system_coords has one row per system, not per station/commodity.
        Used to avoid market_prices' commodity_name index returning every
        station in the galaxy that ever sold a commodity (confirmed live:
        1.5-7.5s per commodity for a common one like Gold/Tritium — a
        station with 100+ commodities made Trade Opportunities take minutes)
        before most of those rows get thrown away for being out of range.
        Returns {system_name: (x, y, z)}; the cube is a loose superset of
        the sphere, so callers still need their own exact distance check.
        """
        rows = self.db.conn.execute(
            "SELECT system_name, x, y, z FROM system_coords "
            "WHERE x BETWEEN ? AND ? AND y BETWEEN ? AND ? AND z BETWEEN ? AND ?",
            (x - radius_ly, x + radius_ly, y - radius_ly, y + radius_ly, z - radius_ly, z + radius_ly),
        ).fetchall()
        return {r["system_name"]: (r["x"], r["y"], r["z"]) for r in rows}

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
        """
        coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
        if not coords_by_system:
            return []

        placeholders = ",".join("?" for _ in coords_by_system)
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.sell_price, m.demand, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large
            FROM market_prices m
            LEFT JOIN station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND m.system_name IN ({placeholders})
            """,
            (commodity_name, _market_data_cutoff(), *coords_by_system.keys()),
        ).fetchall()

        results = []
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = coords_by_system[r["system_name"]]
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
        """
        if not commodity_names:
            return {}

        coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
        if not coords_by_system:
            return {name: [] for name in commodity_names}

        sys_placeholders = ",".join("?" for _ in coords_by_system)
        commodity_placeholders = ",".join("?" for _ in commodity_names)
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.commodity_name, m.sell_price, m.demand, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large
            FROM market_prices m
            LEFT JOIN station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name IN ({commodity_placeholders}) AND m.sell_price IS NOT NULL
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND m.system_name IN ({sys_placeholders})
            """,
            (*commodity_names, _market_data_cutoff(), *coords_by_system.keys()),
        ).fetchall()

        by_commodity: dict[str, list[dict]] = {name: [] for name in commodity_names}
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = coords_by_system[r["system_name"]]
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

    def search_market_buy_prices(
        self, commodity_name: str, x: float, y: float, z: float, radius_ly: float,
        exclude_market_id: Optional[int] = None,
    ) -> list[dict]:
        """
        Cheapest buy prices for a commodity — the mirror of
        search_market_prices, sorted ascending instead of descending, and
        requiring stock > 0 since a listed buy_price with nothing in stock
        isn't actually purchasable.
        """
        coords_by_system = self._nearby_system_coords(x, y, z, radius_ly)
        if not coords_by_system:
            return []

        placeholders = ",".join("?" for _ in coords_by_system)
        rows = self.db.conn.execute(
            f"""
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.buy_price, m.stock, m.last_updated,
                   si.pads_small, si.pads_medium, si.pads_large
            FROM market_prices m
            LEFT JOIN station_info si ON si.market_id = m.market_id
            WHERE m.commodity_name = ? AND m.buy_price IS NOT NULL AND m.buy_price > 0
                  AND m.stock IS NOT NULL AND m.stock > 0
                  AND (m.station_type IS NULL OR m.station_type != 'FleetCarrier')
                  AND m.last_updated >= ?
                  AND m.system_name IN ({placeholders})
            """,
            (commodity_name, _market_data_cutoff(), *coords_by_system.keys()),
        ).fetchall()

        results = []
        for r in rows:
            if exclude_market_id is not None and r["market_id"] == exclude_market_id:
                continue
            rx, ry, rz = coords_by_system[r["system_name"]]
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

    def get_faction_history(self, system_address: int) -> list[dict]:
        rows = self.db.execute(
            """
            SELECT faction_name, snapshot_date, influence, government, allegiance,
                   faction_state, happiness, active_states, pending_states,
                   recovering_states, is_controlling
            FROM faction_snapshots
            WHERE system_address = ?
            ORDER BY snapshot_date DESC, faction_name ASC
            """,
            (system_address,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_codex_entries(self, system_address: int):
        return self.db.execute(
            """
            SELECT
                system_address, body_id, genus, species,
                variant, codex_entry_id, codex_name, base_value
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
                visit_count
            FROM systems
            WHERE system_address = ?
            """,
            (system_address,),
        ).fetchone()

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
                human_signals
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
    ):
        self.db.execute(
            """
            INSERT INTO spansh_bodies (
                system_address, body_name, planet_class, distance_ls, estimated_value, landable,
                surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                atmosphere_type, volcanism, tidal_lock
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name) DO UPDATE SET
                planet_class        = excluded.planet_class,
                distance_ls         = excluded.distance_ls,
                estimated_value     = excluded.estimated_value,
                landable            = excluded.landable,
                surface_gravity     = COALESCE(excluded.surface_gravity,     spansh_bodies.surface_gravity),
                radius              = COALESCE(excluded.radius,              spansh_bodies.radius),
                mass_em             = COALESCE(excluded.mass_em,             spansh_bodies.mass_em),
                surface_temperature = COALESCE(excluded.surface_temperature, spansh_bodies.surface_temperature),
                surface_pressure    = COALESCE(excluded.surface_pressure,    spansh_bodies.surface_pressure),
                atmosphere_type     = COALESCE(excluded.atmosphere_type,     spansh_bodies.atmosphere_type),
                volcanism           = COALESCE(excluded.volcanism,           spansh_bodies.volcanism),
                tidal_lock          = COALESCE(excluded.tidal_lock,          spansh_bodies.tidal_lock)
            """,
            (
                system_address, body_name, planet_class, distance_ls, estimated_value, landable,
                surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                atmosphere_type, volcanism, tidal_lock,
            ),
        )

    def get_spansh_bodies(self, system_address: int):
        return self.db.execute(
            """
            SELECT body_name, planet_class, distance_ls, estimated_value, landable,
                   surface_gravity, radius, mass_em, surface_temperature, surface_pressure,
                   atmosphere_type, volcanism, tidal_lock
            FROM spansh_bodies
            WHERE system_address = ?
            ORDER BY distance_ls IS NULL, distance_ls, body_name
            """,
            (system_address,),
        ).fetchall()

    def count_spansh_bodies(self, system_address: int) -> int:
        row = self.db.execute(
            "SELECT COUNT(*) AS cnt FROM spansh_bodies WHERE system_address = ?",
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