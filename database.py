"""Database helpers for CampusCare (SQLite)."""

import os
import sqlite3
from datetime import datetime


def get_database_path():
    """Return the SQLite database path, allowing env override (useful for tests)."""
    return os.environ.get("DATABASE_PATH", os.path.join("instance", "campuscare.db"))


VALID_CATEGORIES = [
    "Infrastructure",
    "IT / Network",
    "Hostel",
    "Classroom",
    "Library",
    "Cafeteria",
    "Transport",
    "Other",
]

VALID_PRIORITIES = ["Low", "Medium", "High"]

VALID_STATUSES = ["Pending", "In Progress", "Resolved"]


def get_db(db_path=None):
    path = db_path or get_database_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    path = db_path or get_database_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def generate_complaint_id(conn):
    row = conn.execute("SELECT MAX(id) AS max_id FROM complaints").fetchone()
    # sqlite3.Row supports key access; fall back to index if needed
    try:
        max_id = row["max_id"]
    except (KeyError, TypeError):
        max_id = row[0]
    next_number = (max_id or 0) + 1
    return f"CC-{next_number:04d}"


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
