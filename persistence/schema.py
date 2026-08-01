SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS systems (
    system_address INTEGER PRIMARY KEY,
    system_name TEXT,
    body_count INTEGER,
    fss_complete INTEGER,
    first_visit TEXT,
    last_visit TEXT,
    visit_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS bodies (
    system_address  INTEGER NOT NULL,
    body_id         INTEGER NOT NULL,
    body_name       TEXT,
    planet_class    TEXT,
    terraformable   INTEGER,
    landable        INTEGER,
    was_mapped      INTEGER,
    dss_mapped      INTEGER,
    estimated_value INTEGER,
    distance_ls     REAL,
    volcanism       TEXT,
    materials       TEXT,
    first_footfall  INTEGER DEFAULT 0,
    has_footfall    INTEGER DEFAULT 0,
    PRIMARY KEY (system_address, body_id)
);

CREATE TABLE IF NOT EXISTS body_signals (
    system_address INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    bio_signals INTEGER,
    geo_signals INTEGER,
    human_signals INTEGER,
    PRIMARY KEY (system_address, body_name)
);

CREATE TABLE IF NOT EXISTS exobiology (
    system_address INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    genus TEXT NOT NULL,
    species TEXT NOT NULL,
    variant TEXT NOT NULL,
    samples INTEGER,
    PRIMARY KEY (system_address, body_name, genus, species, variant)
);

CREATE TABLE IF NOT EXISTS codex_entries (
    system_address  INTEGER NOT NULL,
    body_id         INTEGER NOT NULL,
    genus           TEXT    NOT NULL,
    species         TEXT    NOT NULL,
    variant         TEXT    NOT NULL,
    codex_entry_id  INTEGER,
    codex_name      TEXT,
    base_value      INTEGER,
    PRIMARY KEY (system_address, body_id, genus)
);

CREATE TABLE IF NOT EXISTS dss_genus_discovery (
    system_address INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    genus TEXT NOT NULL,
    PRIMARY KEY (system_address, body_name, genus)
);

CREATE TABLE IF NOT EXISTS processed_journals (
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (file_name, file_size)
);

CREATE TABLE IF NOT EXISTS spansh_bodies (
    system_address  INTEGER NOT NULL,
    body_name       TEXT    NOT NULL,
    planet_class    TEXT,
    distance_ls     REAL,
    estimated_value INTEGER,
    landable        INTEGER,
    PRIMARY KEY (system_address, body_name)
);

CREATE TABLE IF NOT EXISTS faction_snapshots (
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
    my_reputation       REAL,
    is_squadron_faction INTEGER DEFAULT 0,
    PRIMARY KEY (system_address, faction_name, snapshot_date)
);

CREATE TABLE IF NOT EXISTS system_coords (
    system_name TEXT PRIMARY KEY,
    x REAL,
    y REAL,
    z REAL,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS station_info (
    market_id     INTEGER PRIMARY KEY,
    station_name  TEXT,
    system_name   TEXT,
    station_type  TEXT,
    pads_small    INTEGER,
    pads_medium   INTEGER,
    pads_large    INTEGER,
    last_visited  TEXT
);

CREATE TABLE IF NOT EXISTS market_prices (
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
);
"""