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

    def close(self):
        self.conn.close()