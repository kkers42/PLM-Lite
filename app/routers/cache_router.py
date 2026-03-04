"""
PLM Lite V1.1.0 — Cache session and manifest sidecar routes
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from ..database import Database
from ..permissions import require_ability, require_admin

router = APIRouter(tags=["cache"])


def _db() -> Database:
    return Database()


# ── Cache Sessions ────────────────────────────────────────────────────────────

@router.get("/api/cache/sessions")
async def list_cache_sessions(admin: dict = Depends(require_admin)):
    """List all active NX workstation agent sessions."""
    db = _db()
    with db._connect() as con:
        rows = con.execute(
            """
            SELECT cs.id, cs.session_id, cs.nx_version, cs.station_name,
                   cs.started_at, cs.last_ping, cs.status,
                   u.username
            FROM cache_sessions cs
            LEFT JOIN users u ON u.id = cs.user_id
            ORDER BY cs.last_ping DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.delete("/api/cache/sessions/{session_id}")
async def close_cache_session(session_id: int, admin: dict = Depends(require_admin)):
    """Mark a cache session as closed (does not kill the agent process)."""
    db = _db()
    with db._connect() as con:
        row = con.execute(
            "SELECT id FROM cache_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        con.execute(
            "UPDATE cache_sessions SET status = 'closed' WHERE id = ?",
            (session_id,)
        )
    return {"message": "Session closed", "id": session_id}


@router.post("/api/cache/ping")
async def agent_ping(body: dict):
    """
    Called by the workstation agent to register / keep-alive a session.
    Body: {session_id, nx_version, station_name, user_id}
    No auth required — agent runs locally, only accessible from localhost.
    """
    session_id   = body.get("session_id", "")
    nx_version   = body.get("nx_version", "")
    station_name = body.get("station_name", "")
    user_id      = body.get("user_id")

    if not session_id:
        raise HTTPException(400, "session_id required")

    now = datetime.utcnow().isoformat()
    db = _db()
    with db._connect() as con:
        existing = con.execute(
            "SELECT id FROM cache_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            con.execute(
                "UPDATE cache_sessions SET last_ping = ?, status = 'active' WHERE session_id = ?",
                (now, session_id)
            )
        else:
            con.execute(
                """INSERT INTO cache_sessions
                   (session_id, nx_version, station_name, user_id, started_at, last_ping, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'active')""",
                (session_id, nx_version, station_name, user_id, now, now)
            )
    return {"ok": True}


# ── Manifest Sidecars ─────────────────────────────────────────────────────────

@router.get("/api/parts/{part_id}/manifest")
async def get_manifest(
    part_id: int,
    user: dict = Depends(require_ability("view")),
):
    """Return manifest sidecar metadata for the most recent CAD document on this part."""
    db = _db()
    with db._connect() as con:
        row = con.execute(
            """
            SELECT ms.id, ms.manifest_path, ms.generated_at, ms.nx_version, ms.part_count,
                   d.filename
            FROM manifest_sidecars ms
            JOIN documents d ON d.id = ms.document_id
            WHERE d.part_id = ?
            ORDER BY ms.generated_at DESC
            LIMIT 1
            """,
            (part_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "No manifest found for this part")
    return dict(row)


@router.post("/api/parts/{part_id}/manifest")
async def upsert_manifest(
    part_id: int,
    body: dict,
    user: dict = Depends(require_ability("write")),
):
    """
    Create or update the manifest sidecar for a part's CAD document.
    Body: {document_id, manifest_path, nx_version, part_count}
    """
    document_id   = body.get("document_id")
    manifest_path = body.get("manifest_path", "")
    nx_version    = body.get("nx_version", "")
    part_count    = int(body.get("part_count", 0))

    if not document_id or not manifest_path:
        raise HTTPException(400, "document_id and manifest_path required")

    now = datetime.utcnow().isoformat()
    db = _db()
    with db._connect() as con:
        # Verify document belongs to this part
        doc = con.execute(
            "SELECT id FROM documents WHERE id = ? AND part_id = ?",
            (document_id, part_id)
        ).fetchone()
        if not doc:
            raise HTTPException(404, "Document not found on this part")

        # Delete old manifest for this document and insert fresh
        con.execute("DELETE FROM manifest_sidecars WHERE document_id = ?", (document_id,))
        con.execute(
            """INSERT INTO manifest_sidecars
               (document_id, manifest_path, generated_at, nx_version, part_count)
               VALUES (?, ?, ?, ?, ?)""",
            (document_id, manifest_path, now, nx_version, part_count)
        )
        row_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {"id": row_id, "document_id": document_id, "manifest_path": manifest_path, "generated_at": now}
