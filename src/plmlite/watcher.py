"""PLM Lite v2.2 — File-modification watcher.

No watchdog dependency.  Simple polling loop:
  - Every 5 seconds, iterate all active checkouts in the DB.
  - For each checkout: compare temp file mtime vs vault master mtime.
  - If temp > vault: mark dataset_id as modified in memory.
  - Exposes get_modified_status(dataset_id) for server routes.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Optional

from . import config
from .database import Database

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5.0  # seconds


class FileWatcher:
    """Polls active checkouts every 5 s to detect unsaved modifications."""

    def __init__(self, db_path=None):
        self._db_path = db_path or str(config.DB_PATH)
        self._modified: dict[int, bool] = {}   # dataset_id → bool
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background poll thread (non-blocking)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="plm-watcher")
        self._thread.start()
        logger.info("FileWatcher started (poll interval %ss)", _POLL_INTERVAL)

    def stop(self) -> None:
        """Signal the poll thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("FileWatcher stopped.")

    def get_modified_status(self, dataset_id: int) -> bool:
        """Return True if the checked-out temp file is newer than the vault master."""
        with self._lock:
            return self._modified.get(dataset_id, False)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll()
            except Exception:
                logger.exception("Error in watcher poll")
            self._stop_event.wait(_POLL_INTERVAL)

    def _poll(self) -> None:
        db = Database(self._db_path)
        try:
            checkouts = db.list_checkouts()
        except Exception:
            logger.exception("Could not read checkouts during poll")
            return

        new_state: dict[int, bool] = {}
        for co in checkouts:
            ds_id    = co.get("dataset_id")
            temp_str = co.get("temp_path", "")
            item_id  = co.get("item_id", "")
            revision = co.get("revision", "")
            filename = co.get("filename", "")

            if not (ds_id and temp_str and item_id and revision and filename):
                continue

            temp_path  = Path(temp_str)
            vault_path = config.VAULT_PATH / item_id / revision / filename

            try:
                if temp_path.exists() and vault_path.exists():
                    modified = temp_path.stat().st_mtime > vault_path.stat().st_mtime
                else:
                    modified = False
            except OSError:
                modified = False

            new_state[ds_id] = modified

        with self._lock:
            self._modified = new_state
