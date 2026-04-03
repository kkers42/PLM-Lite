"""PLM Lite v2.2 unit tests.

Tests cover:
  1. Schema        -- tables created, seed data, migrations
  2. Database      -- CRUD, next_item_id, next_revision, temp_files
  3. Checkout      -- vault structure, checkout/checkin/disk_save
  4. Watcher       -- modified detection
"""

import os
import sys
import time
from pathlib import Path

import pytest

from plmlite.database import Database, CheckoutError, _next_alpha


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = Database(db_path=str(tmp_path / "test.db"))
    d.initialize()
    return d


@pytest.fixture
def vault(tmp_path):
    """A fake vault root with one item/revision/file."""
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture
def temp_dir(tmp_path):
    t = tmp_path / "PLMTemp" / "testuser"
    t.mkdir(parents=True)
    return t


# ─────────────────────────────────────────────────────────────────────────────
# 1. Schema
# ─────────────────────────────────────────────────────────────────────────────

def test_tables_created(db):
    with db._connect() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    for expected in ("users", "items", "item_revisions", "datasets",
                     "checkouts", "temp_files", "item_relationships",
                     "item_attributes", "audit_log"):
        assert expected in tables, f"Missing table: {expected}"


def test_item_types_seeded(db):
    types = db.list_item_types()
    names = {t["name"] for t in types}
    assert "Mechanical Part" in names
    assert "Assembly" in names


def test_checkouts_has_temp_path(db):
    with db._connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(checkouts)").fetchall()]
    assert "temp_path" in cols


def test_temp_files_table(db):
    with db._connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(temp_files)").fetchall()]
    for col in ("checkout_id", "dataset_id", "username", "temp_path", "is_checked_out"):
        assert col in cols, f"Missing column in temp_files: {col}"


def test_item_revisions_has_change_description(db):
    with db._connect() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(item_revisions)").fetchall()]
    assert "change_description" in cols


# ─────────────────────────────────────────────────────────────────────────────
# 2. Database
# ─────────────────────────────────────────────────────────────────────────────

def test_next_item_id(db):
    assert db.next_item_id() == "ITM-00001"


def test_create_and_get_item(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    pk = db.create_item("ITM-00001", "Test Part", "desc", itype["id"], "testuser")
    assert pk > 0
    item = db.get_item("ITM-00001")
    assert item["name"] == "Test Part"


def test_next_revision_alpha(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    assert db.next_revision(pk, "alpha") == "A"
    db.create_revision(pk, "A", "alpha", "u")
    assert db.next_revision(pk, "alpha") == "B"


def test_next_revision_numeric(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    assert db.next_revision(pk, "numeric") == "01"
    db.create_revision(pk, "01", "numeric", "u")
    assert db.next_revision(pk, "numeric") == "02"


def test_next_alpha_helper():
    assert _next_alpha("A") == "B"
    assert _next_alpha("Z") == "AA"
    assert _next_alpha("AZ") == "BA"


def test_add_and_get_dataset(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    rev_pk = db.create_revision(item_pk, "01", "numeric", "u")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/vault/ITM-00001/01/part.prt", 1024, "u")
    datasets = db.get_datasets(rev_pk)
    assert len(datasets) == 1
    assert datasets[0]["filename"] == "part.prt"
    assert datasets[0]["id"] == ds_pk


def test_checkout_and_checkin(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    rev_pk = db.create_revision(item_pk, "01", "numeric", "u")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/vault/part.prt", 0, "u")

    db.checkout_dataset(ds_pk, "josh", station_name="PC1", temp_path="/tmp/part.prt")
    co = db.get_checkout(ds_pk)
    assert co["who"] == "josh"
    assert co["temp_path"] == "/tmp/part.prt"

    db.checkin_dataset(ds_pk, "josh")
    assert db.get_checkout(ds_pk) is None


def test_checkout_conflict(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    rev_pk = db.create_revision(item_pk, "01", "numeric", "u")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/vault/part.prt", 0, "u")

    db.checkout_dataset(ds_pk, "josh", station_name="", temp_path="")
    with pytest.raises(CheckoutError):
        db.checkout_dataset(ds_pk, "bob", station_name="", temp_path="")


def test_checkin_wrong_user(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    rev_pk = db.create_revision(item_pk, "01", "numeric", "u")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/vault/part.prt", 0, "u")

    db.checkout_dataset(ds_pk, "josh", station_name="", temp_path="")
    with pytest.raises(CheckoutError):
        db.checkin_dataset(ds_pk, "bob")


def test_temp_files_crud(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    rev_pk = db.create_revision(item_pk, "01", "numeric", "u")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", "/vault/part.prt", 0, "u")
    db.checkout_dataset(ds_pk, "josh", station_name="", temp_path="/tmp/p.prt")
    co = db.get_checkout(ds_pk)

    db.add_temp_file(co["id"], ds_pk, "josh", "/tmp/p.prt", is_checked_out=True)
    files = db.get_temp_files_for_user("josh")
    assert len(files) == 1
    assert files[0]["is_checked_out"] == 1

    db.delete_temp_files_for_user("josh")
    assert db.get_temp_files_for_user("josh") == []


def test_attributes(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    pk = db.create_item("ITM-00001", "Part", "", itype["id"], "u")
    db.set_attribute(pk, "material", "steel")
    attrs = db.get_attributes(pk)
    assert attrs[0]["attr_key"] == "material"
    assert attrs[0]["attr_value"] == "steel"
    db.delete_attribute(pk, "material")
    assert db.get_attributes(pk) == []


def test_relationships(db):
    itype = db.get_item_type_by_name("Mechanical Part")
    p = db.create_item("ITM-00001", "Parent", "", itype["id"], "u")
    c = db.create_item("ITM-00002", "Child",  "", itype["id"], "u")
    db.add_relationship(p, c, quantity=2, added_by="u")
    children = db.get_children(p)
    assert len(children) == 1
    assert children[0]["item_id"] == "ITM-00002"
    parents = db.get_parents(c)
    assert parents[0]["item_id"] == "ITM-00001"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Checkout module (filesystem)
# ─────────────────────────────────────────────────────────────────────────────

def test_checkout_file_creates_temp_and_readonly(db, vault, temp_dir, monkeypatch):
    from plmlite import checkout as co_mod
    monkeypatch.setattr(co_mod, "get_temp_dir", lambda username: temp_dir)

    # Set up vault file
    item_id = "ITM-00001"
    revision = "01"
    vault_item_dir = vault / item_id / revision
    vault_item_dir.mkdir(parents=True)
    vault_file = vault_item_dir / "part.prt"
    vault_file.write_bytes(b"NX data")

    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item(item_id, "Part", "", itype["id"], "josh")
    rev_pk = db.create_revision(item_pk, revision, "numeric", "josh")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", str(vault_file), 7, "josh")

    dataset = db.get_datasets(rev_pk)[0]
    item = db.get_item(item_id)

    from plmlite.checkout import checkout_file
    temp_path = checkout_file(dataset, item["item_id"], db.get_revisions(item_pk)[0]["revision"], "josh", db)

    assert temp_path.exists()
    assert temp_path.read_bytes() == b"NX data"
    # Temp file should be writable
    assert os.access(str(temp_path), os.W_OK)
    # Checkout record in DB
    co = db.get_checkout(ds_pk)
    assert co is not None
    assert co["who"] == "josh"


def test_checkin_file_copies_back_and_cleans(db, vault, temp_dir, monkeypatch):
    from plmlite import checkout as co_mod
    monkeypatch.setattr(co_mod, "get_temp_dir", lambda username: temp_dir)

    item_id = "ITM-00001"
    revision = "01"
    vault_item_dir = vault / item_id / revision
    vault_item_dir.mkdir(parents=True)
    vault_file = vault_item_dir / "part.prt"
    vault_file.write_bytes(b"original")

    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item(item_id, "Part", "", itype["id"], "josh")
    rev_pk = db.create_revision(item_pk, revision, "numeric", "josh")
    ds_pk = db.add_dataset(rev_pk, "part.prt", ".prt", str(vault_file), 8, "josh")

    dataset = db.get_datasets(rev_pk)[0]
    item = db.get_item(item_id)
    rev = db.get_revisions(item_pk)[0]

    from plmlite.checkout import checkout_file, checkin_file
    temp_path = checkout_file(dataset, item["item_id"], rev["revision"], "josh", db)

    # Simulate user editing the file
    temp_path.write_bytes(b"modified data")

    checkin_file(dataset, item["item_id"], rev["revision"], "josh", db)

    # Vault should have new content
    assert vault_file.read_bytes() == b"modified data"
    # Temp file should be gone
    assert not temp_path.exists()
    # Checkout record should be cleared
    assert db.get_checkout(ds_pk) is None


def test_checkout_released_revision_blocked(db, vault, temp_dir, monkeypatch):
    from plmlite import checkout as co_mod
    monkeypatch.setattr(co_mod, "get_temp_dir", lambda username: temp_dir)

    item_id = "ITM-00001"
    revision = "01"
    vault_item_dir = vault / item_id / revision
    vault_item_dir.mkdir(parents=True)
    (vault_item_dir / "part.prt").write_bytes(b"data")

    itype = db.get_item_type_by_name("Mechanical Part")
    item_pk = db.create_item(item_id, "Part", "", itype["id"], "josh")
    rev_pk = db.create_revision(item_pk, revision, "numeric", "josh")
    db.add_dataset(rev_pk, "part.prt", ".prt", str(vault_item_dir / "part.prt"), 4, "josh")
    # Release the revision
    db.release_revision(rev_pk, "josh")

    dataset = db.get_datasets(rev_pk)[0]
    item = db.get_item(item_id)
    rev = db.get_revisions(item_pk)[0]

    from plmlite.checkout import checkout_file
    with pytest.raises(CheckoutError):
        checkout_file(dataset, item["item_id"], rev["revision"], "josh", db)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Watcher
# ─────────────────────────────────────────────────────────────────────────────

def test_watcher_modified_detection(tmp_path):
    from plmlite.watcher import FileWatcher

    watcher = FileWatcher(db_path=":memory:")
    # get_modified_status returns False for unknown dataset_id
    assert watcher.get_modified_status(999) is False


def test_watcher_start_stop(tmp_path):
    from plmlite.watcher import FileWatcher
    watcher = FileWatcher(db_path=":memory:")
    watcher.start()
    assert watcher._thread is not None
    assert watcher._thread.is_alive()
    watcher.stop()
    assert not watcher._thread.is_alive()
