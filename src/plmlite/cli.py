"""Command-line interface for PLMLITE."""

import argparse
import getpass
import sys

from .lifecycle import LifecycleManager, LifecycleState


def main():
    parser = argparse.ArgumentParser(
        prog="plmlite",
        description="PLMLITE - Lightweight PLM for NX12 CAD datasets",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- File watcher ---
    subparsers.add_parser("watch", help="start file watcher (blocks until Ctrl+C)")

    # --- Version history ---
    history_p = subparsers.add_parser("history", help="show version history for a file")
    history_p.add_argument("filename", help="filename to look up, e.g. part_001.prt")

    # --- Checkout management ---
    subparsers.add_parser("list-checkouts", help="list all checked-out files")

    checkout_p = subparsers.add_parser("checkout", help="check out a file")
    checkout_p.add_argument("filename")

    checkin_p = subparsers.add_parser("checkin", help="check in a file")
    checkin_p.add_argument("filename")

    # --- Lifecycle state (DB-backed) ---
    state_p = subparsers.add_parser("state", help="show lifecycle state for a file")
    state_p.add_argument("filepath", help="full filepath of the tracked file")

    set_p = subparsers.add_parser("set", help="set lifecycle state for a file")
    set_p.add_argument("filepath", help="full filepath of the tracked file")
    set_p.add_argument("state", choices=[s.value for s in LifecycleState])

    # --- NX file parser ---
    parse_p = subparsers.add_parser("parse", help="parse an NX file and show metadata")
    parse_p.add_argument("file")

    # --- Config display ---
    subparsers.add_parser("config", help="show current configuration")

    args = parser.parse_args()

    if args.command == "watch":
        _cmd_watch()
    elif args.command == "history":
        _cmd_history(args.filename)
    elif args.command == "list-checkouts":
        _cmd_list_checkouts()
    elif args.command == "checkout":
        _cmd_checkout(args.filename)
    elif args.command == "checkin":
        _cmd_checkin(args.filename)
    elif args.command == "state":
        _cmd_state(args.filepath)
    elif args.command == "set":
        _cmd_set(args.filepath, args.state)
    elif args.command == "parse":
        _cmd_parse(args.file)
    elif args.command == "config":
        _cmd_config()
    else:
        parser.print_help()
        sys.exit(1)


# -----------------------------------------------------------------------------
# Command implementations
# -----------------------------------------------------------------------------

def _cmd_watch() -> None:
    from .watcher import FileWatcher
    from . import config
    cfg = config.get_config()
    print("Starting PLMLITE watcher")
    print(f"  Watch path  : {cfg['WATCH_PATH']}")
    print(f"  Backup path : {cfg['BACKUP_PATH']}")
    print(f"  Database    : {cfg['DB_PATH']}")
    print(f"  Extensions  : {', '.join(cfg['FILE_EXTENSIONS'])}")
    print(f"  Max versions: {cfg['MAX_VERSIONS']}")
    print("Press Ctrl+C to stop.\n")

    warnings = config.validate_paths()
    for w in warnings:
        print(f"WARNING: {w}")

    watcher = FileWatcher()
    watcher.start()


def _cmd_history(filename: str) -> None:
    from .database import Database
    db = Database()
    db.initialize()
    file_row = db.get_file_by_name(filename)
    if not file_row:
        print(f"No record found for: {filename}")
        print("(Has this file been saved while the watcher was running?)")
        sys.exit(1)
    versions = db.get_version_history(file_row["id"])
    if not versions:
        print(f"No versions recorded for: {filename}")
        return
    print(f"Version history for: {filename}")
    print(f"  Lifecycle state: {file_row.get('lifecycle_state', 'unknown')}")
    if file_row.get("checked_out_by"):
        print(f"  Checked out by : {file_row['checked_out_by']} at {file_row['checked_out_at']}")
    print()
    print(f"{'Ver':>4}  {'Saved By':<20}  {'Saved At':<20}  {'Size':>10}")
    print("-" * 62)
    for v in versions:
        size_str = f"{v['file_size'] // 1024} KB" if v.get("file_size") else "?"
        saved_by = v.get("saved_by") or "?"
        print(f"{v['version_num']:>4}  {saved_by:<20}  {str(v['saved_at']):<20}  {size_str:>10}")


def _cmd_list_checkouts() -> None:
    from .database import Database
    db = Database()
    db.initialize()
    checkouts = db.list_checkouts()
    if not checkouts:
        print("No files currently checked out.")
        return
    print(f"{'Filename':<30}  {'Checked Out By':<20}  Checked Out At")
    print("-" * 80)
    for f in checkouts:
        print(f"{f['filename']:<30}  {f['checked_out_by']:<20}  {f['checked_out_at']}")


def _cmd_checkout(filename: str) -> None:
    from .database import Database
    db = Database()
    db.initialize()
    file_row = db.get_file_by_name(filename)
    if not file_row:
        print(f"File not tracked: {filename}")
        print("(Has this file been saved while the watcher was running?)")
        sys.exit(1)
    username = getpass.getuser()
    success = db.checkout_file(file_row["id"], username)
    if success:
        print(f"Checked out '{filename}' to {username}")
    else:
        print(
            f"Cannot check out: '{filename}' is already checked out"
            f" by {file_row['checked_out_by']}"
        )
        sys.exit(1)


def _cmd_checkin(filename: str) -> None:
    from .database import Database
    db = Database()
    db.initialize()
    file_row = db.get_file_by_name(filename)
    if not file_row:
        print(f"File not tracked: {filename}")
        sys.exit(1)
    username = getpass.getuser()
    if file_row.get("checked_out_by") and file_row["checked_out_by"] != username:
        print(
            f"Warning: '{filename}' was checked out by {file_row['checked_out_by']},"
            f" not {username}."
        )
    db.checkin_file(file_row["id"])
    print(f"Checked in: '{filename}'")


def _cmd_state(filepath: str) -> None:
    from .database import Database
    db = Database()
    db.initialize()
    manager = LifecycleManager(db=db)
    state = manager.get_state(filepath)
    print(state.value if state else "unknown")


def _cmd_set(filepath: str, state_str: str) -> None:
    from .database import Database
    db = Database()
    db.initialize()
    manager = LifecycleManager(db=db)
    manager.set_state(filepath, LifecycleState(state_str))
    print(f"Set lifecycle state for '{filepath}' to '{state_str}'")


def _cmd_parse(filepath: str) -> None:
    from .parser import parse_nx_file
    info = parse_nx_file(filepath)
    for key, value in info.items():
        print(f"{key}: {value}")


def _cmd_config() -> None:
    from . import config
    cfg = config.get_config()
    print("PLMLITE Configuration:")
    for key, value in cfg.items():
        print(f"  {key}: {value}")
    warnings = config.validate_paths()
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ! {w}")
