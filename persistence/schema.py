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
    system_address INTEGER NOT NULL,
    body_id INTEGER NOT NULL,
    body_name TEXT,
    planet_class TEXT,
    terraformable INTEGER,
    landable INTEGER,
    mapped INTEGER,
    estimated_value INTEGER,
    distance_ls REAL,
    PRIMARY KEY (system_address, body_id)
);

CREATE TABLE IF NOT EXISTS body_signals (
    system_address INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    bio_signals INTEGER,
    geo_signals INTEGER,
    PRIMARY KEY (system_address, body_name)
);

CREATE TABLE IF NOT EXISTS exobiology (
    system_address INTEGER NOT NULL,
    body_name TEXT NOT NULL,
    genus TEXT NOT NULL,
    species TEXT NOT NULL,
    samples INTEGER,
    PRIMARY KEY (system_address, body_name, genus, species)
);

CREATE TABLE IF NOT EXISTS processed_journals (
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    processed_at TEXT NOT NULL,
    PRIMARY KEY (file_name, file_size)
);
"""