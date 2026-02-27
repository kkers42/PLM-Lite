"""
PLM Lite V1.0 — Parts routes
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
import io

from ..auth import get_current_user
from ..database import Database
from ..export import generate_bom_excel
from ..models import (
    AttributeSet, CheckoutRequest, MessageResponse,
    PartCreate, PartUpdate, RevisionCreate,
)
from ..permissions import require_ability, require_admin

router = APIRouter(prefix="/api/parts", tags=["parts"])


def _db() -> Database:
    return Database()


# ── List / Search ─────────────────────────────────────────────────────────────

@router.get("")
async def list_parts(
    search: str = Query(""),
    status: str = Query(""),
    checked_out_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_ability("view")),
):
    return _db().list_parts(search=search, status=status, checked_out_only=checked_out_only,
                             page=page, per_page=per_page)


# ── Create ────────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
async def create_part(
    body: PartCreate,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    if db.get_part_by_number(body.part_number):
        raise HTTPException(409, f"Part number '{body.part_number}' already exists")
    return db.create_part(body.model_dump(), user["id"])


# ── Get detail ────────────────────────────────────────────────────────────────

@router.get("/{part_id}")
async def get_part(part_id: int, user: dict = Depends(require_ability("view"))):
    part = _db().get_part(part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    return part


# ── Update ────────────────────────────────────────────────────────────────────

@router.put("/{part_id}")
async def update_part(
    part_id: int,
    body: PartUpdate,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    part = db.get_part(part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    if part.get("is_locked"):
        raise HTTPException(423, "Part is locked (Released). Use 'Unreleased' to edit.")
    db.update_part(part_id, body.model_dump(), user["id"])
    return db.get_part(part_id)


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{part_id}")
async def delete_part(
    part_id: int,
    user: dict = Depends(require_admin),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    db.delete_part(part_id, user["id"])
    return MessageResponse(message="Part deleted")


# ── Checkout / Checkin ────────────────────────────────────────────────────────

@router.post("/{part_id}/checkout")
async def checkout(
    part_id: int,
    body: CheckoutRequest,
    user: dict = Depends(require_ability("checkout")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    ok = db.checkout_part(part_id, user["id"], body.station)
    if not ok:
        raise HTTPException(409, "Part is already checked out")
    return db.get_part(part_id)


@router.post("/{part_id}/checkin")
async def checkin(
    part_id: int,
    user: dict = Depends(require_ability("checkout")),
):
    db = _db()
    part = db.get_part(part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    if part.get("checked_out_by") != user["id"] and not user.get("can_admin"):
        raise HTTPException(403, "You can only check in parts you have checked out")
    db.checkin_part(part_id, user["id"])
    return db.get_part(part_id)


# ── Release / Unreleased ─────────────────────────────────────────────────────

@router.post("/{part_id}/release")
async def release_part(
    part_id: int,
    user: dict = Depends(require_ability("release")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    db.release_part(part_id, user["id"])
    return db.get_part(part_id)


@router.post("/{part_id}/unreleased")
async def unrelease_part(
    part_id: int,
    user: dict = Depends(require_ability("release")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    db.unrelease_part(part_id, user["id"])
    return db.get_part(part_id)


# ── Revisions ─────────────────────────────────────────────────────────────────

@router.post("/{part_id}/revise")
async def bump_revision(
    part_id: int,
    body: RevisionCreate,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    new_rev = db.bump_revision(part_id, user["id"], body.description)
    return {"message": f"Revision bumped to {new_rev}", "new_revision": new_rev}


@router.get("/{part_id}/revisions")
async def list_revisions(part_id: int, user: dict = Depends(require_ability("view"))):
    return _db().list_revisions(part_id)


# ── Attributes ────────────────────────────────────────────────────────────────

@router.get("/{part_id}/attributes")
async def get_attributes(part_id: int, user: dict = Depends(require_ability("view"))):
    return _db().get_attributes(part_id)


@router.put("/{part_id}/attributes")
async def set_attribute(
    part_id: int,
    body: AttributeSet,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    db.set_attribute(part_id, body.key, body.value, body.order)
    return db.get_attributes(part_id)


@router.delete("/{part_id}/attributes/{key}")
async def delete_attribute(
    part_id: int,
    key: str,
    user: dict = Depends(require_ability("write")),
):
    _db().delete_attribute(part_id, key)
    return MessageResponse(message="Attribute removed")


# ── Where-used / BOM ─────────────────────────────────────────────────────────

@router.get("/{part_id}/where-used")
async def where_used(part_id: int, user: dict = Depends(require_ability("view"))):
    return _db().get_parents(part_id)


@router.get("/{part_id}/bom")
async def get_bom(part_id: int, user: dict = Depends(require_ability("view"))):
    db = _db()
    part = db.get_part(part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    return {"root": part, "items": db.get_bom_flat(part_id)}


@router.get("/{part_id}/bom/export")
async def export_bom(part_id: int, user: dict = Depends(require_ability("view"))):
    db = _db()
    part = db.get_part(part_id)
    if not part:
        raise HTTPException(404, "Part not found")
    bom_rows = db.get_bom_flat(part_id)
    xlsx_bytes = generate_bom_excel(part, bom_rows)
    filename = f"BOM_{part['part_number']}_Rev{part['part_revision']}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Documents ─────────────────────────────────────────────────────────────────

@router.get("/{part_id}/documents")
async def list_part_docs(part_id: int, user: dict = Depends(require_ability("view"))):
    return _db().list_documents(part_id)


@router.post("/{part_id}/documents/{doc_id}")
async def attach_doc(
    part_id: int,
    doc_id: int,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    if not db.get_part(part_id):
        raise HTTPException(404, "Part not found")
    if not db.get_document(doc_id):
        raise HTTPException(404, "Document not found")
    db.attach_document(part_id, doc_id)
    return MessageResponse(message="Document attached")


@router.delete("/{part_id}/documents/{doc_id}")
async def detach_doc(
    part_id: int,
    doc_id: int,
    user: dict = Depends(require_ability("write")),
):
    _db().detach_document(doc_id)
    return MessageResponse(message="Document detached")
