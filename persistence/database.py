import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        # timeout=30: how long a connection waits for a lock before raising
        # "database is locked", instead of sqlite3's 5s default — matters
        # now that background workers (CSV import, market search) open
        # their own connection to this same file while the main/UI thread
        # is also reading/writing live. WAL journal mode is the real fix
        # (readers don't block on a writer at all, and vice versa in the
        # common case) — the busy_timeout is just a safety net for the
        # writer-vs-writer case WAL doesn't eliminate.
        self.conn = sqlite3.connect(db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        if str(db_path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def executescript(self, sql: str):
        self.conn.executescript(sql)
        self.conn.commit()

    def enable_incremental_auto_vacuum(self) -> bool:
        """SQLite only applies an auto_vacuum mode CHANGE on the next
        VACUUM — the file was created with the default (NONE), so this is
        a one-time cost. Returns True if a VACUUM actually ran (only ever
        happens once per database file, from then on incremental_vacuum()
        alone reclaims freed space cheaply). Call from a worker thread only
        — VACUUM rewrites the entire file, slow on a multi-GB database."""
        mode = self.conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if mode == 2:  # already INCREMENTAL
            return False
        self.conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
        self.conn.execute("VACUUM")
        return True

    def incremental_vacuum(self, pages: int = 2000) -> None:
        """Reclaims already-freed pages (e.g. from a prior DELETE) a chunk
        at a time — cheap compared to a full VACUUM. Call from a worker
        thread only, same reasoning as enable_incremental_auto_vacuum()."""
        self.conn.execute(f"PRAGMA incremental_vacuum({pages})")

    def ensure_market_prices_indexes(self) -> None:
        """market_prices' only index besides its PRIMARY KEY is on
        commodity_name — every "which stations are near (x,y,z)" query
        (Trade Route Loop Planner, and to a lesser extent Market search)
        filters on system_name too, with nothing to narrow the row set
        first when it wants every commodity for a station rather than one
        specific one. Confirmed live: a full table scan taking 48.7s at
        ~13.4M rows, 6.2s after this index (SEARCH instead of SCAN per
        EXPLAIN QUERY PLAN). IF NOT EXISTS makes every run after the first
        an instant no-op. Building it takes ~2+ minutes on a database this
        size and needs a write lock like any schema change — call from a
        worker thread only, same reasoning as enable_incremental_auto_vacuum()."""
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_market_prices_system_name ON market_prices(system_name)")

    def ensure_system_coords_indexes(self) -> None:
        """system_coords has no index besides its PRIMARY KEY (system_name)
        — every radius search (Market, Fleet Carrier Materials, Trade Route
        Loop Planner) does a bounding-box JOIN against x/y/z with nothing to
        narrow the row set first. Not run from run_migrations() (which runs
        synchronously on the main/UI thread every startup) for the same
        reason ensure_market_prices_indexes() isn't: system_coords is fed
        continuously by the EDDN listener and grows unboundedly (437k+ rows
        and climbing as of this writing) — an index build at that scale, or
        whatever scale it reaches later, could freeze app launch. IF NOT
        EXISTS makes every run after the first an instant no-op. Call from
        a worker thread only, same reasoning as ensure_market_prices_indexes()."""
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_system_coords_xyz ON system_coords(x, y, z)")

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
            "ALTER TABLE faction_snapshots ADD COLUMN data_timestamp TEXT",
            "ALTER TABLE faction_snapshots ADD COLUMN source TEXT",
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
            """CREATE TABLE IF NOT EXISTS dismissed_faction_systems (
                faction_name   TEXT NOT NULL,
                system_address INTEGER NOT NULL,
                PRIMARY KEY (faction_name, system_address)
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
            """CREATE TABLE IF NOT EXISTS fleet_carrier_materials (
                market_id       INTEGER NOT NULL,
                material_symbol TEXT    NOT NULL,
                carrier_name    TEXT,
                carrier_id      TEXT,
                price           INTEGER,
                stock           INTEGER,
                demand          INTEGER,
                last_updated    TEXT    NOT NULL,
                PRIMARY KEY (market_id, material_symbol)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_fcm_symbol ON fleet_carrier_materials(material_symbol)",
            """CREATE TABLE IF NOT EXISTS rings (
                system_address INTEGER NOT NULL,
                ring_name      TEXT    NOT NULL,
                parent_body    TEXT,
                ring_class     TEXT,
                distance_ls    REAL,
                scanned        INTEGER DEFAULT 0,
                hotspots       TEXT,
                PRIMARY KEY (system_address, ring_name)
            )""",
            # market_prices' PRIMARY KEY is (market_id, commodity_name) — great
            # for market_id lookups (Rare Goods, service finders), useless for
            # a commodity_name-only search (the Market tab's main search),
            # which was a confirmed full-table-scan taking 20+ seconds once
            # this table reached ~12M rows.
            "CREATE INDEX IF NOT EXISTS idx_market_prices_commodity ON market_prices(commodity_name)",
            # Biology CodexEntry sightings from the EDDN network — species are
            # deterministic per body, so another commander's already-reported
            # find tells us exactly what's there before we personally DSS it.
            """CREATE TABLE IF NOT EXISTS codex_species_sightings (
                system_address  INTEGER NOT NULL,
                body_id         INTEGER NOT NULL,
                species_name    TEXT    NOT NULL,
                species_symbol  TEXT,
                last_seen       TEXT    NOT NULL,
                PRIMARY KEY (system_address, body_id)
            )""",
            # ColonisationConstructionDepot only ever fires in your own
            # journal when you personally dock at the depot — no EDDN schema
            # exists for it (confirmed against EDCD/EDDN's schema repo), so
            # this can't be crowdsourced. market_id is nullable to support
            # manually adding a squadron site before ever visiting it; once
            # visited, that row is matched by system+station name and
            # updated in place with the real market_id and progress data.
            """CREATE TABLE IF NOT EXISTS colonisation_depots (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                market_id      INTEGER,
                system_address INTEGER,
                system_name    TEXT NOT NULL,
                station_name   TEXT NOT NULL,
                progress       REAL,
                complete       INTEGER DEFAULT 0,
                resources      TEXT,
                last_updated   TEXT
            )""",
            "ALTER TABLE bodies ADD COLUMN was_footfalled INTEGER DEFAULT 0",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except Exception:
                pass  # column/table already exists

        self._apply_version_migrations()

    # Bump this constant whenever a migration requires journals to be re-imported.
    _REQUIRED_SCHEMA_VERSION = 6

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
            # v5: rings table (hotspot scan history) was added.
            # v6: bodies.was_footfalled was added.
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