"""PLM Lite v2.0 — File system watcher.

Multi-path, per-type, lock-aware watcher built on watchdog.

On file-modified event:
  - No .plmlock sidecar  : unchecked-out save -- auto-create item/revision/dataset in DB
  - .plmlock by self      : update file_size in datasets table
  - .plmlock by other user: quarantine the file via checkout.quarantine_unauthorized_save()

Debounce: 2 seconds per file path (handles NX multi-pass saves).
"""

import getpass
import logging
import time
from pathlib import Path
from typing import List, Optional

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import config
from .database import Database
from .checkout import (
    LOCK_SUFFIX,
    get_lock_info,
    is_locked,
    quarantine_unauthorized_save,
)

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 2.0


class NXFileEventHandler(FileSystemEventHandler):
    """Handles file-system events for one watch path."""

    def __init__(
        self,
        db: Database,
        extensions: List[str],
        username: str,
        watch_name: str = "",
    ):
        super().__init__()
        self.db = db
        self.extensions = [e.lower() for e in extensions]
        self.username = username
        self.watch_name = watch_name
        self._debounce: dict = {}

    # ------------------------------------------------------------------
    # watchdog callback
    # ------------------------------------------------------------------

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        filepath = str(event.src_path)
        if self._should_process(filepath):
            self._debounce[filepath] = time.time()
            try:
                self._handle_file_change(filepath)
            except Exception:
                logger.exception("Error handling change for %s", filepath)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _should_process(self, filepath: str) -> bool:
        path = Path(filepath)

        # Skip .plmlock sidecars
        if path.name.endswith(LOCK_SUFFIX):
            return False

        # Extension filter
        if path.suffix.lower() not in self.extensions:
            return False

        # Skip temp / lock files
        if path.name.startswith((".", "~")):
            return False
        if path.suffix.lower() == ".lck":
            return False

        # Debounce
        last = self._debounce.get(filepath, 0.0)
        if time.time() - last < _DEBOUNCE_SECONDS:
            return False

        return True

    def _handle_file_change(self, filepath: str) -> None:
        path = Path(filepath)

        if is_locked(path):
            info = get_lock_info(path)
            locker = (info or {}).get("checked_out_by", "")
            if locker == self.username:
                self._update_dataset_size(path)
            else:
                logger.warning(
                    "Unauthorized save by %s on file locked by %s -- quarantining %s",
                    self.username, locker, path.name,
                )
                quarantine_unauthorized_save(path, self.db)
        else:
            self._auto_upsert_dataset(path)

    def _update_dataset_size(self, path: Path) -> None:
        dataset = self.db.get_dataset_by_path(str(path))
        if dataset:
            size = path.stat().st_size if path.exists() else 0
            self.db.update_dataset_size(dataset["id"], size)
            self.db.write_audit(
                "file_save", "dataset", str(dataset["id"]), self.username,
                f"Size updated on save: {path.name} ({size} bytes)",
            )
            logger.info("Updated size for %s -> %d bytes", path.name, size)

    def _auto_upsert_dataset(self, path: Path) -> None:
        """Auto-create item + revision + dataset record for an unchecked-out save."""
        existing = self.db.get_dataset_by_path(str(path))
        if existing:
            size = path.stat().st_size if path.exists() else 0
            self.db.update_dataset_size(existing["id"], size)
            self.db.write_audit(
                "file_save", "dataset", str(existing["id"]), self.username,
                f"Unchecked-out save: {path.name}",
            )
            logger.info("Recorded unchecked save: %s", path.name)
            return

        # New file -- auto-create item chain
        item_type = self.db.get_item_type_by_name("Mechanical Part")
        item_type_id = item_type["id"] if item_type else 1

        new_item_id = self.db.next_item_id()
        item_pk = self.db.create_item(
            new_item_id,
            path.name,
            f"Auto-created by watcher from {self.watch_name or 'file system'}",
            item_type_id,
            self.username,
        )

        rev_label = self.db.next_revision(item_pk, "alpha")
        rev_pk = self.db.create_revision(item_pk, rev_label, "alpha", self.username)

        file_size = path.stat().st_size if path.exists() else 0
        self.db.add_dataset(
            rev_pk, path.name, path.suffix.lower(), str(path), file_size, self.username
        )

        self.db.write_audit(
            "auto_create", "item", new_item_id, self.username,
            f"Auto-created from watcher save: {path.name}",
        )
        logger.info(
            "Auto-created %s rev %s for %s", new_item_id, rev_label, path.name
        )


# ------------------------------------------------------------------
# FileWatcher
# ------------------------------------------------------------------

class FileWatcher:
    """Manages one or more watchdog Observers, one per watch config."""

    def __init__(
        self,
        watch_configs: Optional[List[dict]] = None,
        db_path=None,
    ):
        self.watch_configs = watch_configs or config.get_watch_configs()
        self.db = Database(db_path)
        self.username = getpass.getuser()
        self._observers: List[Observer] = []

    def start(self) -> None:
        """Initialize DB, start all Observers, block until Ctrl+C."""
        self.db.initialize()
        self.db.upsert_user(self.username)

        for wc in self.watch_configs:
            watch_path = Path(wc["path"])
            if not watch_path.exists():
                logger.warning("Watch path does not exist, skipping: %s", watch_path)
                continue

            handler = NXFileEventHandler(
                db=self.db,
                extensions=wc["extensions"],
                username=self.username,
                watch_name=wc.get("name", ""),
            )
            obs = Observer()
            obs.schedule(handler, str(watch_path), recursive=True)
            obs.start()
            self._observers.append(obs)
            logger.info(
                "Watching %s for %s as %s",
                watch_path, wc["extensions"], self.username,
            )

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        for obs in self._observers:
            obs.stop()
            obs.join()
        self._observers.clear()
        logger.info("Watcher stopped.")
