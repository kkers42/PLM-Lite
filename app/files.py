"""
PLM Lite V1.0 — File storage, CAD versioning, restore
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import aiofiles
import aiofiles.os

from . import config
from .database import Database


def _ext_folder(filename: str) -> Path:
    """Return the subfolder for this file type, e.g. STL/, NX/, STEP/"""
    ext = Path(filename).suffix.lstrip(".").upper()
    folder_map = {
        "PRT": "NX", "ASM": "NX", "DRW": "NX",
        "SLDPRT": "SOLIDWORKS", "SLDASM": "SOLIDWORKS",
        "IPT": "INVENTOR", "IAM": "INVENTOR",
        "STEP": "STEP", "STP": "STEP",
        "STL": "STL", "3MF": "3MF", "OBJ": "OBJ",
    }
    folder = folder_map.get(ext, ext if ext else "OTHER")
    return config.FILES_ROOT / folder


def _version_label() -> str:
    """Returns _MMDD_HHMM string for backup filenames."""
    now = datetime.now()
    return now.strftime("_%m%d_%H%M")


async def save_upload(
    file_data: bytes,
    filename: str,
    part_id: int | None,
    description: str,
    user_id: int,
    db: Database,
) -> dict:
    """
    Save uploaded file, handle CAD versioning.
    Returns the document dict.
    """
    file_type = Path(filename).suffix.lstrip(".").lower()
    is_cad = config.is_cad_file(filename)
    dest_folder = _ext_folder(filename)
    dest_folder.mkdir(parents=True, exist_ok=True)
    god_path = dest_folder / filename

    if is_cad and part_id is not None:
        # Check if this part already has a doc with same filename
        existing_docs = db.list_documents(part_id)
        existing = next((d for d in existing_docs if d["filename"] == filename), None)

        if existing and god_path.exists():
            # Backup the current GOD file
            label = _version_label()
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            backup_name = f"{stem}{label}{suffix}"
            backup_path = dest_folder / backup_name

            # Copy current → backup
            shutil.copy2(str(god_path), str(backup_path))

            # Record version
            file_size = backup_path.stat().st_size
            db.add_file_version(
                existing["id"], label, str(backup_path), file_size, user_id
            )

            # Rotate: keep only MAX_FILE_VERSIONS backups
            old_versions = db.get_old_versions(existing["id"], config.MAX_FILE_VERSIONS)
            for old in old_versions:
                old_file = Path(old["backup_path"])
                if old_file.exists():
                    old_file.unlink(missing_ok=True)
                db.delete_file_version(old["id"])

    # Write the new GOD file
    async with aiofiles.open(str(god_path), "wb") as f:
        await f.write(file_data)

    # Upsert document record
    if is_cad and part_id is not None:
        existing_docs = db.list_documents(part_id)
        existing = next((d for d in existing_docs if d["filename"] == filename), None)
        if existing:
            return existing  # doc record stays, file replaced on disk

    return db.create_document(
        filename=filename,
        stored_path=str(god_path),
        file_type=file_type,
        description=description,
        uploaded_by=user_id,
        part_id=part_id,
    )


async def restore_version(doc_id: int, version_id: int, user_id: int, db: Database) -> None:
    """
    Restore a backup version as the GOD file.
    Current GOD file is moved to Temp/.
    """
    doc = db.get_document(doc_id)
    version = db.get_file_version(version_id)
    if not doc or not version:
        raise FileNotFoundError("Document or version not found")

    god_path = Path(doc["stored_path"])
    backup_path = Path(version["backup_path"])

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file missing: {backup_path}")

    # Move current GOD → Temp
    temp_dir = config.FILES_ROOT / "Temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    if god_path.exists():
        now = datetime.now().strftime("%m%d_%H%M%S")
        temp_dest = temp_dir / f"{god_path.stem}_{now}{god_path.suffix}"
        shutil.move(str(god_path), str(temp_dest))

    # Copy backup → GOD
    shutil.copy2(str(backup_path), str(god_path))


def get_file_path(stored_path: str) -> Path:
    """Validate and return a safe path for download."""
    p = Path(stored_path).resolve()
    root = config.FILES_ROOT.resolve()
    if not str(p).startswith(str(root)):
        raise PermissionError("Path traversal detected")
    return p
