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

        # EDDN/Spansh-sourced tables live in a separate file, attached as
        # `net` -- see docs/superpowers/specs/2026-08-27-db-split-design.md.
        # Each attached file keeps its own independent WAL/lock even under
        # one connection, which is what actually removes the contention
        # between the periodic EDDN flush and this connection's own writes
        # (2026-08-27: two prior same-file stopgaps -- batching writes,
        # then a longer checkpoint cadence -- only reduced how often that
        # contention was felt, this removes it).
        if str(db_path) == ":memory:":
            self.cache_db_path = ":memory:"
        else:
            self.cache_db_path = Path(db_path).parent / "network_cache.db"
        self._attach_cache_db()

    def _attach_cache_db(self) -> None:
        from persistence.schema import CACHE_SCHEMA_SQL

        try:
            self.conn.execute("ATTACH DATABASE ? AS net", (str(self.cache_db_path),))
            self.conn.execute("PRAGMA net.journal_mode=WAL")
            self.conn.executescript(CACHE_SCHEMA_SQL)
        except sqlite3.DatabaseError:
            # Cache data is disposable by design -- a corrupted cache file
            # (partial write, disk issue, anything) must never take down
            # the app or risk the personal DB. Detach if partially
            # attached, delete the bad file (and any stale WAL/SHM
            # sidecars now that this DB runs in WAL mode too), and retry
            # once against a fresh one.
            try:
                self.conn.execute("DETACH DATABASE net")
            except sqlite3.OperationalError:
                pass
            if self.cache_db_path != ":memory:":
                for suffix in ("", "-wal", "-shm"):
                    try:
                        Path(f"{self.cache_db_path}{suffix}").unlink(missing_ok=True)
                    except OSError:
                        pass
            self.conn.execute("ATTACH DATABASE ? AS net", (str(self.cache_db_path),))
            self.conn.execute("PRAGMA net.journal_mode=WAL")
            self.conn.executescript(CACHE_SCHEMA_SQL)

    def execute(self, sql: str, params: tuple = ()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        self.conn.commit()
        return cur

    def executescript(self, sql: str):
        self.conn.executescript(sql)
        self.conn.commit()

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
        worker thread only, same reasoning as enable_incremental_auto_vacuum().
        Targets net.market_prices -- that table lives in the cache DB
        (see docs/superpowers/specs/2026-08-27-db-split-design.md).

        NOTE: SQLite schema-qualifies CREATE INDEX on the INDEX name, not the
        table name (opposite of CREATE TABLE/ALTER TABLE/FROM/JOIN which qualify
        the table). Correct form: CREATE INDEX net.idx_name ON table_name(...).
        Incorrect form: CREATE INDEX idx_name ON net.table_name(...) raises syntax error."""
        self.conn.execute("CREATE INDEX IF NOT EXISTS net.idx_market_prices_system_name ON market_prices(system_name)")

    def enable_incremental_auto_vacuum(self, schema: str = "main") -> bool:
        """SQLite only applies an auto_vacuum mode CHANGE on the next
        VACUUM — the file was created with the default (NONE), so this is
        a one-time cost. Returns True if a VACUUM actually ran (only ever
        happens once per database file, from then on incremental_vacuum()
        alone reclaims freed space cheaply). Call from a worker thread only
        — VACUUM rewrites the entire file, slow on a multi-GB database.
        schema: "main" (personal DB) or "net" (cache DB) -- VACUUM and its
        related PRAGMAs are schema-qualified in SQLite and apply to exactly
        one attached database per call, there's no "vacuum everything"
        single statement (see docs/superpowers/specs/2026-08-27-db-split-design.md)."""
        mode = self.conn.execute(f"PRAGMA {schema}.auto_vacuum").fetchone()[0]
        if mode == 2:  # already INCREMENTAL
            return False
        self.conn.execute(f"PRAGMA {schema}.auto_vacuum = INCREMENTAL")
        self.conn.execute(f"VACUUM {schema}")
        return True

    def incremental_vacuum(self, pages: int = 2000, schema: str = "main") -> None:
        """Reclaims already-freed pages (e.g. from a prior DELETE) a chunk
        at a time — cheap compared to a full VACUUM. Call from a worker
        thread only, same reasoning as enable_incremental_auto_vacuum().
        schema: see enable_incremental_auto_vacuum's docstring."""
        self.conn.execute(f"PRAGMA {schema}.incremental_vacuum({pages})")

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
        a worker thread only, same reasoning as ensure_market_prices_indexes().
        Unlike ensure_market_prices_indexes()'s tables, system_coords stays
        in `main` (it's personal-DB data, not EDDN/Spansh cache) -- that's
        why this method takes no schema parameter and never references
        `net.`."""
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_system_coords_xyz ON system_coords(x, y, z)")

    def run_migrations(self):
        """Add new columns to existing tables without breaking older DBs.
        Two independent lists -- personal tables in `main`, EDDN/Spansh
        cache tables in `net` (see docs/superpowers/specs/2026-08-27-
        db-split-design.md). Each entry is idempotent (IF NOT EXISTS /
        best-effort ALTER), so running this on every startup is safe."""
        personal_migrations = [
            "ALTER TABLE bodies ADD COLUMN first_footfall INTEGER DEFAULT 0",
            "ALTER TABLE bodies ADD COLUMN has_footfall    INTEGER DEFAULT 0",
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
            """CREATE TABLE IF NOT EXISTS dismissed_faction_systems (
                faction_name   TEXT NOT NULL,
                system_address INTEGER NOT NULL,
                PRIMARY KEY (faction_name, system_address)
            )""",
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
            """CREATE TABLE IF NOT EXISTS resolved_bodies (
                system_address INTEGER NOT NULL,
                body_id        INTEGER NOT NULL,
                PRIMARY KEY (system_address, body_id)
            )""",
            "ALTER TABLE codex_entries ADD COLUMN is_phenomena INTEGER DEFAULT 0",
            # Outfitting/shipyard tracking (station_modules/station_ships) was
            # removed 2026-08-27 -- see edc/core/eddn_market.py history.
            "DROP TABLE IF EXISTS station_modules",
            "DROP TABLE IF EXISTS station_ships",
            # 2026-08-27 DB split: these 8 tables now live in `net`
            # (network_cache.db) instead of `main` -- drop any copy an
            # existing un-wiped edhelper.db already has. No-op on a
            # database that never had them (new DBs, or one already
            # created after this migration ran once).
            "DROP TABLE IF EXISTS main.spansh_bodies",
            "DROP TABLE IF EXISTS main.station_info",
            "DROP TABLE IF EXISTS main.commodity_names",
            "DROP TABLE IF EXISTS main.market_prices",
            "DROP TABLE IF EXISTS main.fleet_carrier_materials",
            "DROP TABLE IF EXISTS main.codex_species_sightings",
            "DROP TABLE IF EXISTS main.system_bgs_status",
            "DROP TABLE IF EXISTS main.system_res_sites",
            # Set true for a system backfilled from the commander's personal
            # EDSM flight log (tools/import_edsm_flight_log.py) where any
            # visit had EDSM's own firstDiscover flag set -- distinct from
            # bodies.first_discovered, which is per-body and only ever known
            # from a personal journal Scan event.
            "ALTER TABLE systems ADD COLUMN first_discovery INTEGER DEFAULT 0",
            # Surface Mining (Update 4.4, 2026-09-02): $PlanetaryMiningLocation_Name;
            # signal count, tracked alongside bio/geo/human in body_signals.
            "ALTER TABLE body_signals ADD COLUMN surface_mining_signals INTEGER",
        ]
        cache_migrations = [
            "ALTER TABLE net.spansh_bodies ADD COLUMN surface_gravity REAL",
            "ALTER TABLE net.spansh_bodies ADD COLUMN radius REAL",
            "ALTER TABLE net.spansh_bodies ADD COLUMN mass_em REAL",
            "ALTER TABLE net.spansh_bodies ADD COLUMN surface_temperature REAL",
            "ALTER TABLE net.spansh_bodies ADD COLUMN surface_pressure REAL",
            "ALTER TABLE net.spansh_bodies ADD COLUMN atmosphere_type TEXT",
            "ALTER TABLE net.spansh_bodies ADD COLUMN volcanism TEXT",
            "ALTER TABLE net.spansh_bodies ADD COLUMN tidal_lock INTEGER",
            "ALTER TABLE net.spansh_bodies ADD COLUMN was_mapped INTEGER",
            "ALTER TABLE net.spansh_bodies ADD COLUMN updated_at TEXT",
            # Surface Mining (Update 4.4): crowd-sourced Planetary Mining
            # Location signal count for bodies from other commanders' EDDN
            # fssbodysignals uploads -- not a personal DB column, so no
            # _REQUIRED_SCHEMA_VERSION bump needed (net.* is disposable cache).
            "ALTER TABLE net.spansh_bodies ADD COLUMN surface_mining_signals INTEGER",
            "ALTER TABLE net.station_info ADD COLUMN station_services TEXT",
            "ALTER TABLE net.station_info ADD COLUMN station_faction TEXT",
            "ALTER TABLE net.station_info ADD COLUMN carrier_docking_access TEXT",
            "ALTER TABLE net.station_info ADD COLUMN economies TEXT",
            "ALTER TABLE net.station_info ADD COLUMN dist_from_star_ls REAL",
            "ALTER TABLE net.station_info ADD COLUMN station_government TEXT",
            "ALTER TABLE net.station_info ADD COLUMN station_allegiance TEXT",
            """CREATE TABLE IF NOT EXISTS net.fleet_carrier_materials (
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
            "CREATE INDEX IF NOT EXISTS net.idx_fcm_symbol ON fleet_carrier_materials(material_symbol)",
            "CREATE INDEX IF NOT EXISTS net.idx_market_prices_commodity ON market_prices(commodity_name)",
            """CREATE TABLE IF NOT EXISTS net.codex_species_sightings (
                system_address  INTEGER NOT NULL,
                body_id         INTEGER NOT NULL,
                species_name    TEXT    NOT NULL,
                species_symbol  TEXT,
                last_seen       TEXT    NOT NULL,
                PRIMARY KEY (system_address, body_id)
            )""",
            """CREATE TABLE IF NOT EXISTS net.system_bgs_status (
                system_address INTEGER PRIMARY KEY,
                system_name    TEXT,
                conflicts      TEXT,
                faction_states TEXT,
                data_timestamp TEXT,
                source         TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS net.system_res_sites (
                system_address INTEGER PRIMARY KEY,
                system_name    TEXT,
                tiers          TEXT,
                data_timestamp TEXT,
                source         TEXT
            )""",
        ]
        for sql in personal_migrations + cache_migrations:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except Exception:
                pass  # column/table already exists

        self._apply_version_migrations()

    # Bump this constant whenever a migration requires journals to be re-imported.
    _REQUIRED_SCHEMA_VERSION = 9

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
            # v7: resolved_bodies table (star FSS-resolution) and
            #     codex_entries.is_phenomena (NSP Codex confirmations) were added.
            # v8: journal_importer.py now backfills faction_snapshots
            #     (including SquadronFaction:true detection) from historical
            #     Location/FSDJump events, which it never did before.
            # v9: body_signals.surface_mining_signals was added (Surface
            #     Mining, Update 4.4).
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