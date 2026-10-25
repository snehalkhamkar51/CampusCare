"""Database helpers for CampusCare (SQLite)."""

import os
import sqlite3
from datetime import datetime


def get_database_path():
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

VALID_ROLES = ["student", "admin"]


def get_db(db_path=None):
    path = db_path or get_database_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _column_names(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def init_db(db_path=None):
    path = db_path or get_database_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # Users table (new in milestone 2).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('student', 'admin')),
            created_at TEXT NOT NULL
        )
        """
    )

    # Complaints table (original schema, kept backward compatible).
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

    # Safe migrations for existing databases: add owner and updated_at columns.
    columns = _column_names(conn, "complaints")
    if "user_id" not in columns:
        conn.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER")
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE complaints ADD COLUMN updated_at TEXT")
    # Backfill updated_at for legacy rows.
    conn.execute(
        "UPDATE complaints SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''"
    )

    conn.commit()
    conn.close()


def generate_complaint_id(conn):
    row = conn.execute("SELECT MAX(id) AS max_id FROM complaints").fetchone()
    try:
        max_id = row["max_id"]
    except (KeyError, TypeError, IndexError):
        max_id = row[0] if row else None
    next_number = (max_id or 0) + 1
    return f"CC-{next_number:04d}"


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- User helpers ----------

def create_user(db_path, username, email, password_hash, role="student"):
    conn = get_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO users (username, email, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (username, email, password_hash, role, now_iso()),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_by_username(db_path, username):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(db_path, user_id):
    conn = get_db(db_path)
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()


def username_exists(db_path, username):
    return get_user_by_username(db_path, username) is not None


def email_exists(db_path, email):
    conn = get_db(db_path)
    try:
        row = conn.execute(
            "SELECT 1 FROM users WHERE email = ?", (email,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()
