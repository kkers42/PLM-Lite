"""PLM Lite v2.0 — SQLite persistence layer.

Short-lived connections throughout: safe for network-share SQLite (WAL mode).
Each public method opens and closes its own connection.

In-memory usage for tests: pass db_path=':memory:' — a unique shared-cache URI
is generated per instance so multiple _connect() calls share the same DB.
"""

import logging
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import config

logger = logging.getLogger(__name__)


class DatabaseError(Exception):
    """Unrecoverable database problem."""


class CheckoutError(Exception):
    """Raised on checkout/checkin constraint violations."""


def _find_schema() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "schema.sql"
    return Path(__file__).parent.parent.parent / "schema.sql"


_SCHEMA_PATH = _find_schema()


class Database:
    def __init__(self, db_path=None):
        raw = str(db_path) if db_path is not None else str(config.DB_PATH)
        if raw == ":memory:":
            # Unique shared-cache URI so multiple _connect() calls share the same DB
            self._uri = f"file:plmlite_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._use_uri = True
        elif raw.startswith("file:"):
            self._uri = raw
            self._use_uri = True
        else:
            self._uri = raw
            self._use_uri = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._uri,
            timeout=10.0,
            check_same_thread=False,
            uri=self._use_uri,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    # ------------------------------------------------------------------
    # Init
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)
        logger.debug("Database initialized at %s", self._uri)
        # Migrations for existing DBs
        with self._connect() as conn:
            # Add change_description to item_revisions if missing
            cols = [r[1] for r in conn.execute("PRAGMA table_info(item_revisions)")]
            if 'change_description' not in cols:
                conn.execute("ALTER TABLE item_revisions ADD COLUMN change_description TEXT NOT NULL DEFAULT ''")
            # Create item_attributes if missing
            conn.execute("""CREATE TABLE IF NOT EXISTS item_attributes (
                id INTEGER PRIMARY KEY,
                item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                attr_key TEXT NOT NULL,
                attr_value TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                UNIQUE(item_id, attr_key))""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_attrs_item_id ON item_attributes(item_id)")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_create_user(self, conn: sqlite3.Connection, username: str,
                             role: str = "admin") -> int:
        cur = conn.execute("SELECT id FROM users WHERE username=?", (username,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO users(username, role) VALUES(?,?)", (username, role)
        )
        conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def upsert_user(self, username: str, role: str = "admin") -> int:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO users(username, role) VALUES(?,?)
                   ON CONFLICT(username) DO UPDATE SET role=excluded.role""",
                (username, role),
            )
            conn.commit()
            cur = conn.execute("SELECT id FROM users WHERE username=?", (username,))
            return cur.fetchone()["id"]

    def list_users(self) -> list:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM users ORDER BY username")
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Item types
    # ------------------------------------------------------------------

    def list_item_types(self) -> list:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM item_types ORDER BY name")
            return [dict(r) for r in cur.fetchall()]

    def get_item_type_by_name(self, name: str) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM item_types WHERE name=?", (name,))
            row = cur.fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    def next_item_id(self) -> str:
        with self._connect() as conn:
            cur = conn.execute("SELECT MAX(id) FROM items")
            max_id = cur.fetchone()[0] or 0
            return f"ITM-{max_id + 1:05d}"

    def create_item(self, item_id: str, name: str, description: str,
                    item_type_id: int, created_by: str) -> int:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, created_by)
            cur = conn.execute(
                """INSERT INTO items(item_id, name, description, item_type_id, created_by)
                   VALUES(?,?,?,?,?)""",
                (item_id, name, description, item_type_id, uid),
            )
            conn.commit()
            return cur.lastrowid

    def get_item(self, item_id: str) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT i.*, t.name AS type_name, u.username AS creator
                   FROM items i
                   JOIN item_types t ON t.id = i.item_type_id
                   JOIN users u      ON u.id = i.created_by
                   WHERE i.item_id=?""",
                (item_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_items(self, status_filter: Optional[str] = None) -> list:
        with self._connect() as conn:
            if status_filter:
                cur = conn.execute(
                    """SELECT i.*, t.name AS type_name, u.username AS creator
                       FROM items i
                       JOIN item_types t ON t.id = i.item_type_id
                       JOIN users u      ON u.id = i.created_by
                       WHERE i.status=? ORDER BY i.item_id""",
                    (status_filter,),
                )
            else:
                cur = conn.execute(
                    """SELECT i.*, t.name AS type_name, u.username AS creator
                       FROM items i
                       JOIN item_types t ON t.id = i.item_type_id
                       JOIN users u      ON u.id = i.created_by
                       ORDER BY i.item_id"""
                )
            return [dict(r) for r in cur.fetchall()]

    def set_item_status(self, item_pk: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE items SET status=? WHERE id=?", (status, item_pk))
            conn.commit()

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------

    def next_revision(self, item_pk: int, revision_type: str) -> str:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT revision FROM item_revisions WHERE item_id=? AND revision_type=? ORDER BY id DESC LIMIT 1",
                (item_pk, revision_type),
            )
            row = cur.fetchone()
            if not row:
                return "A" if revision_type == "alpha" else "01"
            last = row["revision"]
            if revision_type == "alpha":
                return _next_alpha(last)
            else:
                return f"{int(last) + 1:02d}"

    def create_revision(self, item_pk: int, revision: str, revision_type: str,
                        created_by: str) -> int:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, created_by)
            cur = conn.execute(
                """INSERT INTO item_revisions(item_id, revision, revision_type, created_by)
                   VALUES(?,?,?,?)""",
                (item_pk, revision, revision_type, uid),
            )
            conn.commit()
            return cur.lastrowid

    def get_revisions(self, item_pk: int) -> list:
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT r.*, r.change_description, u.username AS creator,
                          rb.username AS releaser
                   FROM item_revisions r
                   JOIN users u ON u.id = r.created_by
                   LEFT JOIN users rb ON rb.id = r.released_by
                   WHERE r.item_id=? ORDER BY r.id""",
                (item_pk,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_revision_by_name(self, item_pk: int, revision: str) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM item_revisions WHERE item_id=? AND revision=?",
                (item_pk, revision),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def lock_revision(self, revision_id: int, released_by: str) -> None:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, released_by)
            conn.execute(
                """UPDATE item_revisions
                   SET status='locked', released_by=?, released_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (uid, revision_id),
            )
            conn.commit()

    def release_revision(self, revision_id: int, released_by: str) -> None:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, released_by)
            conn.execute(
                """UPDATE item_revisions
                   SET status='released', released_by=?, released_at=CURRENT_TIMESTAMP
                   WHERE id=?""",
                (uid, revision_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Datasets
    # ------------------------------------------------------------------

    def add_dataset(self, revision_id: int, filename: str, file_type: str,
                    stored_path: str, file_size: int, added_by: str) -> int:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, added_by)
            cur = conn.execute(
                """INSERT INTO datasets(revision_id, filename, file_type,
                                        stored_path, file_size, added_by)
                   VALUES(?,?,?,?,?,?)""",
                (revision_id, filename, file_type, stored_path, file_size, uid),
            )
            conn.commit()
            return cur.lastrowid

    def get_datasets(self, revision_id: int) -> list:
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT d.*, u.username AS adder,
                          c.id AS checkout_id,
                          cu.username AS checked_out_by,
                          c.checked_out_at, c.station_name
                   FROM datasets d
                   JOIN users u ON u.id = d.added_by
                   LEFT JOIN checkouts c ON c.dataset_id = d.id
                   LEFT JOIN users cu ON cu.id = c.checked_out_by
                   WHERE d.revision_id=? ORDER BY d.filename""",
                (revision_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_dataset_by_path(self, stored_path: str) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT * FROM datasets WHERE stored_path=?", (stored_path,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_dataset_size(self, dataset_id: int, file_size: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE datasets SET file_size=? WHERE id=?", (file_size, dataset_id)
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Checkouts
    # ------------------------------------------------------------------

    def checkout_dataset(self, dataset_id: int, username: str,
                         station_name: str, lock_file_path: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT c.id, u.username AS who FROM checkouts c JOIN users u ON u.id=c.checked_out_by WHERE c.dataset_id=?",
                (dataset_id,),
            )
            existing = cur.fetchone()
            if existing:
                raise CheckoutError(
                    f"Dataset {dataset_id} already checked out by {existing['who']}"
                )
            uid = self._get_or_create_user(conn, username)
            conn.execute(
                """INSERT INTO checkouts(dataset_id, checked_out_by, station_name, lock_file_path)
                   VALUES(?,?,?,?)""",
                (dataset_id, uid, station_name, lock_file_path),
            )
            conn.commit()

    def checkin_dataset(self, dataset_id: int, username: str) -> None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT c.id, u.username AS who FROM checkouts c JOIN users u ON u.id=c.checked_out_by WHERE c.dataset_id=?",
                (dataset_id,),
            )
            row = cur.fetchone()
            if not row:
                return  # already checked in — idempotent
            if row["who"] != username:
                raise CheckoutError(
                    f"Cannot check in: dataset {dataset_id} is checked out by {row['who']}, not {username}"
                )
            conn.execute("DELETE FROM checkouts WHERE dataset_id=?", (dataset_id,))
            conn.commit()

    def get_checkout(self, dataset_id: int) -> Optional[dict]:
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT c.*, u.username AS who
                   FROM checkouts c JOIN users u ON u.id=c.checked_out_by
                   WHERE c.dataset_id=?""",
                (dataset_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_checkouts(self, username: Optional[str] = None) -> list:
        with self._connect() as conn:
            if username:
                cur = conn.execute(
                    """SELECT c.*, u.username AS who, d.filename, d.stored_path,
                              i.item_id, r.revision
                       FROM checkouts c
                       JOIN users u   ON u.id = c.checked_out_by
                       JOIN datasets d ON d.id = c.dataset_id
                       JOIN item_revisions r ON r.id = d.revision_id
                       JOIN items i ON i.id = r.item_id
                       WHERE u.username=?
                       ORDER BY c.checked_out_at DESC""",
                    (username,),
                )
            else:
                cur = conn.execute(
                    """SELECT c.*, u.username AS who, d.filename, d.stored_path,
                              i.item_id, r.revision
                       FROM checkouts c
                       JOIN users u   ON u.id = c.checked_out_by
                       JOIN datasets d ON d.id = c.dataset_id
                       JOIN item_revisions r ON r.id = d.revision_id
                       JOIN items i ON i.id = r.item_id
                       ORDER BY c.checked_out_at DESC"""
                )
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def write_audit(self, action: str, entity_type: str, entity_id: str,
                    performed_by: str, detail: str = "") -> None:
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, performed_by)
            conn.execute(
                """INSERT INTO audit_log(action, entity_type, entity_id, performed_by, detail)
                   VALUES(?,?,?,?,?)""",
                (action, entity_type, str(entity_id), uid, detail),
            )
            conn.commit()

    def get_audit_log_for_item(self, item_id: str) -> list:
        """Return all audit entries touching an item and all its revisions/datasets."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT a.*, u.username AS who
                   FROM audit_log a LEFT JOIN users u ON u.id=a.performed_by
                   WHERE
                     (a.entity_type='item'          AND a.entity_id=?)
                  OR (a.entity_type='item_revision' AND a.entity_id IN (
                        SELECT id FROM item_revisions WHERE item_id=(
                          SELECT id FROM items WHERE item_id=?)))
                  OR (a.entity_type='dataset'       AND a.entity_id IN (
                        SELECT d.id FROM datasets d
                        JOIN item_revisions r ON r.id=d.revision_id
                        WHERE r.item_id=(SELECT id FROM items WHERE item_id=?)))
                   ORDER BY a.performed_at ASC""",
                (item_id, item_id, item_id),
            )
            return [dict(r) for r in cur.fetchall()]

    def get_audit_log(self, entity_type: Optional[str] = None,
                      entity_id: Optional[str] = None) -> list:
        with self._connect() as conn:
            if entity_type and entity_id is not None:
                cur = conn.execute(
                    """SELECT a.*, u.username AS who
                       FROM audit_log a LEFT JOIN users u ON u.id=a.performed_by
                       WHERE a.entity_type=? AND a.entity_id=?
                       ORDER BY a.performed_at DESC""",
                    (entity_type, str(entity_id)),
                )
            elif entity_type:
                cur = conn.execute(
                    """SELECT a.*, u.username AS who
                       FROM audit_log a LEFT JOIN users u ON u.id=a.performed_by
                       WHERE a.entity_type=?
                       ORDER BY a.performed_at DESC""",
                    (entity_type,),
                )
            else:
                cur = conn.execute(
                    """SELECT a.*, u.username AS who
                       FROM audit_log a LEFT JOIN users u ON u.id=a.performed_by
                       ORDER BY a.performed_at DESC"""
                )
            return [dict(r) for r in cur.fetchall()]

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def add_relationship(self, parent_item_id: int, child_item_id: int,
                         quantity: int = 1, added_by: str = "system") -> None:
        """Add a parent→child relationship. Silently ignores duplicates."""
        with self._connect() as conn:
            uid = self._get_or_create_user(conn, added_by)
            conn.execute(
                """INSERT OR IGNORE INTO item_relationships
                   (parent_item_id, child_item_id, quantity, added_by)
                   VALUES (?, ?, ?, ?)""",
                (parent_item_id, child_item_id, quantity, uid),
            )
            conn.commit()

    def get_children(self, item_pk: int) -> list:
        """Return all direct children of an item."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT i.id, i.item_id, i.name, i.status,
                          t.name AS type_name, r.quantity,
                          u.username AS creator
                   FROM item_relationships r
                   JOIN items i ON i.id = r.child_item_id
                   JOIN item_types t ON t.id = i.item_type_id
                   LEFT JOIN users u ON u.id = i.created_by
                   WHERE r.parent_item_id = ?
                   ORDER BY i.item_id""",
                (item_pk,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_parents(self, item_pk: int) -> list:
        """Return all items that reference this item as a child (where-used)."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT i.id, i.item_id, i.name, i.status,
                          t.name AS type_name, r.quantity
                   FROM item_relationships r
                   JOIN items i ON i.id = r.parent_item_id
                   JOIN item_types t ON t.id = i.item_type_id
                   WHERE r.child_item_id = ?
                   ORDER BY i.item_id""",
                (item_pk,),
            )
            return [dict(row) for row in cur.fetchall()]

    def get_item_by_filename(self, filename: str) -> Optional[dict]:
        """Find an item by matching its dataset filename (basename only)."""
        with self._connect() as conn:
            cur = conn.execute(
                """SELECT i.* FROM items i
                   JOIN item_revisions r ON r.item_id = i.id
                   JOIN datasets d ON d.revision_id = r.id
                   WHERE d.filename = ?
                   ORDER BY i.id DESC LIMIT 1""",
                (filename,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def update_item(self, item_pk: int, **kwargs) -> None:
        """Update item fields: name, description, item_id."""
        allowed = {'name', 'description', 'item_id'}
        sets = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not sets:
            return
        with self._connect() as conn:
            placeholders = ', '.join(f"{k}=?" for k in sets)
            conn.execute(f"UPDATE items SET {placeholders} WHERE id=?",
                         (*sets.values(), item_pk))

    def get_attributes(self, item_pk: int) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, attr_key, attr_value, sort_order FROM item_attributes WHERE item_id=? ORDER BY sort_order, id",
                (item_pk,)).fetchall()
        return [dict(r) for r in rows]

    def set_attribute(self, item_pk: int, key: str, value: str, sort_order: int = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO item_attributes(item_id, attr_key, attr_value, sort_order) VALUES(?,?,?,?) "
                "ON CONFLICT(item_id, attr_key) DO UPDATE SET attr_value=excluded.attr_value",
                (item_pk, key, value, sort_order))

    def delete_attribute(self, item_pk: int, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM item_attributes WHERE item_id=? AND attr_key=?", (item_pk, key))

    def update_revision_description(self, revision_pk: int, change_description: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE item_revisions SET change_description=? WHERE id=?",
                         (change_description, revision_pk))


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _next_alpha(current: str) -> str:
    """Increment spreadsheet-column-style alpha revision: A->B, Z->AA, AZ->BA."""
    chars = list(current.upper())
    i = len(chars) - 1
    while i >= 0:
        if chars[i] < "Z":
            chars[i] = chr(ord(chars[i]) + 1)
            return "".join(chars)
        chars[i] = "A"
        i -= 1
    return "A" + "".join(chars)
