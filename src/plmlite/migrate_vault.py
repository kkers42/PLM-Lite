"""PLM Lite v2.2 — Vault migration script.

Moves files from a flat vault layout (VAULT_PATH/{filename}) to the
structured layout (VAULT_PATH/{item_id}/{revision}/{filename}).

Usage:
    python -m plmlite.migrate_vault [--dry-run]

Idempotent: files that are already in the correct location are skipped.
The script updates stored_path in the datasets table after each move.
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
        target = config.VAULT_PATH / row["item_id"] / row["revision"] / row["filename"]

        if str(target) == row["stored_path"] and target.exists():
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
                shutil.copy2(str(src), str(target))
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
    parser = argparse.ArgumentParser(description="Migrate vault to v2.2 folder structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be moved without moving")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
