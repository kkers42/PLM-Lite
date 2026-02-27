"""
PLM Lite V1.0 — Relationships routes
"""
from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..database import Database
from ..models import MessageResponse, RelationshipCreate
from ..permissions import require_ability

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


def _db() -> Database:
    return Database()


@router.get("")
async def list_relationships(user: dict = Depends(require_ability("view"))):
    return _db().list_all_relationships()


@router.post("", status_code=201)
async def add_relationship(
    body: RelationshipCreate,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    if body.parent_part_id == body.child_part_id:
        raise HTTPException(400, "Parent and child cannot be the same part")
    if not db.get_part(body.parent_part_id):
        raise HTTPException(404, "Parent part not found")
    if not db.get_part(body.child_part_id):
        raise HTTPException(404, "Child part not found")
    if db.relationship_exists(body.parent_part_id, body.child_part_id):
        raise HTTPException(409, "Relationship already exists")
    return db.add_relationship(
        parent_id=body.parent_part_id,
        child_id=body.child_part_id,
        quantity=body.quantity,
        rel_type=body.relationship_type,
        notes=body.notes,
        user_id=user["id"],
    )


@router.delete("/{rel_id}")
async def delete_relationship(
    rel_id: int,
    user: dict = Depends(require_ability("write")),
):
    _db().delete_relationship(rel_id, user["id"])
    return MessageResponse(message="Relationship removed")


@router.get("/tree/{part_id}")
async def get_tree(part_id: int, user: dict = Depends(require_ability("view"))):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    return db.get_tree(part_id)
