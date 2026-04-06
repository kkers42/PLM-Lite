"""PLM Lite v2.2 — Checkout engine.

Vault-based checkout/checkin workflow.
- Files live permanently in VAULT_PATH/{revision}/{filename} (read-only).
  All datasets at the same revision label share one folder — filenames are
  unique across the entire vault.
- On checkout: file is copied to C:\\Users\\{username}\\PLMTemp\\ (writable).
- On checkin: temp file is copied back to vault (read-only), checkout cleared.
- No .plmlock sidecar files. Locking is DB-only.
- Children of the checked-out item are also copied to temp as read-only.
"""

import logging
import os
import shutil
import socket
import stat
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional

if TYPE_CHECKING:
    from .database import Database

from .database import CheckoutError  # re-export so callers get one canonical error
from . import config

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def get_temp_dir(username: str) -> Path:
    """Return (and create) C:\\Users\\{username}\\PLMTemp\\."""
    temp_dir = config.TEMP_BASE_PATH
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _set_readonly(path: Path) -> None:
    """Make a file read-only (remove write bits). Best-effort on network shares."""
    try:
        current = os.stat(path).st_mode
        new_mode = current & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH
        os.chmod(path, new_mode)
    except OSError:
        pass


def _set_writable(path: Path) -> None:
    """Make a file writable (add user write bit). Best-effort."""
    try:
        current = os.stat(path).st_mode
        new_mode = current | stat.S_IWRITE
        os.chmod(path, new_mode)
    except OSError:
        pass


# ------------------------------------------------------------------
# Checkout
# ------------------------------------------------------------------

def checkout_file(
    dataset: dict,
    item_id_str: str,
    revision: str,
    username: str,
    db: "Database",
) -> Path:
    """Copy vault master to user temp dir (writable), register DB checkout.

    Returns the temp file path.
    Raises CheckoutError if already checked out by someone else or file missing.
    """
    vault_path = Path(dataset["stored_path"])
    temp_dir   = get_temp_dir(username)
    temp_path  = temp_dir / dataset["filename"]

    # Existing checkout check
    existing = db.get_checkout(dataset["id"])
    if existing:
        if existing["who"] == username:
            # Idempotent — already checked out by this user
            return temp_path
        raise CheckoutError(
            f"{dataset['filename']} is already checked out by {existing['who']}"
        )

    # Block checkout of released/locked revisions
    rev_row = db.get_revision_by_path(dataset["id"])
    if rev_row and rev_row.get("status") in ("released", "locked"):
        raise CheckoutError(
            f"Cannot check out: revision is {rev_row['status']}"
        )

    if not vault_path.exists():
        raise CheckoutError(f"Vault file not found: {vault_path}")

    # Copy vault → temp
    shutil.copy2(str(vault_path), str(temp_path))
    _set_writable(temp_path)

    # Keep vault read-only (belt-and-suspenders)
    _set_readonly(vault_path)

    # DB: create checkout record
    station = os.environ.get("COMPUTERNAME", socket.gethostname())
    db.checkout_dataset(dataset["id"], username, station, str(temp_path))

    # DB: create temp_file record
    checkout_rec = db.get_checkout(dataset["id"])
    checkout_id  = checkout_rec["id"] if checkout_rec else None
    db.add_temp_file(checkout_id, dataset["id"], username, str(temp_path), True)

    db.write_audit(
        "checkout", "dataset", str(dataset["id"]), username,
        f"Checked out {dataset['filename']} → {temp_path}",
    )
    logger.info("Checked out %s → %s", dataset["filename"], temp_path)
    return temp_path


# ------------------------------------------------------------------
# Copy children
# ------------------------------------------------------------------

def _pick_revision(revisions: list, rule: str) -> Optional[dict]:
    """Pick a revision from a list based on the assembly rev rule."""
    if not revisions:
        return None
    if rule == "latest_released":
        for r in reversed(revisions):
            if r["status"] == "released":
                return r
        return None  # no released rev — don't load
    elif rule == "latest_working":
        for r in reversed(revisions):
            if r["status"] == "in_work":
                return r
        # Fall back to latest released if no in_work
        for r in reversed(revisions):
            if r["status"] == "released":
                return r
        return None
    else:  # latest_created — newest regardless of status
        return revisions[-1]


def copy_children_to_temp(
    item_pk: int,
    username: str,
    db: "Database",
    exclude_dataset_ids: set,
    _visited: Optional[set] = None,
    rev_rule: Optional[str] = None,
) -> List[str]:
    """Recursively copy child-item vault files to user temp as read-only.

    Returns list of temp paths copied.
    """
    if rev_rule is None:
        from . import config as _cfg
        rev_rule = _cfg.ASSEMBLY_REV_RULE

    if _visited is None:
        _visited = set()
    if item_pk in _visited:
        return []
    _visited.add(item_pk)

    temp_dir = get_temp_dir(username)
    copied: List[str] = []

    for child in db.get_children(item_pk):
        revisions = db.get_revisions(child["id"])
        rev = _pick_revision(revisions, rev_rule)
        if not rev:
            continue

        for ds in db.get_datasets(rev["id"]):
            if ds["id"] in exclude_dataset_ids:
                continue  # already handled (the checked-out assembly itself)

            existing_co = db.get_checkout(ds["id"])
            temp_path = temp_dir / ds["filename"]

            if existing_co and existing_co["who"] == username:
                # Child is checked out by ME — ensure writable temp exists
                co_temp = Path(existing_co.get("temp_path") or "")
                # Normalise: always use temp_dir / filename as canonical path
                if not co_temp.exists():
                    vault_path = Path(ds["stored_path"])
                    if vault_path.exists():
                        if temp_path.exists():
                            _set_writable(temp_path)
                        shutil.copy2(str(vault_path), str(temp_path))
                        _set_writable(temp_path)
                        # Update checkout record so watcher uses correct path
                        with db._connect() as conn:
                            conn.execute(
                                "UPDATE checkouts SET temp_path=? WHERE id=?",
                                (str(temp_path), existing_co["id"]),
                            )
                            conn.commit()
                        copied.append(str(temp_path))
                continue

            # Not checked out by me (either checked out by someone else, or free)
            # Copy from vault as read-only
            vault_path = Path(ds["stored_path"])
            if not vault_path.exists():
                logger.warning("Child vault file not found, skipping: %s", vault_path)
                continue

            try:
                if temp_path.exists():
                    _set_writable(temp_path)
                shutil.copy2(str(vault_path), str(temp_path))
                _set_readonly(temp_path)
                db.delete_temp_file_for_dataset(ds["id"], username)
                db.add_temp_file(None, ds["id"], username, str(temp_path), False)
                copied.append(str(temp_path))
                logger.debug("Copied child %s → temp (read-only)", ds["filename"])
            except Exception:
                logger.exception("Failed to copy child %s to temp", ds["filename"])

        # Recurse into child's children
        copied.extend(
            copy_children_to_temp(
                child["id"], username, db, exclude_dataset_ids, _visited, rev_rule
            )
        )

    return copied


# ------------------------------------------------------------------
# Check in
# ------------------------------------------------------------------

def checkin_file(
    dataset: dict,
    item_id_str: str,
    revision: str,
    username: str,
    db: "Database",
) -> None:
    """Copy temp → vault, delete checkout record and temp file.

    Raises CheckoutError if no matching checkout exists.
    """
    checkout = db.get_checkout(dataset["id"])
    if not checkout:
        raise CheckoutError(f"{dataset['filename']} is not checked out")
    if checkout["who"] != username:
        raise CheckoutError(
            f"Cannot check in: {dataset['filename']} is checked out by {checkout['who']}"
        )

    temp_str = checkout.get("temp_path", "")
    temp_path = Path(temp_str) if temp_str else get_temp_dir(username) / dataset["filename"]
    if not temp_path.exists():
        raise CheckoutError(f"Temp file not found: {temp_path}")

    vault_path = Path(dataset["stored_path"])
    vault_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy temp → vault
    _set_writable(vault_path)
    shutil.copy2(str(temp_path), str(vault_path))
    _set_readonly(vault_path)

    # Update file size in DB
    db.update_dataset_size(dataset["id"], vault_path.stat().st_size)

    # DB: delete checkout (cascades to temp_files with this checkout_id)
    db.checkin_dataset(dataset["id"], username)

    # Delete temp file from disk
    try:
        temp_path.unlink()
    except OSError:
        logger.warning("Could not delete temp file: %s", temp_path)

    # Belt-and-suspenders: remove any orphaned temp_file records
    db.delete_temp_file_for_dataset(dataset["id"], username)

    db.write_audit(
        "checkin", "dataset", str(dataset["id"]), username,
        f"Checked in {dataset['filename']}",
    )
    logger.info("Checked in %s → %s", dataset["filename"], vault_path)


# ------------------------------------------------------------------
# Disk save (keep checkout active)
# ------------------------------------------------------------------

def disk_save(
    dataset: dict,
    item_id_str: str,
    revision: str,
    username: str,
    db: "Database",
) -> None:
    """Copy temp → vault without releasing the checkout.

    The user stays checked out; the vault is updated with the current temp content.
    """
    checkout = db.get_checkout(dataset["id"])
    if not checkout:
        raise CheckoutError(f"{dataset['filename']} is not checked out")
    if checkout["who"] != username:
        raise CheckoutError(
            f"Cannot save: {dataset['filename']} is checked out by {checkout['who']}"
        )

    temp_str = checkout.get("temp_path", "")
    temp_path = Path(temp_str) if temp_str else get_temp_dir(username) / dataset["filename"]
    if not temp_path.exists():
        raise CheckoutError(f"Temp file not found: {temp_path}")

    vault_path = Path(dataset["stored_path"])
    vault_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy temp → vault
    _set_writable(vault_path)
    shutil.copy2(str(temp_path), str(vault_path))
    _set_readonly(vault_path)

    # Update file size
    db.update_dataset_size(dataset["id"], vault_path.stat().st_size)

    db.write_audit(
        "disk_save", "dataset", str(dataset["id"]), username,
        f"Disk save {dataset['filename']} (checkout retained)",
    )
    logger.info("Disk save %s → %s (checkout retained)", dataset["filename"], vault_path)


# ------------------------------------------------------------------
# Save as new revision
# ------------------------------------------------------------------

def save_as_new_revision(
    dataset: dict,
    item: dict,
    current_revision: dict,
    username: str,
    db: "Database",
    change_description: str = "",
    revision_type: Optional[str] = None,
) -> dict:
    """Save temp file as a new revision. Old checkout is released; new checkout opened.

    Returns the new revision dict {"revision": label, "id": rev_pk}.
    """
    checkout = db.get_checkout(dataset["id"])
    if not checkout:
        raise CheckoutError(f"{dataset['filename']} is not checked out")
    if checkout["who"] != username:
        raise CheckoutError(
            f"Cannot save: {dataset['filename']} is checked out by {checkout['who']}"
        )

    temp_str = checkout.get("temp_path", "")
    temp_path = Path(temp_str) if temp_str else get_temp_dir(username) / dataset["filename"]
    if not temp_path.exists():
        raise CheckoutError(f"Temp file not found: {temp_path}")

    rtype = revision_type or current_revision.get("revision_type", "alpha")

    # Compute next revision label
    new_rev_label = db.next_revision(item["id"], rtype)

    # Create new revision record
    new_rev_pk = db.create_revision(item["id"], new_rev_label, rtype, username)
    if change_description:
        db.update_revision_description(new_rev_pk, change_description)

    # Create new vault directory and copy file (flat by revision label)
    new_vault_dir = config.VAULT_PATH / new_rev_label
    new_vault_dir.mkdir(parents=True, exist_ok=True)
    new_vault_path = new_vault_dir / dataset["filename"]
    shutil.copy2(str(temp_path), str(new_vault_path))
    _set_readonly(new_vault_path)

    # Create new dataset record under new revision
    file_size = new_vault_path.stat().st_size
    new_ds_pk = db.add_dataset(
        new_rev_pk, dataset["filename"], dataset.get("file_type", ""),
        str(new_vault_path), file_size, username,
    )

    # Release old checkout (cascades to temp_files for old checkout_id)
    db.checkin_dataset(dataset["id"], username)

    # Create new checkout for new dataset (same temp file)
    station = os.environ.get("COMPUTERNAME", socket.gethostname())
    db.checkout_dataset(new_ds_pk, username, station, str(temp_path))
    new_checkout = db.get_checkout(new_ds_pk)
    new_checkout_id = new_checkout["id"] if new_checkout else None

    # Register temp file against new dataset/checkout
    db.add_temp_file(new_checkout_id, new_ds_pk, username, str(temp_path), True)

    db.write_audit(
        "save_as_new_revision", "item_revision", str(new_rev_pk), username,
        f"Saved {dataset['filename']} as new revision {new_rev_label}",
    )
    logger.info("Saved %s as revision %s", dataset["filename"], new_rev_label)
    return {"revision": new_rev_label, "id": new_rev_pk}


# ------------------------------------------------------------------
# Cleanup user temp
# ------------------------------------------------------------------

def cleanup_user_temp(
    username: str,
    db: "Database",
    force: bool = False,
) -> dict:
    """Delete all temp files for a user.

    If force=False and there are modified (unsaved) files, returns early with
    has_unsaved=True and a list of the unsaved filenames.
    If force=True or no unsaved files, deletes everything and returns has_unsaved=False.
    """
    temp_files = db.get_temp_files_for_user(username)
    temp_dir   = get_temp_dir(username)

    # Identify modified checked-out files (temp newer than vault)
    unsaved = []
    for tf in temp_files:
        if not tf.get("is_checked_out"):
            continue
        t = Path(tf["temp_path"])
        v = Path(tf.get("stored_path", ""))
        if t.exists() and v.exists():
            try:
                if t.stat().st_mtime > v.stat().st_mtime:
                    unsaved.append(tf["filename"])
            except OSError:
                pass

    if unsaved and not force:
        return {"has_unsaved": True, "checked_out_files": unsaved}

    # Delete all temp files from disk
    for tf in temp_files:
        try:
            Path(tf["temp_path"]).unlink(missing_ok=True)
        except OSError:
            pass

    # Clean DB records
    db.delete_temp_files_for_user(username)

    logger.info("Cleaned up temp files for %s", username)
    return {"has_unsaved": False, "checked_out_files": []}


# ------------------------------------------------------------------
# Temp file watcher — auto-pushes saves to vault
# ------------------------------------------------------------------

class TempWatcher:
    """Background thread that watches PLMTemp for saves and auto-pushes to vault.

    Polls every `interval` seconds. When a checked-out temp file's mtime is
    newer than the last known mtime, calls disk_save() to push it to the vault.
    The user just saves in NX — vault stays current automatically.
    """

    def __init__(self, username: str, db: "Database",
                 interval: float = 3.0,
                 on_save: Optional[Callable[[str], None]] = None):
        self.username  = username
        self.db        = db
        self.interval  = interval
        self.on_save   = on_save   # callback(filename) — called on main thread via GUI
        self._stop_evt = threading.Event()
        self._mtimes: dict = {}    # temp_path → last known mtime
        self._thread   = threading.Thread(target=self._run, daemon=True, name="TempWatcher")

    def start(self):
        self._thread.start()
        logger.info("TempWatcher started for %s (interval=%ss)", self.username, self.interval)

    def stop(self):
        self._stop_evt.set()
        logger.info("TempWatcher stopped for %s", self.username)

    def _run(self):
        while not self._stop_evt.wait(self.interval):
            try:
                self._poll()
            except Exception:
                logger.exception("TempWatcher poll error")

    def _poll(self):
        # Watch directly from checkouts table — most reliable source of temp paths
        checkouts = self.db.list_checkouts(self.username)
        for co in checkouts:
            temp_str = co.get("temp_path") or ""
            if not temp_str:
                continue
            temp_path = Path(temp_str)
            if not temp_path.exists():
                continue
            try:
                mtime = temp_path.stat().st_mtime
            except OSError:
                continue

            last = self._mtimes.get(str(temp_path))
            if last is None:
                self._mtimes[str(temp_path)] = mtime
                continue

            if mtime > last:
                self._mtimes[str(temp_path)] = mtime
                self._push(co, temp_path)

    def _push(self, tf: dict, temp_path: Path):
        vault_path = Path(tf["stored_path"])
        try:
            vault_path.parent.mkdir(parents=True, exist_ok=True)
            _set_writable(vault_path)
            shutil.copy2(str(temp_path), str(vault_path))
            _set_readonly(vault_path)
            self.db.update_dataset_size(tf["dataset_id"], vault_path.stat().st_size)
            # Re-parse relationships from updated file
            self._sync_relationships(str(vault_path), tf["dataset_id"])
            logger.info("TempWatcher: auto-saved %s → %s", tf["filename"], vault_path)
            if self.on_save:
                self.on_save(tf["filename"])
        except Exception:
            logger.exception("TempWatcher: failed to push %s", tf["filename"])

    def _sync_relationships(self, vault_path: str, dataset_id: int) -> None:
        """Parse CAD file and auto-create BOM relationships from embedded component refs."""
        from .parser import parse_nx_file
        try:
            result = parse_nx_file(vault_path)
        except Exception:
            return
        # Find which item owns this dataset
        with self.db._connect() as conn:
            row = conn.execute(
                """SELECT r.item_id FROM datasets d
                   JOIN item_revisions r ON r.id = d.revision_id
                   WHERE d.id=?""", (dataset_id,)
            ).fetchone()
        if not row:
            return
        item_pk = row[0]
        for comp_filename in result.get("components", []):
            child = self.db.get_item_by_filename(comp_filename)
            if child and child["id"] != item_pk:
                try:
                    self.db.add_relationship(item_pk, child["id"], 1, self.username)
                except Exception:
                    pass
