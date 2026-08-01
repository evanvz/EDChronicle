import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def executescript(self, sql: str):
        self.conn.executescript(sql)
        self.conn.commit()

    def run_migrations(self):
        """Add new columns to existing tables without breaking older DBs."""
        migrations = [
            "ALTER TABLE bodies ADD COLUMN first_footfall INTEGER DEFAULT 0",
            "ALTER TABLE bodies ADD COLUMN has_footfall    INTEGER DEFAULT 0",
            """CREATE TABLE IF NOT EXISTS spansh_bodies (
                system_address  INTEGER NOT NULL,
                body_name       TEXT    NOT NULL,
                planet_class    TEXT,
                distance_ls     REAL,
                estimated_value INTEGER,
                landable        INTEGER,
                PRIMARY KEY (system_address, body_name)
            )""",
            "ALTER TABLE bodies ADD COLUMN mass_em REAL",
            "ALTER TABLE bodies ADD COLUMN radius REAL",
            "ALTER TABLE bodies ADD COLUMN surface_gravity REAL",
            "ALTER TABLE bodies ADD COLUMN surface_temperature REAL",
            "ALTER TABLE bodies ADD COLUMN surface_pressure REAL",
            "ALTER TABLE bodies ADD COLUMN atmosphere_type TEXT",
            "ALTER TABLE bodies ADD COLUMN atmosphere TEXT",
            "ALTER TABLE bodies ADD COLUMN atmosphere_composition TEXT",
            "ALTER TABLE bodies ADD COLUMN composition TEXT",
            "ALTER TABLE bodies ADD COLUMN tidal_lock INTEGER",
            "ALTER TABLE bodies ADD COLUMN first_discovered INTEGER",
            "ALTER TABLE bodies ADD COLUMN first_mapped INTEGER",
            "ALTER TABLE spansh_bodies ADD COLUMN surface_gravity REAL",
            "ALTER TABLE spansh_bodies ADD COLUMN radius REAL",
            "ALTER TABLE spansh_bodies ADD COLUMN mass_em REAL",
            "ALTER TABLE spansh_bodies ADD COLUMN surface_temperature REAL",
            "ALTER TABLE spansh_bodies ADD COLUMN surface_pressure REAL",
            "ALTER TABLE spansh_bodies ADD COLUMN atmosphere_type TEXT",
            "ALTER TABLE spansh_bodies ADD COLUMN volcanism TEXT",
            "ALTER TABLE spansh_bodies ADD COLUMN tidal_lock INTEGER",
            """CREATE TABLE IF NOT EXISTS faction_snapshots (
                system_address    INTEGER NOT NULL,
                faction_name      TEXT    NOT NULL,
                snapshot_date     TEXT    NOT NULL,
                influence         REAL,
                government        TEXT,
                allegiance        TEXT,
                faction_state     TEXT,
                happiness         TEXT,
                active_states     TEXT,
                pending_states    TEXT,
                recovering_states TEXT,
                is_controlling    INTEGER DEFAULT 0,
                PRIMARY KEY (system_address, faction_name, snapshot_date)
            )""",
            """CREATE TABLE IF NOT EXISTS system_coords (
                system_name TEXT PRIMARY KEY,
                x REAL,
                y REAL,
                z REAL,
                last_seen TEXT
            )""",
            "ALTER TABLE faction_snapshots ADD COLUMN my_reputation REAL",
            "ALTER TABLE faction_snapshots ADD COLUMN is_squadron_faction INTEGER DEFAULT 0",
            """CREATE TABLE IF NOT EXISTS station_info (
                market_id     INTEGER PRIMARY KEY,
                station_name  TEXT,
                system_name   TEXT,
                station_type  TEXT,
                pads_small    INTEGER,
                pads_medium   INTEGER,
                pads_large    INTEGER,
                last_visited  TEXT
            )""",
            "ALTER TABLE station_info ADD COLUMN station_services TEXT",
            "ALTER TABLE station_info ADD COLUMN station_faction TEXT",
            """CREATE TABLE IF NOT EXISTS commodity_names (
                internal_name TEXT PRIMARY KEY,
                display_name  TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS market_prices (
                market_id      INTEGER NOT NULL,
                commodity_name TEXT    NOT NULL,
                station_name   TEXT,
                station_type   TEXT,
                system_name    TEXT,
                sell_price     INTEGER,
                buy_price      INTEGER,
                mean_price     INTEGER,
                demand         INTEGER,
                demand_bracket INTEGER,
                stock          INTEGER,
                stock_bracket  INTEGER,
                last_updated   TEXT NOT NULL,
                PRIMARY KEY (market_id, commodity_name)
            )""",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except Exception:
                pass  # column/table already exists

        self._apply_version_migrations()

    # Bump this constant whenever a migration requires journals to be re-imported.
    _REQUIRED_SCHEMA_VERSION = 4

    def _apply_version_migrations(self):
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"
        )
        self.conn.commit()

        row = self.conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
        current = row[0] if row else 0

        if current < self._REQUIRED_SCHEMA_VERSION:
            # v2: body physical-stat columns were added.
            # v3: station_info (landing pad ground truth from Docked events) was added.
            # v4: station_info.station_services/station_faction (Interstellar Factors detection) was added.
            # Re-import all journals to backfill.
            self.conn.execute("DELETE FROM processed_journals")
            if current == 0:
                self.conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (self._REQUIRED_SCHEMA_VERSION,),
                )
            else:
                self.conn.execute(
                    "UPDATE schema_version SET version = ?",
                    (self._REQUIRED_SCHEMA_VERSION,),
                )
            self.conn.commit()

    def close(self):
        self.conn.close()