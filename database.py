import sqlite3
import os
from datetime import date
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "goals.db")


class Database:
    def __init__(self):
        self.path = DB_PATH

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS goals (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    period  TEXT NOT NULL CHECK(period IN ('week','month','year')),
                    text    TEXT NOT NULL,
                    done    INTEGER NOT NULL DEFAULT 0,
                    reviewed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (date('now')),
                    FOREIGN KEY (user_id) REFERENCES users(id)
                );
            """)

    def ensure_user(self, uid: int):
        with self._conn() as conn:
            conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (uid,))

    def get_all_users(self) -> list[int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id FROM users").fetchall()
        return [r["id"] for r in rows]

    def add_goal(self, uid: int, period: str, text: str):
        self.ensure_user(uid)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO goals (user_id, period, text) VALUES (?, ?, ?)",
                (uid, period, text)
            )

    def get_goals(self, uid: int, period: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE user_id=? AND period=? ORDER BY id",
                (uid, period)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_goals(self, uid: int, period: str) -> list[dict]:
        """Цели не отрецензированные в текущем периоде"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM goals WHERE user_id=? AND period=? AND reviewed=0 ORDER BY id",
                (uid, period)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_goal(self, goal_id: int, done: bool):
        with self._conn() as conn:
            conn.execute(
                "UPDATE goals SET done=?, reviewed=1 WHERE id=?",
                (1 if done else 0, goal_id)
            )

    def delete_goal(self, uid: int, goal_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM goals WHERE id=? AND user_id=?",
                (goal_id, uid)
            )

    def get_goal_by_id(self, goal_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM goals WHERE id=?", (goal_id,)
            ).fetchone()
        return dict(row) if row else None
