"""
PLM Lite V1.0 — Documents routes
"""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse

from .. import config
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


@router.get("/{doc_id}/open")
async def open_document_inplace(
    doc_id: int,
    user: dict = Depends(require_ability("view")),
):
    """
    Return a Windows .url shortcut file that opens the file directly from the
    network share (UNC path) — no download, file stays on the server.
    Requires FILES_UNC_ROOT to be configured in .env.
    """
    if not config.FILES_UNC_ROOT:
        raise HTTPException(501, "Open-in-place not configured (FILES_UNC_ROOT not set)")

    db = _db()
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    # Build UNC path: replace the server-side FILES_ROOT prefix with the UNC root
    stored = Path(doc["stored_path"])
    files_root = config.FILES_ROOT.resolve()
    try:
        rel = stored.resolve().relative_to(files_root)
    except ValueError:
        raise HTTPException(400, "Stored path is outside FILES_ROOT")

    # Convert forward slashes to backslashes for UNC
    unc_root = config.FILES_UNC_ROOT.rstrip("/").rstrip("\\")
    rel_parts = str(rel).replace("/", "\\")
    unc_path = f"{unc_root}\\{rel_parts}"

    # Windows .url shortcut format — double-clicking opens in associated app
    shortcut = f"[InternetShortcut]\r\nURL=file:///{unc_path.replace(chr(92), '/')}\r\n"

    safe_name = doc["filename"].replace('"', "")
    return PlainTextResponse(
        content=shortcut,
        media_type="application/x-mswinurl",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.url"'},
    )


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
