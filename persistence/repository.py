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
        body_name: str | None,
        planet_class: str | None,
        terraformable: int | None,
        landable: int | None,
        mapped: int | None,
        estimated_value: int | None,
        distance_ls: float | None,
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
                mapped,
                estimated_value,
                distance_ls
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_id) DO UPDATE SET
                body_name = excluded.body_name,
                planet_class = excluded.planet_class,
                terraformable = excluded.terraformable,
                landable = excluded.landable,
                mapped = excluded.mapped,
                estimated_value = excluded.estimated_value,
                distance_ls = excluded.distance_ls
            """,
            (
                system_address,
                body_id,
                body_name,
                planet_class,
                terraformable,
                landable,
                mapped,
                estimated_value,
                distance_ls,
            ),
        )

    def save_body_signals(
        self,
        system_address: int,
        body_name: str,
        bio_signals: int | None,
        geo_signals: int | None,
    ):
        self.db.execute(
            """
            INSERT INTO body_signals (
                system_address,
                body_name,
                bio_signals,
                geo_signals
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(system_address, body_name) DO UPDATE SET
                bio_signals = excluded.bio_signals,
                geo_signals = excluded.geo_signals
            """,
            (
                system_address,
                body_name,
                bio_signals,
                geo_signals,
            ),
        )

    def save_exobiology(
        self,
        system_address: int,
        body_name: str,
        genus: str,
        species: str,
        samples: int | None,
    ):
        self.db.execute(
            """
            INSERT INTO exobiology (
                system_address,
                body_name,
                genus,
                species,
                samples
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(system_address, body_name, genus, species) DO UPDATE SET
                samples = excluded.samples
            """,
            (
                system_address,
                body_name,
                genus,
                species,
                samples,
            ),
        )

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