"""File system watcher for NX12 CAD datasets.

Uses the watchdog library to monitor a network share folder and trigger
automatic backups and database updates whenever a tracked file is modified.
"""

import getpass
import logging
import time
from pathlib import Path
from typing import Optional

from watchdog.events import FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import config
from .backup import copy_to_backup
from .database import Database

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 2.0


class NXFileEventHandler(FileSystemEventHandler):
    """Handles file system events for NX CAD files.

    Filters by extension, ignores temp/lock files, and debounces rapid events
    caused by NX12's multi-pass save behaviour.
    """

    def __init__(
        self,
        db: Database,
        backup_dir: Path,
        extensions: list[str],
        max_versions: int,
        username: str,
    ):
        super().__init__()
        self.db = db
        self.backup_dir = backup_dir
        self.extensions = [e.lower() for e in extensions]
        self.max_versions = max_versions
        self.username = username
        self._debounce: dict[str, float] = {}

    def on_modified(self, event: FileModifiedEvent) -> None:
        if event.is_directory:
            return
        filepath = str(event.src_path)
        if self._should_process(filepath):
            self._debounce[filepath] = time.time()
            self._handle_file_change(filepath)

    def _should_process(self, filepath: str) -> bool:
        """Return True if this file should trigger a backup."""
        path = Path(filepath)

        # Extension filter
        if path.suffix.lower() not in self.extensions:
            return False

        # Skip temp/lock files
        if path.name.startswith((".", "~")):
            return False
        if path.suffix.lower() == ".lck":
            return False

        # Debounce — skip if processed within the last DEBOUNCE_SECONDS
        last = self._debounce.get(filepath, 0.0)
        if time.time() - last < _DEBOUNCE_SECONDS:
            return False

        return True

    def _handle_file_change(self, filepath: str) -> None:
        """Core handler: backup the file, update DB, rotate old versions.

        All exceptions are caught and logged so the watcher never crashes.
        """
        path = Path(filepath)
        try:
            file_id = self.db.upsert_file(path.name, filepath)
            version_num = self.db.get_current_version_num(file_id) + 1

            # Copy with retry — NX may still hold the file handle open
            backup_dest = None
            for attempt in range(3):
                try:
                    backup_dest = copy_to_backup(path, self.backup_dir, version_num)
                    break
                except (PermissionError, OSError) as e:
                    if attempt == 2:
                        logger.error(
                            "Failed to backup %s after 3 attempts: %s", path.name, e
                        )
                        return
                    time.sleep(0.5 * (2**attempt))

            file_size = path.stat().st_size if path.exists() else 0
            self.db.insert_version(
                file_id, version_num, str(backup_dest), self.username, file_size
            )

            # Rotate old versions
            old_versions = self.db.get_old_versions(file_id, keep=self.max_versions)
            for v in old_versions:
                from .backup import delete_backup_file
                if v["backup_path"]:
                    delete_backup_file(Path(v["backup_path"]))
                self.db.delete_version(v["id"])

            self.db.upsert_user(self.username)

            logger.info(
                "v%d  %s  saved_by=%s  backup=%s",
                version_num,
                path.name,
                self.username,
                backup_dest.name if backup_dest else "?",
            )

        except Exception as e:
            logger.exception("Unexpected error handling change for %s: %s", filepath, e)


class FileWatcher:
    """Manages the watchdog Observer lifecycle."""

    def __init__(
        self,
        watch_path: Optional[Path] = None,
        backup_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        self.watch_path = watch_path or config.WATCH_PATH
        self.backup_path = backup_path or config.BACKUP_PATH
        self.db = Database(db_path)
        self.username = getpass.getuser()
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        """Initialize DB, start the Observer, and block until Ctrl+C."""
        self.db.initialize()

        handler = NXFileEventHandler(
            db=self.db,
            backup_dir=self.backup_path,
            extensions=config.FILE_EXTENSIONS,
            max_versions=config.MAX_VERSIONS,
            username=self.username,
        )

        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_path), recursive=True)
        self._observer.start()

        logger.info("Watching %s as user %s", self.watch_path, self.username)

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        """Stop the Observer cleanly."""
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Watcher stopped.")
