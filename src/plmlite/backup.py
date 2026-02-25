"""Backup utility functions for PLMLITE.

Pure stdlib module — no plmlite imports. Handles file copying and version rotation.
"""

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def make_backup_filename(original_path: Path, version_num: int) -> str:
    """Generate a versioned backup filename with timestamp.

    Example: 'part_001.prt' -> 'part_001.prt.v3.20260224_143012'
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{original_path.name}.v{version_num}.{timestamp}"


def copy_to_backup(
    source_path: Path,
    backup_dir: Path,
    version_num: int,
) -> Path:
    """Copy source file to backup_dir with a versioned filename.

    Creates backup_dir if it doesn't exist.

    Returns:
        Path to the created backup file.

    Raises:
        FileNotFoundError: if source_path does not exist.
        OSError: if backup_dir cannot be created or file cannot be copied.
    """
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)

    backup_name = make_backup_filename(source_path, version_num)
    dest = backup_dir / backup_name
    shutil.copy2(str(source_path), str(dest))
    logger.debug("Backed up %s -> %s", source_path.name, dest.name)
    return dest


def delete_backup_file(backup_path: Path) -> bool:
    """Delete a backup file.

    Returns True if deleted, False if file did not exist.
    Logs a warning on permission/OS errors without raising.
    """
    try:
        backup_path.unlink()
        logger.debug("Deleted backup: %s", backup_path.name)
        return True
    except FileNotFoundError:
        return False
    except PermissionError as e:
        logger.warning("Permission denied deleting backup %s: %s", backup_path, e)
        return False
    except OSError as e:
        logger.warning("Failed to delete backup %s: %s", backup_path, e)
        return False


def rotate_backups(backup_paths: list[Path], keep: int) -> list[Path]:
    """Delete all but the newest `keep` backup files.

    Args:
        backup_paths: Paths to existing backups, ordered oldest-first.
        keep: Number of most-recent versions to retain.

    Returns:
        List of Paths that were deleted.
    """
    excess = len(backup_paths) - keep
    if excess <= 0:
        return []

    to_delete = backup_paths[:excess]
    deleted = []
    for path in to_delete:
        if delete_backup_file(path):
            deleted.append(path)
    return deleted
