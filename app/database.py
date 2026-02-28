"""
PLM Lite V1.0 — Database layer
Short-lived SQLite connections; safe for network share and concurrent access.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Optional

from . import config

_SCHEMA = Path(__file__).parent.parent / "schema.sql"


class Database:
    def __init__(self, db_path: Path = config.DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def initialize(self) -> None:
        """Create tables from schema.sql and seed default roles/admin if needed."""
        sql = _SCHEMA.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(sql)
            conn.commit()
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        with self._connect() as conn:
            if conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO roles (name, can_release, can_view, can_write, can_upload, can_checkout, can_admin) VALUES (?,?,?,?,?,?,?)",
                    [
                        ("Admin",    1, 1, 1, 1, 1, 1),
                        ("Engineer", 1, 1, 1, 1, 1, 0),
                        ("Viewer",   0, 1, 0, 0, 0, 0),
                    ],
                )
                conn.commit()
            if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
                import bcrypt as _bcrypt_lib
                admin_hash = _bcrypt_lib.hashpw(b"admin123", _bcrypt_lib.gensalt()).decode()
                admin_role = conn.execute("SELECT id FROM roles WHERE name='Admin'").fetchone()
                conn.execute(
                    "INSERT INTO users (username, password_hash, role_id, must_change_password) VALUES (?,?,?,1)",
                    ("admin", admin_hash, admin_role["id"] if admin_role else None),
                )
                conn.commit()

    # ── Roles ─────────────────────────────────────────────────────────────────

    def list_roles(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM roles ORDER BY name").fetchall()]

    def get_role(self, role_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
            return dict(row) if row else None

    def create_role(self, name: str, abilities: dict) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO roles (name, can_release, can_view, can_write, can_upload, can_checkout, can_admin) VALUES (?,?,?,?,?,?,?)",
                (name,
                 int(abilities.get("can_release", 1)),
                 int(abilities.get("can_view", 1)),
                 int(abilities.get("can_write", 1)),
                 int(abilities.get("can_upload", 1)),
                 int(abilities.get("can_checkout", 1)),
                 int(abilities.get("can_admin", 0))),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM roles WHERE name=?", (name,)).fetchone()
            return dict(row)

    def update_role(self, role_id: int, name: str, abilities: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE roles SET name=?, can_release=?, can_view=?, can_write=?, can_upload=?, can_checkout=?, can_admin=? WHERE id=?",
                (name,
                 int(abilities.get("can_release", 1)),
                 int(abilities.get("can_view", 1)),
                 int(abilities.get("can_write", 1)),
                 int(abilities.get("can_upload", 1)),
                 int(abilities.get("can_checkout", 1)),
                 int(abilities.get("can_admin", 0)),
                 role_id),
            )
            conn.commit()

    def delete_role(self, role_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM roles WHERE id=?", (role_id,))
            conn.commit()

    # ── Users ─────────────────────────────────────────────────────────────────

    def get_user(self, user_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.*, r.name as role_name, r.can_release, r.can_view, r.can_write,
                          r.can_upload, r.can_checkout, r.can_admin
                   FROM users u LEFT JOIN roles r ON u.role_id = r.id
                   WHERE u.id=?""",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.*, r.name as role_name, r.can_release, r.can_view, r.can_write,
                          r.can_upload, r.can_checkout, r.can_admin
                   FROM users u LEFT JOIN roles r ON u.role_id = r.id
                   WHERE LOWER(u.username)=LOWER(?)""",
                (username,),
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_email(self, email: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT u.*, r.name as role_name, r.can_release, r.can_view, r.can_write,
                          r.can_upload, r.can_checkout, r.can_admin
                   FROM users u LEFT JOIN roles r ON u.role_id = r.id
                   WHERE LOWER(u.email)=LOWER(?)""",
                (email,),
            ).fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(r) for r in conn.execute(
                    """SELECT u.id, u.username, u.email, u.is_active, u.must_change_password,
                              u.created_at, u.last_active, u.role_id,
                              r.name as role_name
                       FROM users u LEFT JOIN roles r ON u.role_id=r.id
                       ORDER BY u.username""",
                ).fetchall()
            ]

    def create_user(self, username: str, password_hash: Optional[str], email: Optional[str], role_id: Optional[int]) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, email, role_id) VALUES (?,?,?,?)",
                (username, password_hash, email, role_id),
            )
            conn.commit()
            return self.get_user_by_username(username)

    def upsert_oauth_user(self, email: str, username: str) -> dict:
        """Create or update a Google OAuth user. Assigns Engineer role if new."""
        with self._connect() as conn:
            existing = self.get_user_by_email(email)
            if existing:
                conn.execute("UPDATE users SET last_active=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
                conn.commit()
                return self.get_user(existing["id"])
            engineer_role = conn.execute("SELECT id FROM roles WHERE name='Engineer'").fetchone()
            conn.execute(
                "INSERT INTO users (username, email, role_id) VALUES (?,?,?)",
                (username, email, engineer_role["id"] if engineer_role else None),
            )
            conn.commit()
            return self.get_user_by_email(email)

    def upsert_windows_user(self, username: str, windows_identity: str) -> dict:
        """Create or return a Windows-authenticated user. Assigns Viewer role if new."""
        with self._connect() as conn:
            existing = self.get_user_by_username(username)
            if existing:
                conn.execute("UPDATE users SET last_active=CURRENT_TIMESTAMP WHERE id=?", (existing["id"],))
                conn.commit()
                return self.get_user(existing["id"])
            viewer_role = conn.execute("SELECT id FROM roles WHERE name='Viewer'").fetchone()
            conn.execute(
                "INSERT INTO users (username, role_id, is_active) VALUES (?,?,1)",
                (username, viewer_role["id"] if viewer_role else None),
            )
            conn.commit()
            return self.get_user_by_username(username)

    def update_user(self, user_id: int, role_id: Optional[int], is_active: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET role_id=?, is_active=? WHERE id=?",
                (role_id, is_active, user_id),
            )
            conn.commit()

    def update_user_password(self, user_id: int, password_hash: str, must_change: int = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, must_change_password=? WHERE id=?",
                (password_hash, must_change, user_id),
            )
            conn.commit()

    def touch_user(self, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE users SET last_active=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
            conn.commit()

    # ── Parts ─────────────────────────────────────────────────────────────────

    def create_part(self, data: dict, created_by: int) -> dict:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO parts (part_number, part_name, part_revision, description,
                   part_level, created_by) VALUES (?,?,?,?,?,?)""",
                (data["part_number"], data["part_name"],
                 data.get("part_revision", "A"), data.get("description", ""),
                 data.get("part_level", ""), created_by),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM parts WHERE part_number=?", (data["part_number"],)).fetchone()
            part = dict(row)
        self._log_audit(created_by, "create_part", "part", part["id"], {"part_number": part["part_number"]})
        return part

    def get_part(self, part_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT p.*, u1.username as created_by_name, u2.username as checked_out_by_name
                   FROM parts p
                   LEFT JOIN users u1 ON p.created_by = u1.id
                   LEFT JOIN users u2 ON p.checked_out_by = u2.id
                   WHERE p.id=?""",
                (part_id,),
            ).fetchone()
            if not row:
                return None
            part = dict(row)
            part["attributes"] = self.get_attributes(part_id)
            return part

    def get_part_by_number(self, part_number: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT id FROM parts WHERE part_number=?", (part_number,)).fetchone()
            return self.get_part(row["id"]) if row else None

    def list_parts(
        self,
        search: str = "",
        status: str = "",
        checked_out_only: bool = False,
        page: int = 1,
        per_page: int = 50,
    ) -> dict:
        where = ["1=1"]
        params: list = []
        if search:
            where.append("(LOWER(p.part_number) LIKE ? OR LOWER(p.part_name) LIKE ?)")
            params += [f"%{search.lower()}%", f"%{search.lower()}%"]
        if status:
            where.append("p.release_status=?")
            params.append(status)
        if checked_out_only:
            where.append("p.checked_out_by IS NOT NULL")

        where_sql = " AND ".join(where)
        offset = (page - 1) * per_page

        with self._connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM parts p WHERE {where_sql}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT p.*, u1.username as created_by_name, u2.username as checked_out_by_name
                    FROM parts p
                    LEFT JOIN users u1 ON p.created_by = u1.id
                    LEFT JOIN users u2 ON p.checked_out_by = u2.id
                    WHERE {where_sql}
                    ORDER BY p.part_number
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()
        return {"total": total, "page": page, "per_page": per_page, "items": [dict(r) for r in rows]}

    def update_part(self, part_id: int, data: dict, updated_by: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE parts SET part_name=?, description=?, part_level=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (data["part_name"], data.get("description", ""), data.get("part_level", ""), part_id),
            )
            conn.commit()
        self._log_audit(updated_by, "update_part", "part", part_id, data)

    def delete_part(self, part_id: int, deleted_by: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM parts WHERE id=?", (part_id,))
            conn.commit()
        self._log_audit(deleted_by, "delete_part", "part", part_id, {})

    def checkout_part(self, part_id: int, user_id: int, station: str = "") -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT checked_out_by FROM parts WHERE id=?", (part_id,)).fetchone()
            if not row or row["checked_out_by"] is not None:
                return False
            conn.execute(
                "UPDATE parts SET checked_out_by=?, checked_out_at=CURRENT_TIMESTAMP, checked_out_station=? WHERE id=?",
                (user_id, station, part_id),
            )
            conn.commit()
        self._log_audit(user_id, "checkout", "part", part_id, {"station": station})
        return True

    def checkin_part(self, part_id: int, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE parts SET checked_out_by=NULL, checked_out_at=NULL, checked_out_station=NULL WHERE id=?",
                (part_id,),
            )
            conn.commit()
        self._log_audit(user_id, "checkin", "part", part_id, {})

    def release_part(self, part_id: int, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE parts SET release_status='Released', is_locked=1, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (part_id,),
            )
            conn.commit()
        self._log_audit(user_id, "release", "part", part_id, {})

    def unrelease_part(self, part_id: int, user_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE parts SET release_status='Prototype', is_locked=0, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (part_id,),
            )
            conn.commit()
        self._log_audit(user_id, "unrelease", "part", part_id, {})

    def bump_revision(self, part_id: int, user_id: int, description: str = "") -> str:
        """Snapshot current state, increment revision letter, unlock part."""
        part = self.get_part(part_id)
        if not part:
            raise ValueError("Part not found")
        current_rev = part["part_revision"]
        next_rev = chr(ord(current_rev[-1]) + 1) if current_rev else "B"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO part_revisions (part_id, revision_label, description, changed_by, snapshot_json) VALUES (?,?,?,?,?)",
                (part_id, current_rev, description, user_id, json.dumps(part)),
            )
            conn.execute(
                "UPDATE parts SET part_revision=?, is_locked=0, release_status='Prototype', updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (next_rev, part_id),
            )
            conn.commit()
        self._log_audit(user_id, "bump_revision", "part", part_id, {"from": current_rev, "to": next_rev})
        return next_rev

    def list_revisions(self, part_id: int) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT pr.*, u.username as changed_by_name
                   FROM part_revisions pr LEFT JOIN users u ON pr.changed_by=u.id
                   WHERE pr.part_id=? ORDER BY pr.changed_at DESC""",
                (part_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Part Attributes ───────────────────────────────────────────────────────

    def get_attributes(self, part_id: int) -> list[dict]:
        with self._connect() as conn:
            return [
                dict(r) for r in conn.execute(
                    "SELECT * FROM part_attributes WHERE part_id=? ORDER BY attr_order, attr_key",
                    (part_id,),
                ).fetchall()
            ]

    def set_attribute(self, part_id: int, key: str, value: str, order: int = 0) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO part_attributes (part_id, attr_key, attr_value, attr_order) VALUES (?,?,?,?) "
                "ON CONFLICT(part_id, attr_key) DO UPDATE SET attr_value=excluded.attr_value, attr_order=excluded.attr_order",
                (part_id, key, value, order),
            )
            conn.commit()

    def delete_attribute(self, part_id: int, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM part_attributes WHERE part_id=? AND attr_key=?", (part_id, key))
            conn.commit()

    def list_attribute_keys(self) -> list[str]:
        with self._connect() as conn:
            return [
                r[0] for r in conn.execute(
                    "SELECT DISTINCT attr_key FROM part_attributes ORDER BY attr_key"
                ).fetchall()
            ]

    # ── Part Relationships ─────────────────────────────────────────────────────

    def add_relationship(self, parent_id: int, child_id: int, quantity: float = 1.0,
                         rel_type: str = "assembly", notes: str = "", user_id: int = 0) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO part_relationships (parent_part_id, child_part_id, quantity, relationship_type, notes) VALUES (?,?,?,?,?)",
                (parent_id, child_id, quantity, rel_type, notes),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM part_relationships WHERE parent_part_id=? AND child_part_id=?",
                (parent_id, child_id),
            ).fetchone()
        self._log_audit(user_id, "add_relationship", "relationship", row["id"], {"parent": parent_id, "child": child_id})
        return dict(row)

    def delete_relationship(self, rel_id: int, user_id: int = 0) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM part_relationships WHERE id=?", (rel_id,))
            conn.commit()
        self._log_audit(user_id, "delete_relationship", "relationship", rel_id, {})

    def relationship_exists(self, parent_id: int, child_id: int) -> bool:
        with self._connect() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM part_relationships WHERE parent_part_id=? AND child_part_id=?",
                (parent_id, child_id),
            ).fetchone())

    def get_children(self, part_id: int) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT pr.id as rel_id, pr.quantity, pr.relationship_type, pr.notes,
                          p.id, p.part_number, p.part_name, p.part_revision, p.release_status
                   FROM part_relationships pr JOIN parts p ON pr.child_part_id=p.id
                   WHERE pr.parent_part_id=? ORDER BY p.part_number""",
                (part_id,),
            ).fetchall()]

    def get_parents(self, part_id: int) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT pr.id as rel_id, pr.relationship_type,
                          p.id, p.part_number, p.part_name, p.part_revision, p.release_status
                   FROM part_relationships pr JOIN parts p ON pr.parent_part_id=p.id
                   WHERE pr.child_part_id=? ORDER BY p.part_number""",
                (part_id,),
            ).fetchall()]

    def list_all_relationships(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                """SELECT pr.id, pr.quantity, pr.relationship_type, pr.notes, pr.created_at,
                          pp.part_number as parent_pn, pp.part_name as parent_name,
                          pc.part_number as child_pn,  pc.part_name as child_name
                   FROM part_relationships pr
                   JOIN parts pp ON pr.parent_part_id=pp.id
                   JOIN parts pc ON pr.child_part_id=pc.id
                   ORDER BY pp.part_number, pc.part_number""",
            ).fetchall()]

    def get_bom_flat(self, root_part_id: int) -> list[dict]:
        """Recursive BOM as flat list with depth column."""
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                """WITH RECURSIVE bom(part_id, depth, path) AS (
                     SELECT ?, 0, CAST(? AS TEXT)
                     UNION ALL
                     SELECT pr.child_part_id, b.depth+1, b.path || '/' || pr.child_part_id
                     FROM part_relationships pr JOIN bom b ON pr.parent_part_id=b.part_id
                     WHERE b.depth < 20
                   )
                   SELECT b.depth, pr_link.quantity, pr_link.relationship_type,
                          p.id, p.part_number, p.part_name, p.part_revision, p.release_status
                   FROM bom b
                   JOIN parts p ON b.part_id=p.id
                   LEFT JOIN part_relationships pr_link ON pr_link.child_part_id=b.part_id
                   WHERE b.depth > 0
                   ORDER BY b.path""",
                (root_part_id, root_part_id),
            ).fetchall()]

    def get_tree(self, part_id: int, depth: int = 0) -> dict:
        """Recursive tree dict for visual renderer."""
        part = self.get_part(part_id)
        if not part:
            return {}
        children = self.get_children(part_id)
        return {
            "id": part_id,
            "part_number": part["part_number"],
            "part_name": part["part_name"],
            "part_revision": part["part_revision"],
            "release_status": part["release_status"],
            "depth": depth,
            "children": [self.get_tree(c["id"], depth + 1) for c in children] if depth < 20 else [],
        }

    # ── Documents ─────────────────────────────────────────────────────────────

    def create_document(self, filename: str, stored_path: str, file_type: str,
                        description: str, uploaded_by: int, part_id: Optional[int] = None) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO documents (part_id, filename, stored_path, file_type, description, uploaded_by) VALUES (?,?,?,?,?,?)",
                (part_id, filename, stored_path, file_type, description, uploaded_by),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM documents WHERE stored_path=?", (stored_path,)).fetchone()
        doc = dict(row)
        self._log_audit(uploaded_by, "upload_document", "document", doc["id"], {"filename": filename, "part_id": part_id})
        return doc

    def get_document(self, doc_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def list_documents(self, part_id: Optional[int] = None) -> list[dict]:
        with self._connect() as conn:
            if part_id is not None:
                rows = conn.execute(
                    """SELECT d.*, u.username as uploaded_by_name
                       FROM documents d LEFT JOIN users u ON d.uploaded_by=u.id
                       WHERE d.part_id=? ORDER BY d.uploaded_at DESC""",
                    (part_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT d.*, u.username as uploaded_by_name
                       FROM documents d LEFT JOIN users u ON d.uploaded_by=u.id
                       ORDER BY d.uploaded_at DESC""",
                ).fetchall()
            return [dict(r) for r in rows]

    def attach_document(self, part_id: int, doc_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE documents SET part_id=? WHERE id=?", (part_id, doc_id))
            conn.commit()

    def detach_document(self, doc_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE documents SET part_id=NULL WHERE id=?", (doc_id,))
            conn.commit()

    def delete_document(self, doc_id: int, user_id: int) -> Optional[str]:
        """Returns stored_path for physical deletion."""
        doc = self.get_document(doc_id)
        if not doc:
            return None
        with self._connect() as conn:
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
            conn.commit()
        self._log_audit(user_id, "delete_document", "document", doc_id, {"filename": doc["filename"]})
        return doc["stored_path"]

    # ── File Versions ─────────────────────────────────────────────────────────

    def add_file_version(self, doc_id: int, version_label: str, backup_path: str,
                          file_size: int, saved_by: int) -> dict:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO file_versions (document_id, version_label, backup_path, file_size, saved_by) VALUES (?,?,?,?,?)",
                (doc_id, version_label, backup_path, file_size, saved_by),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM file_versions WHERE document_id=? AND version_label=?",
                (doc_id, version_label),
            ).fetchone()
            return dict(row)

    def list_file_versions(self, doc_id: int) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM file_versions WHERE document_id=? ORDER BY saved_at DESC",
                (doc_id,),
            ).fetchall()]

    def get_old_versions(self, doc_id: int, keep: int) -> list[dict]:
        """Return versions beyond the keep limit (oldest first)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM file_versions WHERE document_id=? ORDER BY saved_at DESC",
                (doc_id,),
            ).fetchall()
            return [dict(r) for r in rows[keep:]]

    def delete_file_version(self, version_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT backup_path FROM file_versions WHERE id=?", (version_id,)).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM file_versions WHERE id=?", (version_id,))
            conn.commit()
            return row["backup_path"]

    def get_file_version(self, version_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM file_versions WHERE id=?", (version_id,)).fetchone()
            return dict(row) if row else None

    # ── Audit Log ─────────────────────────────────────────────────────────────

    def _log_audit(self, user_id: int, action: str, entity_type: str,
                   entity_id: Optional[int], detail: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO audit_log (user_id, action, entity_type, entity_id, detail_json) VALUES (?,?,?,?,?)",
                (user_id, action, entity_type, entity_id, json.dumps(detail)),
            )
            conn.commit()

    def get_audit_log(self, page: int = 1, per_page: int = 100,
                      entity_type: str = "", entity_id: Optional[int] = None) -> dict:
        where = ["1=1"]
        params: list = []
        if entity_type:
            where.append("a.entity_type=?")
            params.append(entity_type)
        if entity_id is not None:
            where.append("a.entity_id=?")
            params.append(entity_id)
        where_sql = " AND ".join(where)
        offset = (page - 1) * per_page
        with self._connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM audit_log a WHERE {where_sql}", params).fetchone()[0]
            rows = conn.execute(
                f"""SELECT a.*, u.username
                    FROM audit_log a LEFT JOIN users u ON a.user_id=u.id
                    WHERE {where_sql}
                    ORDER BY a.timestamp DESC LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()
        return {"total": total, "page": page, "per_page": per_page, "items": [dict(r) for r in rows]}
