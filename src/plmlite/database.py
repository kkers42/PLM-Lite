"""SQLite persistence layer for PLMLITE.

All public methods open and close their own connection so that connections
are never held open across calls — important for network share SQLite reliability.
"""

import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


def _find_schema() -> Path:
    """Locate schema.sql whether running from source or as a PyInstaller frozen exe."""
    if getattr(sys, "frozen", False):
        # PyInstaller extracts --add-data files to sys._MEIPASS
        return Path(sys._MEIPASS) / "schema.sql"
    # Running from source: schema.sql is at the project root (3 levels up from here)
    return Path(__file__).parent.parent.parent / "schema.sql"


_SCHEMA_PATH = _find_schema()


class DatabaseError(Exception):
    """Raised on unrecoverable database problems."""


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DB_PATH

    def _connect(self) -> sqlite3.Connection:
        """Open a connection with WAL mode and a 10-second busy timeout."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def initialize(self) -> None:
        """Create all tables if they don't exist. Safe to call repeatedly."""
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
        logger.debug("Database initialized at %s", self.db_path)

    # -------------------------------------------------------------------------
    # File operations
    # -------------------------------------------------------------------------

    def upsert_file(self, filename: str, filepath: str) -> int:
        """Insert file if new, return its id. Returns existing id if already tracked."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id FROM files WHERE filepath = ?", (filepath,)
            )
            row = cur.fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO files (filename, filepath) VALUES (?, ?)",
                (filename, filepath),
            )
            conn.commit()
            return cur.lastrowid

    def get_file_by_path(self, filepath: str) -> Optional[dict]:
        """Return file row as dict or None."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM files WHERE filepath = ?", (filepath,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def get_file_by_name(self, filename: str) -> Optional[dict]:
        """Return first matching file row by filename or None."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM files WHERE filename = ? LIMIT 1", (filename,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_files(self) -> list[dict]:
        """Return all tracked files."""
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM files ORDER BY filename")
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Version operations
    # -------------------------------------------------------------------------

    def insert_version(
        self,
        file_id: int,
        version_num: int,
        backup_path: str,
        saved_by: str,
        file_size: int,
    ) -> int:
        """Insert a version record and bump current_version on the parent file."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO versions (file_id, version_num, backup_path, saved_by, file_size)
                   VALUES (?, ?, ?, ?, ?)""",
                (file_id, version_num, backup_path, saved_by, file_size),
            )
            conn.execute(
                "UPDATE files SET current_version = ? WHERE id = ?",
                (version_num, file_id),
            )
            conn.commit()
            return cur.lastrowid

    def get_version_history(self, file_id: int) -> list[dict]:
        """Return all versions for a file, newest first."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT * FROM versions WHERE file_id = ?
                   ORDER BY saved_at DESC""",
                (file_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_old_versions(self, file_id: int, keep: int) -> list[dict]:
        """Return versions beyond the newest `keep` entries (candidates for deletion), oldest first."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT * FROM versions WHERE file_id = ?
                   ORDER BY saved_at ASC""",
                (file_id,),
            )
            rows = [dict(r) for r in cur.fetchall()]
        excess = len(rows) - keep
        if excess <= 0:
            return []
        return rows[:excess]

    def delete_version(self, version_id: int) -> None:
        """Delete a version record by id."""
        with self._connect() as conn:
            conn.execute("DELETE FROM versions WHERE id = ?", (version_id,))
            conn.commit()

    def get_current_version_num(self, file_id: int) -> int:
        """Return the highest version_num for a file, or 0 if none exist."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT MAX(version_num) FROM versions WHERE file_id = ?",
                (file_id,),
            )
            result = cur.fetchone()[0]
            return result if result is not None else 0

    # -------------------------------------------------------------------------
    # Checkout operations
    # -------------------------------------------------------------------------

    def checkout_file(self, file_id: int, username: str) -> bool:
        """Mark file as checked out. Returns False if already checked out by someone else."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT filename, checked_out_by FROM files WHERE id = ?", (file_id,)
            )
            row = cur.fetchone()
            if row and row["checked_out_by"]:
                return False
            filename = row["filename"] if row else ""
            conn.execute(
                """UPDATE files SET checked_out_by = ?, checked_out_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (username, file_id),
            )
            conn.execute(
                "INSERT INTO checkout_log (file_id, filename, username, action) VALUES (?, ?, ?, ?)",
                (file_id, filename, username, "checkout"),
            )
            conn.commit()
            return True

    def checkin_file(self, file_id: int) -> None:
        """Clear checkout status."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT filename, checked_out_by FROM files WHERE id = ?", (file_id,)
            )
            row = cur.fetchone()
            filename = row["filename"] if row else ""
            username = row["checked_out_by"] if row else ""
            conn.execute(
                "UPDATE files SET checked_out_by = NULL, checked_out_at = NULL WHERE id = ?",
                (file_id,),
            )
            conn.execute(
                "INSERT INTO checkout_log (file_id, filename, username, action) VALUES (?, ?, ?, ?)",
                (file_id, filename, username or "", "checkin"),
            )
            conn.commit()

    def list_checkouts(self) -> list[dict]:
        """Return all files currently checked out."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM files WHERE checked_out_by IS NOT NULL ORDER BY checked_out_at"
            )
            return [dict(r) for r in cur.fetchall()]

    def get_checkout_log(self, file_id: Optional[int] = None, limit: int = 200) -> list[dict]:
        """Return checkout/checkin history, newest first. Optionally filter by file_id."""
        with self._connect() as conn:
            if file_id is not None:
                cur = conn.execute(
                    """SELECT * FROM checkout_log WHERE file_id = ?
                       ORDER BY timestamp DESC LIMIT ?""",
                    (file_id, limit),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM checkout_log ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Lifecycle state
    # -------------------------------------------------------------------------

    def set_lifecycle_state(self, file_id: int, state: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE files SET lifecycle_state = ? WHERE id = ?",
                (state, file_id),
            )
            conn.commit()

    def get_lifecycle_state(self, file_id: int) -> Optional[str]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT lifecycle_state FROM files WHERE id = ?", (file_id,)
            )
            row = cur.fetchone()
            return row["lifecycle_state"] if row else None

    # -------------------------------------------------------------------------
    # User tracking
    # -------------------------------------------------------------------------

    def upsert_user(self, username: str) -> None:
        """Insert or update user with current timestamp."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO users (username, last_active) VALUES (?, CURRENT_TIMESTAMP)
                   ON CONFLICT(username) DO UPDATE SET last_active = CURRENT_TIMESTAMP""",
                (username,),
            )
            conn.commit()

    def list_users(self) -> list[dict]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users ORDER BY last_active DESC")
            return [dict(r) for r in cur.fetchall()]

    # -------------------------------------------------------------------------
    # Relationship operations
    # -------------------------------------------------------------------------

    def add_relationship(
        self,
        parent_file_id: int,
        child_file_id: int,
        relationship_type: str = "assembly",
        notes: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO relationships
                   (parent_file_id, child_file_id, relationship_type, notes)
                   VALUES (?, ?, ?, ?)""",
                (parent_file_id, child_file_id, relationship_type, notes),
            )
            conn.commit()
            return cur.lastrowid

    def get_children(self, parent_file_id: int) -> list[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT f.*, r.id AS rel_id, r.relationship_type, r.notes AS rel_notes,
                          r.created_at AS rel_created_at
                   FROM relationships r
                   JOIN files f ON f.id = r.child_file_id
                   WHERE r.parent_file_id = ?
                   ORDER BY f.filename""",
                (parent_file_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_parents(self, child_file_id: int) -> list[dict]:
        """Return parent files + relationship metadata for a given child file."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT f.*, r.id AS rel_id, r.relationship_type, r.notes AS rel_notes
                   FROM relationships r
                   JOIN files f ON f.id = r.parent_file_id
                   WHERE r.child_file_id = ?
                   ORDER BY f.filename""",
                (child_file_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def list_all_relationships(self) -> list[dict]:
        """Return all relationships with parent/child filenames for display."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT r.id AS rel_id, r.relationship_type, r.notes, r.created_at,
                          p.id AS parent_id, p.filename AS parent_filename,
                          c.id AS child_id, c.filename AS child_filename
                   FROM relationships r
                   JOIN files p ON p.id = r.parent_file_id
                   JOIN files c ON c.id = r.child_file_id
                   ORDER BY p.filename, c.filename""",
            )
            return [dict(r) for r in cur.fetchall()]

    def relationship_exists(self, parent_id: int, child_id: int) -> bool:
        """Return True if a relationship between parent and child already exists."""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT 1 FROM relationships WHERE parent_file_id = ? AND child_file_id = ?",
                (parent_id, child_id),
            )
            return cur.fetchone() is not None

    def delete_relationship(self, relationship_id: int) -> None:
        """Remove a relationship record by its id."""
        with self._connect() as conn:
            conn.execute("DELETE FROM relationships WHERE id = ?", (relationship_id,))
            conn.commit()

    def search_files(
        self,
        name_pattern: str = "",
        state: str = "",
        checked_out_only: bool = False,
        saved_by: str = "",
    ) -> list[dict]:
        """Filter files with optional name/state/checkout/saved_by criteria."""
        clauses: list[str] = []
        params: list = []

        if name_pattern:
            clauses.append("LOWER(f.filename) LIKE ?")
            params.append(f"%{name_pattern.lower()}%")

        if state:
            clauses.append("f.lifecycle_state = ?")
            params.append(state)

        if checked_out_only:
            clauses.append("f.checked_out_by IS NOT NULL")

        if saved_by:
            # Filter by the saved_by of the most recent version
            clauses.append(
                """f.id IN (
                    SELECT file_id FROM versions
                    WHERE LOWER(saved_by) LIKE ?
                )"""
            )
            params.append(f"%{saved_by.lower()}%")

        sql = "SELECT f.* FROM files f"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY f.filename"

        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
