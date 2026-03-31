"""PLM Lite v2.0 -- Command-line interface.

ASCII-only output (Windows cp1252 safe).

Commands:
  items list [--status STATUS]
  items create --name NAME --type TYPE [--desc DESC]
  items show ITEM_ID
  revisions list ITEM_ID
  revisions create ITEM_ID [--type alpha|numeric]
  revisions release ITEM_ID REVISION [--lock]
  datasets add ITEM_ID REVISION FILEPATH
  datasets list ITEM_ID REVISION
  checkout ITEM_ID REVISION FILENAME
  checkin  ITEM_ID REVISION FILENAME
  checkouts list [--user USERNAME]
  audit ITEM_ID
  watch
  config
"""

import argparse
import getpass
import socket
import sys
from pathlib import Path

from .database import Database
from .lifecycle import LifecycleState


def main():
    parser = argparse.ArgumentParser(
        prog="plmlite",
        description="PLM Lite v2.0 -- Lightweight CAD PLM",
    )
    sub = parser.add_subparsers(dest="command")

    # -- items --
    items_p = sub.add_parser("items", help="item management")
    items_sub = items_p.add_subparsers(dest="items_cmd")

    il = items_sub.add_parser("list", help="list items")
    il.add_argument("--status", choices=["in_work", "released", "obsolete", "active", "locked"],
                    help="filter by status")

    ic = items_sub.add_parser("create", help="create a new item")
    ic.add_argument("--name", required=True)
    ic.add_argument("--type", dest="item_type", default="Mechanical Part")
    ic.add_argument("--desc", default="")

    ish = items_sub.add_parser("show", help="show item details")
    ish.add_argument("item_id")

    # -- revisions --
    rev_p = sub.add_parser("revisions", help="revision management")
    rev_sub = rev_p.add_subparsers(dest="rev_cmd")

    rl = rev_sub.add_parser("list", help="list revisions for an item")
    rl.add_argument("item_id")

    rc = rev_sub.add_parser("create", help="create a new revision")
    rc.add_argument("item_id")
    rc.add_argument("--type", dest="rev_type", choices=["alpha", "numeric"], default="alpha")

    rr = rev_sub.add_parser("release", help="release or lock a revision")
    rr.add_argument("item_id")
    rr.add_argument("revision")
    rr.add_argument("--lock", action="store_true", help="lock instead of release")

    # -- datasets --
    ds_p = sub.add_parser("datasets", help="dataset management")
    ds_sub = ds_p.add_subparsers(dest="ds_cmd")

    da = ds_sub.add_parser("add", help="add a dataset file to a revision")
    da.add_argument("item_id")
    da.add_argument("revision")
    da.add_argument("filepath")

    dl = ds_sub.add_parser("list", help="list datasets for a revision")
    dl.add_argument("item_id")
    dl.add_argument("revision")

    # -- checkout / checkin --
    co_p = sub.add_parser("checkout", help="check out a dataset")
    co_p.add_argument("item_id")
    co_p.add_argument("revision")
    co_p.add_argument("filename")

    ci_p = sub.add_parser("checkin", help="check in a dataset")
    ci_p.add_argument("item_id")
    ci_p.add_argument("revision")
    ci_p.add_argument("filename")

    # -- checkouts list --
    cl_p = sub.add_parser("checkouts", help="list active checkouts")
    cl_p.add_argument("--user", default=None)

    # -- audit --
    au_p = sub.add_parser("audit", help="show audit log for an item")
    au_p.add_argument("item_id")

    # -- watch --
    sub.add_parser("watch", help="start file watcher (blocks until Ctrl+C)")

    # -- config --
    sub.add_parser("config", help="show resolved configuration")

    args = parser.parse_args()

    if args.command == "items":
        if args.items_cmd == "list":
            _cmd_items_list(args.status)
        elif args.items_cmd == "create":
            _cmd_items_create(args.name, args.item_type, args.desc)
        elif args.items_cmd == "show":
            _cmd_items_show(args.item_id)
        else:
            items_p.print_help(); sys.exit(1)

    elif args.command == "revisions":
        if args.rev_cmd == "list":
            _cmd_revisions_list(args.item_id)
        elif args.rev_cmd == "create":
            _cmd_revisions_create(args.item_id, args.rev_type)
        elif args.rev_cmd == "release":
            _cmd_revisions_release(args.item_id, args.revision, args.lock)
        else:
            rev_p.print_help(); sys.exit(1)

    elif args.command == "datasets":
        if args.ds_cmd == "add":
            _cmd_datasets_add(args.item_id, args.revision, args.filepath)
        elif args.ds_cmd == "list":
            _cmd_datasets_list(args.item_id, args.revision)
        else:
            ds_p.print_help(); sys.exit(1)

    elif args.command == "checkout":
        _cmd_checkout(args.item_id, args.revision, args.filename)
    elif args.command == "checkin":
        _cmd_checkin(args.item_id, args.revision, args.filename)
    elif args.command == "checkouts":
        _cmd_checkouts_list(args.user)
    elif args.command == "audit":
        _cmd_audit(args.item_id)
    elif args.command == "watch":
        _cmd_watch()
    elif args.command == "config":
        _cmd_config()
    else:
        parser.print_help()
        sys.exit(1)


# ------------------------------------------------------------------
# Command implementations
# ------------------------------------------------------------------

def _get_db() -> Database:
    db = Database()
    db.initialize()
    return db


def _require_item(db: Database, item_id: str):
    item = db.get_item(item_id)
    if not item:
        print(f"Item not found: {item_id}")
        sys.exit(1)
    return item


def _require_revision(db: Database, item_pk: int, revision: str, item_id: str = ""):
    rev = db.get_revision_by_name(item_pk, revision)
    if not rev:
        print(f"Revision {revision} not found on item {item_id}")
        sys.exit(1)
    return rev


def _cmd_items_list(status_filter=None, db=None):
    db = db or _get_db()
    rows = db.list_items(status_filter)
    if not rows:
        print("No items found.")
        return rows
    print(f"{'Item ID':<12}  {'Name':<30}  {'Type':<18}  {'Status':<10}  Creator")
    print("-" * 84)
    for r in rows:
        print(f"{r['item_id']:<12}  {r['name'][:30]:<30}  {r['type_name'][:18]:<18}"
              f"  {r['status']:<10}  {r['creator']}")
    return rows


def _cmd_items_create(name, item_type_name, description="", db=None):
    db = db or _get_db()
    username = getpass.getuser()

    itype = db.get_item_type_by_name(item_type_name)
    if not itype:
        types = [t["name"] for t in db.list_item_types()]
        print(f"Unknown item type '{item_type_name}'. Available: {', '.join(types)}")
        sys.exit(1)

    new_id = db.next_item_id()
    pk = db.create_item(new_id, name, description, itype["id"], username)
    db.write_audit("create", "item", new_id, username, f"Created item: {name}")
    print(f"Created: {new_id}  '{name}'  [{item_type_name}]")
    return new_id


def _cmd_items_show(item_id, db=None):
    db = db or _get_db()
    item = _require_item(db, item_id)
    print(f"Item ID   : {item['item_id']}")
    print(f"Name      : {item['name']}")
    print(f"Type      : {item['type_name']}")
    print(f"Status    : {item['status']}")
    print(f"Created by: {item['creator']}  at {item['created_at']}")
    if item["description"]:
        print(f"Desc      : {item['description']}")
    revs = db.get_revisions(item["id"])
    if revs:
        print(f"\nRevisions ({len(revs)}):")
        for r in revs:
            print(f"  {r['revision']:>4}  [{r['status']:<10}]  "
                  f"by {r['creator']}  {r['created_at']}")
    return item


def _cmd_revisions_list(item_id, db=None):
    db = db or _get_db()
    item = _require_item(db, item_id)
    revs = db.get_revisions(item["id"])
    if not revs:
        print(f"No revisions for {item_id}.")
        return revs
    print(f"Revisions for {item_id} -- {item['name']}")
    print(f"  {'Rev':<6}  {'Type':<8}  {'Status':<10}  {'Created by':<16}  Created at")
    print("  " + "-" * 68)
    for r in revs:
        print(f"  {r['revision']:<6}  {r['revision_type']:<8}  {r['status']:<10}"
              f"  {r['creator']:<16}  {r['created_at']}")
    return revs


def _cmd_revisions_create(item_id, rev_type="alpha", db=None):
    db = db or _get_db()
    username = getpass.getuser()
    item = _require_item(db, item_id)
    rev_label = db.next_revision(item["id"], rev_type)
    pk = db.create_revision(item["id"], rev_label, rev_type, username)
    db.write_audit("create_revision", "item_revision", str(pk), username,
                   f"{item_id} rev {rev_label}")
    print(f"Created revision {rev_label} on {item_id}")
    return rev_label


def _cmd_revisions_release(item_id, revision, lock_only=False, db=None):
    db = db or _get_db()
    username = getpass.getuser()
    item = _require_item(db, item_id)
    rev = _require_revision(db, item["id"], revision, item_id)

    action = "lock" if lock_only else "release"
    answer = input(f"Are you sure you want to {action} {item_id}/{revision}? [y/N] ")
    if answer.strip().lower() != "y":
        print("Aborted.")
        return

    if lock_only:
        db.lock_revision(rev["id"], username)
        print(f"Locked {item_id}/{revision}")
    else:
        db.release_revision(rev["id"], username)
        print(f"Released {item_id}/{revision}")
    db.write_audit(action, "item_revision", str(rev["id"]), username,
                   f"{item_id}/{revision}")


def _cmd_datasets_add(item_id, revision, filepath, db=None):
    db = db or _get_db()
    username = getpass.getuser()
    item = _require_item(db, item_id)
    rev = _require_revision(db, item["id"], revision, item_id)
    path = Path(filepath)
    if not path.exists():
        print(f"File not found: {filepath}")
        sys.exit(1)
    size = path.stat().st_size
    ds_id = db.add_dataset(rev["id"], path.name, path.suffix.lower(),
                           str(path), size, username)
    db.write_audit("add_dataset", "dataset", str(ds_id), username,
                   f"{item_id}/{revision}: {path.name}")
    print(f"Added dataset {path.name} to {item_id}/{revision}  (id={ds_id})")
    return ds_id


def _cmd_datasets_list(item_id, revision, db=None):
    db = db or _get_db()
    item = _require_item(db, item_id)
    rev = _require_revision(db, item["id"], revision, item_id)
    datasets = db.get_datasets(rev["id"])
    if not datasets:
        print(f"No datasets for {item_id}/{revision}.")
        return datasets
    print(f"Datasets for {item_id}/{revision}:")
    print(f"  {'ID':>4}  {'Filename':<30}  {'Size':>10}  {'Checked out by'}")
    print("  " + "-" * 68)
    for d in datasets:
        size_str = f"{d['file_size'] // 1024} KB" if d["file_size"] else "0 KB"
        who = d.get("checked_out_by") or "-"
        print(f"  {d['id']:>4}  {d['filename'][:30]:<30}  {size_str:>10}  {who}")
    return datasets


def _cmd_checkout(item_id, revision, filename, db=None):
    from .checkout import checkout_file as _co
    db = db or _get_db()
    username = getpass.getuser()
    item = _require_item(db, item_id)
    rev = _require_revision(db, item["id"], revision, item_id)
    datasets = db.get_datasets(rev["id"])
    ds = next((d for d in datasets if d["filename"] == filename), None)
    if not ds:
        print(f"Dataset '{filename}' not found in {item_id}/{revision}")
        sys.exit(1)
    station = socket.gethostname()
    _co(Path(ds["stored_path"]), username, db,
        station=station, dataset_id=ds["id"],
        item_id=item_id, revision=revision)
    print(f"Checked out '{filename}' to {username} on {station}")


def _cmd_checkin(item_id, revision, filename, db=None):
    from .checkout import checkin_file as _ci
    db = db or _get_db()
    username = getpass.getuser()
    item = _require_item(db, item_id)
    rev = _require_revision(db, item["id"], revision, item_id)
    datasets = db.get_datasets(rev["id"])
    ds = next((d for d in datasets if d["filename"] == filename), None)
    if not ds:
        print(f"Dataset '{filename}' not found in {item_id}/{revision}")
        sys.exit(1)
    _ci(Path(ds["stored_path"]), username, db)
    print(f"Checked in '{filename}'")


def _cmd_checkouts_list(username=None, db=None):
    db = db or _get_db()
    rows = db.list_checkouts(username)
    if not rows:
        print("No active checkouts.")
        return rows
    print(f"{'Who':<16}  {'Item/Rev':<18}  {'Filename':<28}  Station  Checked out at")
    print("-" * 96)
    for r in rows:
        item_rev = f"{r.get('item_id','?')}/{r.get('revision','?')}"
        print(f"{r['who']:<16}  {item_rev:<18}  {r['filename'][:28]:<28}"
              f"  {r.get('station_name','?'):<10}  {r['checked_out_at']}")
    return rows


def _cmd_audit(item_id, db=None):
    db = db or _get_db()
    item = _require_item(db, item_id)
    logs = db.get_audit_log("item", item_id)
    # Also get revision/dataset logs via item_id prefix search
    all_logs = list(logs)
    if not all_logs:
        print(f"No audit entries for {item_id}.")
        return all_logs
    print(f"Audit log for {item_id}:")
    print(f"  {'Action':<18}  {'Entity':<12}  {'By':<14}  {'At':<22}  Detail")
    print("  " + "-" * 84)
    for e in all_logs:
        print(f"  {e['action']:<18}  {e['entity_type']:<12}  "
              f"{(e.get('who') or '?'):<14}  {e['performed_at']:<22}  {e.get('detail','')}")
    return all_logs


def _cmd_watch():
    from .watcher import FileWatcher
    from . import config as cfg
    watch_configs = cfg.get_watch_configs()
    print("PLM Lite v2.0 -- starting watcher")
    for wc in watch_configs:
        print(f"  [{wc['name']}]  path={wc['path']}  ext={','.join(wc['extensions'])}")
    print("Press Ctrl+C to stop.\n")
    warnings = cfg.validate_paths()
    for w in warnings:
        print(f"WARNING: {w}")
    FileWatcher(watch_configs).start()


def _cmd_config():
    from . import config as cfg
    c = cfg.get_config()
    print("PLM Lite v2.0 Configuration:")
    for key, value in c.items():
        if key == "WATCH_CONFIGS":
            print(f"  {key}:")
            for wc in value:
                print(f"    [{wc['name']}]  path={wc['path']}  ext={','.join(wc['extensions'])}")
        else:
            print(f"  {key}: {value}")
    warnings = cfg.validate_paths()
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  ! {w}")
