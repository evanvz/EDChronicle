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
    ):
        self.db.execute(
            """
            INSERT INTO bodies (
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
                materials
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                body_name       = excluded.body_name,
                planet_class    = excluded.planet_class,
                terraformable   = excluded.terraformable,
                landable        = excluded.landable,
                was_mapped      = excluded.was_mapped,
                dss_mapped      = excluded.dss_mapped,
                estimated_value = excluded.estimated_value,
                distance_ls     = excluded.distance_ls,
                volcanism       = COALESCE(excluded.volcanism, bodies.volcanism),
                materials       = COALESCE(excluded.materials, bodies.materials)
            """,
            (
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
            ),
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
                materials
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