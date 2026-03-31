"""PLM Lite v2.0 — Checkout engine.

Handles the filesystem side of checkout/checkin using .plmlock sidecar files.
The DB side is handled by database.Database; this module orchestrates both.
"""

import json
import shutil
import socket
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .database import Database

LOCK_SUFFIX = ".plmlock"
QUARANTINE_DIR = "_quarantine"


class CheckoutError(Exception):
    """Raised when a checkout/checkin operation cannot proceed."""


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _lock_path(stored_path: Path) -> Path:
    return stored_path.parent / (stored_path.name + LOCK_SUFFIX)


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def checkout_file(
    stored_path: Path,
    username: str,
    db: "Database",
    station: Optional[str] = None,
    dataset_id: int = 0,
    item_id: str = "",
    revision: str = "",
) -> Path:
    """Create .plmlock sidecar, register checkout in DB, write audit entry.

    Returns the path to the .plmlock file.
    Raises CheckoutError if already locked by a different user.
    """
    stored_path = Path(stored_path)
    lock = _lock_path(stored_path)
    station = station or socket.gethostname()

    # Conflict check on filesystem
    if lock.exists():
        info = get_lock_info(stored_path)
        if info and info.get("checked_out_by") != username:
            raise CheckoutError(
                f"Already locked by {info['checked_out_by']} "
                f"since {info.get('checked_out_at', '?')}"
            )
        # Same user re-checking-out: idempotent — just return existing lock
        return lock

    lock_data = {
        "checked_out_by": username,
        "checked_out_at": datetime.now().isoformat(timespec="seconds"),
        "station": station,
        "dataset_id": dataset_id,
        "item_id": item_id,
        "revision": revision,
    }
    lock.write_text(json.dumps(lock_data, indent=2), encoding="utf-8")

    try:
        db.checkout_dataset(dataset_id, username, station, str(lock))
    except Exception:
        # Roll back lock file if DB op failed
        if lock.exists():
            lock.unlink()
        raise

    db.write_audit(
        "checkout", "dataset", str(dataset_id), username,
        f"Checked out {stored_path.name} on {station}",
    )
    return lock


def checkin_file(stored_path: Path, username: str, db: "Database") -> None:
    """Remove .plmlock, release checkout in DB, write audit entry.

    Raises CheckoutError if the file is checked out by someone else.
    """
    stored_path = Path(stored_path)
    lock = _lock_path(stored_path)

    info = get_lock_info(stored_path)
    dataset_id = 0
    if info:
        locker = info.get("checked_out_by", "")
        if locker and locker != username:
            raise CheckoutError(
                f"Cannot check in: locked by {locker}, not {username}"
            )
        dataset_id = info.get("dataset_id", 0)

    if dataset_id:
        db.checkin_dataset(dataset_id, username)

    if lock.exists():
        lock.unlink()

    db.write_audit(
        "checkin", "dataset", str(dataset_id), username,
        f"Checked in {stored_path.name}",
    )


def is_locked(stored_path: Path) -> bool:
    """Return True if a .plmlock sidecar exists for this file."""
    return _lock_path(Path(stored_path)).exists()


def get_lock_info(stored_path: Path) -> Optional[dict]:
    """Return the contents of the .plmlock sidecar as a dict, or None."""
    lock = _lock_path(Path(stored_path))
    if not lock.exists():
        return None
    try:
        return json.loads(lock.read_text(encoding="utf-8"))
    except Exception:
        return None


def quarantine_unauthorized_save(stored_path: Path, db: "Database") -> Path:
    """Move a file saved while locked by another user into a quarantine folder.

    Returns the destination path inside the quarantine directory.
    """
    stored_path = Path(stored_path)
    q_dir = stored_path.parent / QUARANTINE_DIR
    q_dir.mkdir(exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = q_dir / f"{stored_path.stem}.quarantine.{ts}{stored_path.suffix}"
    shutil.move(str(stored_path), str(dest))

    db.write_audit(
        "quarantine", "file", stored_path.name, "system",
        f"Unauthorized save moved to quarantine: {dest.name}",
    )
    return dest
