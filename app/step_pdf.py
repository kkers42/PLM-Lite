"""Publish a derived viewing PDF from the current bytes of a STEP attachment."""
from hashlib import sha256
import json
import logging
import os
import re
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

from fastapi import HTTPException
from pypdf import PdfReader

from . import config
from .files import get_file_path

logger = logging.getLogger(__name__)

MAX_STEP_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 32 * 1024 * 1024


def _source_bytes(document):
    try:
        path = get_file_path(document["stored_path"])
        with path.open("rb") as source:
            data = source.read(MAX_STEP_BYTES + 1)
    except OSError as exc:
        raise HTTPException(404, "STEP attachment is unavailable") from exc
    if len(data) > MAX_STEP_BYTES:
        raise HTTPException(413, "STEP attachment exceeds the 16 MiB publishing limit")
    if not data.lstrip().startswith(b"ISO-10303-21;"):
        raise HTTPException(422, "Attachment is not a STEP exchange file")
    return data


def _require_unlocked(part):
    if part["is_locked"]:
        raise HTTPException(423, "Part is locked (Released). Unrelease it to publish.")


def _validate_pdf(path):
    if not 0 < path.stat().st_size <= MAX_PDF_BYTES:
        raise ValueError("PDF is empty or too large")
    with path.open("rb") as stream:
        for page in PdfReader(stream, strict=True).pages:
            for reference in page.get("/Annots", []):
                annotation = reference.get_object()
                if annotation.get("/Subtype") != "/3D":
                    continue
                model = annotation["/3DD"]
                signature = {"/PRC": b"PRC", "/U3D": b"U3D\0"}.get(model.get("/Subtype"))
                if signature and model.get_data().startswith(signature):
                    return
    raise ValueError("PDF has no supported embedded 3D model")


def publish_step_pdf(db, doc_id, user_id):
    if not config.STEP_PDF_CONVERTER:
        raise HTTPException(503, "3D PDF publishing is not configured")

    document = db.get_document(doc_id)
    if not document or not document["part_id"]:
        raise HTTPException(404, "Part attachment not found")
    if Path(document["filename"]).suffix.lower() not in {".step", ".stp"}:
        raise HTTPException(415, "Select a STEP attachment")
    part = db.get_part(document["part_id"])
    if not part:
        raise HTTPException(404, "Part not found")
    _require_unlocked(part)

    data = _source_bytes(document)
    source_hash = sha256(data).hexdigest()
    revision = part["part_revision"]
    part_label = re.sub(r"[^A-Za-z0-9_-]", "_", part["part_number"])[:36]
    revision_label = re.sub(r"[^A-Za-z0-9_-]", "_", revision)[:16]
    revision_hash = sha256(revision.encode()).hexdigest()[:16]
    filename = f"{part_label}-rev-{revision_label}-step-{doc_id}-{revision_hash}-{source_hash[:16]}-3d.pdf"
    folder = config.FILES_ROOT.resolve() / "PDF" / "published" / str(part["id"])
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / filename
    description = f"3D PDF · Revision {revision} · STEP attachment {doc_id} · SHA-256 {source_hash}"

    with TemporaryDirectory(prefix="step-pdf-", dir=folder) as temporary:
        source = Path(temporary) / "source.step"
        output = Path(temporary) / "model.pdf"
        source.write_bytes(data)
        try:
            subprocess.run(
                [config.STEP_PDF_CONVERTER, str(source), str(output)],
                cwd=temporary, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=45, check=True,
                env={**os.environ, "STEP_PDF_TITLE": f"{part_label} | Revision {revision_label}",
                     "TMPDIR": temporary},
            )
            _validate_pdf(output)
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(504, "3D PDF conversion timed out") from exc
        except FileNotFoundError as exc:
            logger.warning("STEP PDF converter or output missing", exc_info=True)
            raise HTTPException(503, "3D PDF converter or output is unavailable") from exc
        except Exception as exc:
            logger.warning("STEP PDF conversion failed", exc_info=True)
            raise HTTPException(422, "Could not generate a valid 3D PDF from this STEP file") from exc

        with db._connect() as conn:
            # Serialize the final revision check and derived-document insert.
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM parts WHERE id=?", (part["id"],)).fetchone()
            attachment = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if (not current or current["part_revision"] != revision or
                    not attachment or dict(attachment) != document or
                    sha256(_source_bytes(attachment)).hexdigest() != source_hash):
                raise HTTPException(409, "The part or STEP attachment changed during publishing")
            _require_unlocked(current)
            existing = conn.execute(
                "SELECT * FROM documents WHERE stored_path=?", (str(destination),)
            ).fetchone()
            if existing and existing["part_id"] != part["id"]:
                raise HTTPException(409, "The previous PDF was moved to another attachment list")
            if existing and destination.is_file():
                return dict(existing)

            output.replace(destination)
            try:
                if existing:
                    result = dict(existing)
                else:
                    cursor = conn.execute(
                        """INSERT INTO documents
                           (part_id, filename, stored_path, file_type, description, uploaded_by)
                           VALUES (?, ?, ?, 'pdf', ?, ?)""",
                        (part["id"], filename, str(destination), description, user_id),
                    )
                    result = dict(conn.execute(
                        "SELECT * FROM documents WHERE id=?", (cursor.lastrowid,)
                    ).fetchone())
                    conn.execute(
                        """INSERT INTO audit_log
                           (user_id, action, entity_type, entity_id, detail_json)
                           VALUES (?, 'publish_3d_pdf', 'document', ?, ?)""",
                        (user_id, result["id"], json.dumps({
                            "part_id": part["id"], "revision": revision,
                            "source_document_id": doc_id, "source_sha256": source_hash,
                        })),
                    )
                conn.commit()
            except Exception:
                destination.unlink(missing_ok=True)
                raise
            return result
