"""
PLM Lite V1.0 — Admin routes (roles, audit log, attribute keys)
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import Database
from ..models import MessageResponse, RoleCreate, RoleUpdate
from ..permissions import require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _db() -> Database:
    return Database()


# ── Roles ─────────────────────────────────────────────────────────────────────

@router.get("/roles")
async def list_roles(admin: dict = Depends(require_admin)):
    return _db().list_roles()


@router.post("/roles", status_code=201)
async def create_role(body: RoleCreate, admin: dict = Depends(require_admin)):
    db = _db()
    existing = [r for r in db.list_roles() if r["name"].lower() == body.name.lower()]
    if existing:
        raise HTTPException(409, "Role name already exists")
    return db.create_role(body.name, body.model_dump())


@router.put("/roles/{role_id}")
async def update_role(role_id: int, body: RoleUpdate, admin: dict = Depends(require_admin)):
    db = _db()
    if not db.get_role(role_id):
        raise HTTPException(404, "Role not found")
    db.update_role(role_id, body.name, body.model_dump())
    return db.get_role(role_id)


@router.delete("/roles/{role_id}")
async def delete_role(role_id: int, admin: dict = Depends(require_admin)):
    db = _db()
    role = db.get_role(role_id)
    if not role:
        raise HTTPException(404, "Role not found")
    if role["name"] == "Admin":
        raise HTTPException(400, "Cannot delete the Admin role")
    db.delete_role(role_id)
    return MessageResponse(message="Role deleted")


# ── Audit log ─────────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit(
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    entity_type: str = Query(""),
    admin: dict = Depends(require_admin),
):
    return _db().get_audit_log(page=page, per_page=per_page, entity_type=entity_type)


# ── Attribute keys ─────────────────────────────────────────────────────────────

@router.get("/attributes/keys")
async def attribute_keys(admin: dict = Depends(require_admin)):
    return _db().list_attribute_keys()
