"""PLM Lite v2.0 unit tests.

~39 tests across 5 sections:
  1. Schema        (5)  -- tables created, seed data
  2. Database      (12) -- CRUD, next_item_id, next_revision
  3. Checkout engine (10) -- lockfile lifecycle, errors, quarantine
  4. Watcher logic  (6)  -- auto-create, size update, quarantine trigger
  5. CLI commands   (6)  -- items list/create/show, checkout/checkin, revisions

All DB tests use a real temp file (tmp_path) -- simple and reliable.
Filesystem tests use tmp_path for the file tree.
Watcher tests call NXFileEventHandler._handle_file_change() directly.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plmlite.database import Database, CheckoutError, _next_alpha
from plmlite.checkout import (
    checkout_file,
    checkin_file,
    is_locked,
    get_lock_info,
    quarantine_unauthorized_save,
    CheckoutError as CoCheckoutError,
    LOCK_SUFFIX,
    QUARANTINE_DIR,
)
from plmlite.watcher import NXFileEventHandler


# ==================================================================
# Fixtures
# ==================================================================

@pytest.fixture
def db(tmp_path):
    d = Database(db_path=tmp_path / "test.db")
    d.initialize()
    return d


@pytest.fixture
def populated_db(db):
    """DB with one item, one revision, one dataset (file may not exist on disk)."""
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Test Part", "desc", itype["id"], "alice")
    rev_pk = db.create_revision(item_pk, "A", "alpha", "alice")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/data/part.prt", 1024, "alice")
    return db, item_pk, rev_pk, ds_pk


@pytest.fixture
def file_tree(tmp_path):
    """Create a real .prt file in a temp directory for filesystem tests."""
    f = tmp_path / "part.prt"
    f.write_bytes(b"NX_PART_DATA" * 100)
    return tmp_path, f


# ==================================================================
# Section 1: Schema
# ==================================================================

EXPECTED_TABLES = {
    "users", "item_types", "items", "item_revisions",
    "datasets", "checkouts", "workflows", "audit_log",
}


def test_schema_all_tables_created(db):
    conn = sqlite3.connect(str(db._uri) if db._use_uri else db._uri,
                           uri=db._use_uri)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    conn.close()
    assert EXPECTED_TABLES.issubset(tables)


def test_schema_item_types_seeded(db):
    types = db.list_item_types()
    names = {t["name"] for t in types}
    assert "Mechanical Part" in names
    assert "Assembly" in names
    assert "Prototype" in names
    assert "Document" in names


def test_schema_item_id_unique_constraint(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    db.create_item("ITM-00001", "Part A", "", itype["id"], "alice")
    with pytest.raises(Exception):
        db.create_item("ITM-00001", "Part B", "", itype["id"], "bob")


def test_schema_foreign_key_item_type(db):
    with pytest.raises(Exception):
        db.create_item("ITM-00099", "Bad Part", "", 9999, "alice")


def test_schema_indexes_exist(db):
    conn = sqlite3.connect(str(db._uri) if db._use_uri else db._uri,
                           uri=db._use_uri)
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cur.fetchall()}
    conn.close()
    assert "idx_items_item_id" in indexes
    assert "idx_revisions_item_id" in indexes
    assert "idx_datasets_filename" in indexes
    assert "idx_checkouts_dataset_id" in indexes


# ==================================================================
# Section 2: Database methods
# ==================================================================

def test_db_upsert_user_creates(db):
    uid = db.upsert_user("alice", "admin")
    assert isinstance(uid, int)
    users = db.list_users()
    assert any(u["username"] == "alice" for u in users)


def test_db_upsert_user_updates_role(db):
    db.upsert_user("bob", "user")
    db.upsert_user("bob", "readonly")
    users = db.list_users()
    bob = next(u for u in users if u["username"] == "bob")
    assert bob["role"] == "readonly"


def test_db_create_item_returns_id(db):
    itype = db.get_item_type_by_name("Assembly")
    pk = db.create_item("ITM-00001", "My Assembly", "desc", itype["id"], "alice")
    assert isinstance(pk, int) and pk > 0


def test_db_get_item_returns_dict(populated_db):
    db, item_pk, rev_pk, ds_pk = populated_db
    item = db.get_item("ITM-00001")
    assert item is not None
    assert item["name"] == "Test Part"
    assert item["type_name"] == "Mechanical Part"


def test_db_list_items_no_filter(populated_db):
    db, *_ = populated_db
    items = db.list_items()
    assert len(items) == 1
    assert items[0]["item_id"] == "ITM-00001"


def test_db_list_items_status_filter(populated_db):
    db, *_ = populated_db
    assert len(db.list_items("in_work")) == 1
    assert len(db.list_items("released")) == 0


def test_db_create_revision_returns_id(populated_db):
    db, item_pk, *_ = populated_db
    rev_pk = db.create_revision(item_pk, "B", "alpha", "alice")
    assert isinstance(rev_pk, int) and rev_pk > 0


def test_db_get_revisions_ordered(populated_db):
    db, item_pk, *_ = populated_db
    db.create_revision(item_pk, "B", "alpha", "alice")
    revs = db.get_revisions(item_pk)
    assert len(revs) == 2
    assert revs[0]["revision"] == "A"
    assert revs[1]["revision"] == "B"


def test_db_add_dataset_returns_id(populated_db):
    db, _, rev_pk, ds_pk = populated_db
    assert isinstance(ds_pk, int) and ds_pk > 0


def test_db_get_datasets(populated_db):
    db, _, rev_pk, _ = populated_db
    datasets = db.get_datasets(rev_pk)
    assert len(datasets) == 1
    assert datasets[0]["filename"] == "part.prt"


def test_db_checkout_and_checkin(populated_db):
    db, _, _, ds_pk = populated_db
    # No checkout initially
    assert db.get_checkout(ds_pk) is None
    db.checkout_dataset(ds_pk, "alice", "ALICE-PC", "/data/part.prt.plmlock")
    co = db.get_checkout(ds_pk)
    assert co is not None
    assert co["who"] == "alice"
    # Check in
    db.checkin_dataset(ds_pk, "alice")
    assert db.get_checkout(ds_pk) is None


def test_db_next_item_id_format(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    assert db.next_item_id() == "ITM-00001"
    db.create_item("ITM-00001", "Part A", "", itype["id"], "alice")
    assert db.next_item_id() == "ITM-00002"


def test_db_next_revision_alpha(populated_db):
    db, item_pk, *_ = populated_db
    # Already has rev A
    assert db.next_revision(item_pk, "alpha") == "B"
    db.create_revision(item_pk, "B", "alpha", "alice")
    assert db.next_revision(item_pk, "alpha") == "C"


def test_db_next_revision_numeric(populated_db):
    db, item_pk, *_ = populated_db
    pk2 = db.create_revision(item_pk, "01", "numeric", "alice")
    assert db.next_revision(item_pk, "numeric") == "02"


# ==================================================================
# Section 3: Checkout engine
# ==================================================================

def test_co_checkout_creates_lockfile(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    lock = f.parent / (f.name + LOCK_SUFFIX)
    assert lock.exists()


def test_co_checkin_removes_lockfile(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    checkin_file(f, "alice", db)
    lock = f.parent / (f.name + LOCK_SUFFIX)
    assert not lock.exists()


def test_co_is_locked_true(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    assert not is_locked(f)
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    assert is_locked(f)


def test_co_is_locked_false(file_tree):
    _, f = file_tree
    assert not is_locked(f)


def test_co_get_lock_info_returns_dict(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    info = get_lock_info(f)
    assert info is not None
    assert info["checked_out_by"] == "alice"
    assert info["station"] == "ALICE-PC"
    assert info["dataset_id"] == ds_pk


def test_co_get_lock_info_no_lock_returns_none(file_tree):
    _, f = file_tree
    assert get_lock_info(f) is None


def test_co_double_checkout_different_user_raises(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    with pytest.raises(CoCheckoutError):
        checkout_file(f, "bob", db, station="BOB-PC",
                      dataset_id=ds_pk, item_id="ITM-00001", revision="A")


def test_co_checkin_wrong_user_raises(file_tree, populated_db):
    tmp, f = file_tree
    db, _, _, ds_pk = populated_db
    checkout_file(f, "alice", db, station="ALICE-PC",
                  dataset_id=ds_pk, item_id="ITM-00001", revision="A")
    with pytest.raises((CoCheckoutError, CheckoutError)):
        checkin_file(f, "bob", db)


def test_co_quarantine_moves_file(file_tree, tmp_path):
    _, f = file_tree
    db = Database(db_path=tmp_path / "q.db")
    db.initialize()
    db.upsert_user("system")
    dest = quarantine_unauthorized_save(f, db)
    assert not f.exists()
    assert dest.exists()
    assert dest.parent.name == QUARANTINE_DIR


def test_co_quarantine_creates_dir(file_tree, tmp_path):
    _, f = file_tree
    db = Database(db_path=tmp_path / "q2.db")
    db.initialize()
    db.upsert_user("system")
    q_dir = f.parent / QUARANTINE_DIR
    assert not q_dir.exists()
    quarantine_unauthorized_save(f, db)
    assert q_dir.exists()


# ==================================================================
# Section 4: Watcher logic
# ==================================================================

def _make_handler(db, extensions=None, username="alice"):
    return NXFileEventHandler(
        db=db,
        extensions=extensions or [".prt", ".asm"],
        username=username,
        watch_name="test",
    )


def test_watcher_no_lock_creates_item_revision_dataset(tmp_path):
    f = tmp_path / "bracket.prt"
    f.write_bytes(b"NX" * 50)
    db = Database(db_path=tmp_path / "w.db")
    db.initialize()

    handler = _make_handler(db)
    handler._handle_file_change(str(f))

    items = db.list_items()
    assert len(items) == 1
    item_pk = items[0]["id"]
    revs = db.get_revisions(item_pk)
    assert len(revs) == 1
    assert revs[0]["revision"] == "A"
    datasets = db.get_datasets(revs[0]["id"])
    assert len(datasets) == 1
    assert datasets[0]["filename"] == "bracket.prt"


def test_watcher_no_lock_second_save_updates_size(tmp_path):
    f = tmp_path / "part.prt"
    f.write_bytes(b"X" * 100)
    db = Database(db_path=tmp_path / "w2.db")
    db.initialize()

    handler = _make_handler(db)
    handler._handle_file_change(str(f))

    # Simulate file growing
    f.write_bytes(b"X" * 500)
    handler._handle_file_change(str(f))

    items = db.list_items()
    revs = db.get_revisions(items[0]["id"])
    datasets = db.get_datasets(revs[0]["id"])
    assert datasets[0]["file_size"] == 500


def test_watcher_locked_by_self_updates_size(tmp_path, tmp_path_factory):
    tmp2 = tmp_path_factory.mktemp("db2")
    f = tmp_path / "self.prt"
    f.write_bytes(b"A" * 200)

    db = Database(db_path=tmp2 / "w3.db")
    db.initialize()

    # Pre-create item chain and checkout record
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "self.prt", "", itype["id"], "alice")
    rev_pk = db.create_revision(item_pk, "A", "alpha", "alice")
    ds_pk = db.add_dataset(rev_pk, "self.prt", ".prt", str(f), 200, "alice")
    db.checkout_dataset(ds_pk, "alice", "ALICE-PC", str(f) + LOCK_SUFFIX)

    # Create lock file
    lock = f.parent / (f.name + LOCK_SUFFIX)
    lock.write_text(json.dumps({
        "checked_out_by": "alice", "checked_out_at": "2026-01-01T10:00:00",
        "station": "ALICE-PC", "dataset_id": ds_pk, "item_id": "ITM-00001", "revision": "A"
    }))

    # Simulate save with new size
    f.write_bytes(b"A" * 999)

    handler = _make_handler(db, username="alice")
    handler._handle_file_change(str(f))

    datasets = db.get_datasets(rev_pk)
    assert datasets[0]["file_size"] == 999


def test_watcher_locked_by_other_quarantines(tmp_path, tmp_path_factory):
    tmp2 = tmp_path_factory.mktemp("db3")
    f = tmp_path / "shared.prt"
    f.write_bytes(b"B" * 100)

    db = Database(db_path=tmp2 / "w4.db")
    db.initialize()

    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "shared.prt", "", itype["id"], "alice")
    rev_pk = db.create_revision(item_pk, "A", "alpha", "alice")
    ds_pk = db.add_dataset(rev_pk, "shared.prt", ".prt", str(f), 100, "alice")
    db.checkout_dataset(ds_pk, "alice", "ALICE-PC", str(f) + LOCK_SUFFIX)

    lock = f.parent / (f.name + LOCK_SUFFIX)
    lock.write_text(json.dumps({
        "checked_out_by": "alice", "checked_out_at": "2026-01-01T10:00:00",
        "station": "ALICE-PC", "dataset_id": ds_pk, "item_id": "ITM-00001", "revision": "A"
    }))

    # Bob tries to save while alice has it locked
    handler = _make_handler(db, username="bob")
    handler._handle_file_change(str(f))

    assert not f.exists()
    q_dir = f.parent / QUARANTINE_DIR
    assert q_dir.exists()
    assert any(q_dir.iterdir())


def test_watcher_skips_lock_files(tmp_path):
    lock_file = tmp_path / "part.prt.plmlock"
    lock_file.write_text("{}", encoding="utf-8")

    db = Database(db_path=tmp_path / "wskip.db")
    db.initialize()
    handler = _make_handler(db)

    # Should silently skip, no items created
    handler._handle_file_change(str(lock_file))
    assert db.list_items() == []


def test_watcher_debounce(tmp_path):
    f = tmp_path / "debounce.prt"
    f.write_bytes(b"D" * 50)

    db = Database(db_path=tmp_path / "wdebounce.db")
    db.initialize()
    handler = _make_handler(db)

    # Simulate two rapid events
    handler._debounce[str(f)] = __import__("time").time()  # mark as just-processed
    handler._handle_file_change(str(f))  # should be debounced

    # No items because _should_process would have returned False on the second call
    # We call _handle_file_change directly, bypassing _should_process, so test
    # the debounce check separately via _should_process
    assert handler._should_process(str(f)) is False


# ==================================================================
# Section 5: CLI commands
# ==================================================================

def test_cli_items_list_empty(tmp_path):
    db = Database(db_path=tmp_path / "cli.db")
    db.initialize()
    from plmlite.cli import _cmd_items_list
    result = _cmd_items_list(db=db)
    assert result == []


def test_cli_items_create(tmp_path):
    db = Database(db_path=tmp_path / "cli2.db")
    db.initialize()
    from plmlite.cli import _cmd_items_create
    new_id = _cmd_items_create("Bracket LH", "Mechanical Part", "left hand bracket", db=db)
    assert new_id == "ITM-00001"
    item = db.get_item(new_id)
    assert item["name"] == "Bracket LH"


def test_cli_items_list_after_create(tmp_path):
    db = Database(db_path=tmp_path / "cli3.db")
    db.initialize()
    from plmlite.cli import _cmd_items_create, _cmd_items_list
    _cmd_items_create("Part A", "Assembly", db=db)
    _cmd_items_create("Part B", "Document", db=db)
    rows = _cmd_items_list(db=db)
    assert len(rows) == 2


def test_cli_items_show(tmp_path):
    db = Database(db_path=tmp_path / "cli4.db")
    db.initialize()
    from plmlite.cli import _cmd_items_create, _cmd_items_show
    _cmd_items_create("Top Assembly", "Assembly", db=db)
    item = _cmd_items_show("ITM-00001", db=db)
    assert item["item_id"] == "ITM-00001"


def test_cli_revisions_list(tmp_path):
    db = Database(db_path=tmp_path / "cli5.db")
    db.initialize()
    from plmlite.cli import _cmd_items_create, _cmd_revisions_create, _cmd_revisions_list
    _cmd_items_create("Rotor", "Mechanical Part", db=db)
    _cmd_revisions_create("ITM-00001", "alpha", db=db)
    _cmd_revisions_create("ITM-00001", "alpha", db=db)
    revs = _cmd_revisions_list("ITM-00001", db=db)
    assert len(revs) == 2
    assert revs[0]["revision"] == "A"
    assert revs[1]["revision"] == "B"


def test_cli_checkout_and_checkin(tmp_path):
    f = tmp_path / "rotor.prt"
    f.write_bytes(b"NX" * 100)

    db = Database(db_path=tmp_path / "cli6.db")
    db.initialize()
    from plmlite.cli import _cmd_items_create, _cmd_revisions_create, _cmd_datasets_add

    _cmd_items_create("Rotor", "Mechanical Part", db=db)
    _cmd_revisions_create("ITM-00001", "alpha", db=db)
    _cmd_datasets_add("ITM-00001", "A", str(f), db=db)

    # Checkout via checkout engine directly (CLI cmd needs getpass.getuser())
    item = db.get_item("ITM-00001")
    rev = db.get_revision_by_name(item["id"], "A")
    datasets = db.get_datasets(rev["id"])
    ds = datasets[0]

    checkout_file(f, "alice", db, station="TEST-PC",
                  dataset_id=ds["id"], item_id="ITM-00001", revision="A")
    assert is_locked(f)
    co = db.get_checkout(ds["id"])
    assert co is not None

    checkin_file(f, "alice", db)
    assert not is_locked(f)
    assert db.get_checkout(ds["id"]) is None
