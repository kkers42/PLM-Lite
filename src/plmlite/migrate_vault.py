"""PLM Lite v2.2 — Vault migration script.

Moves files from any previous layout to the flat-by-revision structure:

    VAULT_PATH/
      01/
        TST0001.prt
        TST0002.prt
      A/
        somepart.prt

All datasets at the same revision label share one folder regardless of item.
Filenames must be unique across the entire vault.

Usage:
    python -m plmlite.migrate_vault [--dry-run]

Idempotent: files already in the correct location are skipped.
Updates stored_path in the datasets table after each move.
"""

import argparse
import logging
import shutil
import sys
from pathlib import Path

from . import config
from .database import Database

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def migrate(dry_run: bool = False) -> None:
    db = Database()
    db.initialize()

    moved = 0
    skipped = 0
    errors = 0

    with db._connect() as conn:
        rows = conn.execute(
            """SELECT d.id AS ds_id, d.filename, d.stored_path,
                      i.item_id, r.revision
               FROM datasets d
               JOIN item_revisions r ON r.id = d.revision_id
               JOIN items i          ON i.id = r.item_id"""
        ).fetchall()

    for row in rows:
        row = dict(row)
        # New layout: VAULT_PATH/{revision}/{filename}
        target = config.VAULT_PATH / row["revision"] / row["filename"]

        if Path(row["stored_path"]).resolve() == target.resolve() and target.exists():
            skipped += 1
            continue  # already in correct location

        src = Path(row["stored_path"])
        if not src.exists():
            logger.warning("Source file missing, skipping: %s", src)
            errors += 1
            continue

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                # Strip read-only before overwriting if target already exists
                if target.exists():
                    try:
                        import os, stat
                        os.chmod(target, os.stat(target).st_mode | stat.S_IWRITE)
                    except OSError:
                        pass
                shutil.copy2(str(src), str(target))
                # Set vault file read-only
                try:
                    import os, stat
                    os.chmod(target, os.stat(target).st_mode & ~stat.S_IWRITE)
                except OSError:
                    pass
                with db._connect() as conn:
                    conn.execute(
                        "UPDATE datasets SET stored_path=? WHERE id=?",
                        (str(target), row["ds_id"]),
                    )
                    conn.commit()
                logger.info("Moved  %s → %s", src.name, target)
                moved += 1
            except Exception:
                logger.exception("Failed to move %s", src)
                errors += 1
        else:
            logger.info("[DRY-RUN] Would move  %s → %s", src, target)
            moved += 1

    logger.info(
        "Migration %scomplete: %d moved, %d already OK, %d errors",
        "(dry-run) " if dry_run else "",
        moved, skipped, errors,
    )
    if errors:
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate vault to v2.2 flat-by-revision structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be moved without moving")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
