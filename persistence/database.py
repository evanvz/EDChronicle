import sqlite3
from pathlib import Path


class Database:
    def __init__(self, db_path: Path):
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
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
                self.conn.commit()
            except Exception:
                pass  # column/table already exists

    def close(self):
        self.conn.close()