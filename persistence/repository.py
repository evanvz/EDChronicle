import json

from .database import Database


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
        self.db.execute(
            """
            INSERT INTO faction_snapshots (
                system_address, faction_name, snapshot_date,
                influence, government, allegiance, faction_state, happiness,
                active_states, pending_states, recovering_states, is_controlling
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, faction_name, snapshot_date) DO UPDATE SET
                influence         = excluded.influence,
                government        = excluded.government,
                allegiance        = excluded.allegiance,
                faction_state     = excluded.faction_state,
                happiness         = excluded.happiness,
                active_states     = excluded.active_states,
                pending_states    = excluded.pending_states,
                recovering_states = excluded.recovering_states,
                is_controlling    = excluded.is_controlling
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
            ),
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

    def search_market_prices(
        self, commodity_name: str, x: float, y: float, z: float, radius_ly: float
    ) -> list[dict]:
        """
        Best sell prices for a commodity, joined against system_coords for
        distance, filtered to radius_ly, sorted by sell price descending.
        Distance filtering/sorting happens in Python — dataset is bounded
        (one row per station/commodity ever reported), no need for a
        spatial index at this scale.
        """
        rows = self.db.conn.execute(
            """
            SELECT m.market_id, m.station_name, m.station_type, m.system_name,
                   m.sell_price, m.demand, m.stock, m.last_updated,
                   c.x, c.y, c.z
            FROM market_prices m
            JOIN system_coords c ON c.system_name = m.system_name
            WHERE m.commodity_name = ? AND m.sell_price IS NOT NULL
            """,
            (commodity_name,),
        ).fetchall()

        results = []
        for r in rows:
            rx, ry, rz = r["x"], r["y"], r["z"]
            if rx is None or ry is None or rz is None:
                continue
            dist = ((rx - x) ** 2 + (ry - y) ** 2 + (rz - z) ** 2) ** 0.5
            if dist > radius_ly:
                continue
            rec = dict(r)
            rec["distance_ly"] = dist
            results.append(rec)

        results.sort(key=lambda r: r["sell_price"], reverse=True)
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