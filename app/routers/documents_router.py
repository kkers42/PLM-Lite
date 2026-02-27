"""
PLM Lite V1.0 — Documents routes
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..auth import get_current_user
from ..database import Database
from ..files import get_file_path, restore_version, save_upload
from ..models import MessageResponse
from ..permissions import require_ability

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _db() -> Database:
    return Database()


@router.get("")
async def list_documents(
    part_id: Optional[int] = Query(None),
    user: dict = Depends(require_ability("view")),
):
    return _db().list_documents(part_id)


@router.post("", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    part_id: Optional[int] = Form(None),
    description: str = Form(""),
    user: dict = Depends(require_ability("upload")),
):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    db = _db()
    doc = await save_upload(
        file_data=data,
        filename=file.filename,
        part_id=part_id,
        description=description,
        user_id=user["id"],
        db=db,
    )
    return doc


@router.get("/{doc_id}/download")
async def download_document(
    doc_id: int,
    user: dict = Depends(require_ability("view")),
):
    db = _db()
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    try:
        fpath = get_file_path(doc["stored_path"])
    except PermissionError:
        raise HTTPException(400, "Invalid file path")
    if not fpath.exists():
        raise HTTPException(404, "File not found on disk")
    return FileResponse(path=str(fpath), filename=doc["filename"])


@router.get("/{doc_id}")
async def get_document(doc_id: int, user: dict = Depends(require_ability("view"))):
    doc = _db().get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: int,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    stored_path = db.delete_document(doc_id, user["id"])
    if stored_path:
        p = Path(stored_path)
        if p.exists():
            p.unlink(missing_ok=True)
    return MessageResponse(message="Document deleted")


@router.get("/{doc_id}/versions")
async def list_versions(doc_id: int, user: dict = Depends(require_ability("view"))):
    return _db().list_file_versions(doc_id)


@router.post("/{doc_id}/restore/{version_id}")
async def restore_doc_version(
    doc_id: int,
    version_id: int,
    user: dict = Depends(require_ability("write")),
):
    db = _db()
    try:
        await restore_version(doc_id, version_id, user["id"], db)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return MessageResponse(message="Version restored")
