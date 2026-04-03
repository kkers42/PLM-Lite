-- PLM Lite v2.2 schema
-- WAL mode enabled here and in _connect() for network share safety

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT    NOT NULL UNIQUE,
    role        TEXT    NOT NULL DEFAULT 'admin'
                CHECK(role IN ('admin','user','readonly')),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_types (
    id              INTEGER PRIMARY KEY,
    name            TEXT    NOT NULL UNIQUE,
    lifecycle_mode  TEXT    NOT NULL
                    CHECK(lifecycle_mode IN ('production','prototype')),
    workflow_config TEXT    NOT NULL DEFAULT '{"steps":["confirm"]}'
);

CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY,
    item_id      TEXT    NOT NULL UNIQUE,
    name         TEXT    NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    item_type_id INTEGER NOT NULL REFERENCES item_types(id),
    status       TEXT    NOT NULL DEFAULT 'in_work'
                 CHECK(status IN ('in_work','released','obsolete','active','locked')),
    created_by   INTEGER NOT NULL REFERENCES users(id),
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_revisions (
    id                 INTEGER PRIMARY KEY,
    item_id            INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    revision           TEXT    NOT NULL,
    revision_type      TEXT    NOT NULL CHECK(revision_type IN ('alpha','numeric')),
    status             TEXT    NOT NULL DEFAULT 'in_work'
                       CHECK(status IN ('in_work','released','locked')),
    created_by         INTEGER NOT NULL REFERENCES users(id),
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    released_by        INTEGER REFERENCES users(id),
    released_at        TIMESTAMP,
    change_description TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS datasets (
    id          INTEGER PRIMARY KEY,
    revision_id INTEGER NOT NULL REFERENCES item_revisions(id) ON DELETE CASCADE,
    filename    TEXT    NOT NULL,
    file_type   TEXT    NOT NULL DEFAULT '',
    stored_path TEXT    NOT NULL,
    file_size   INTEGER NOT NULL DEFAULT 0,
    added_by    INTEGER NOT NULL REFERENCES users(id),
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkouts (
    id              INTEGER PRIMARY KEY,
    dataset_id      INTEGER NOT NULL UNIQUE REFERENCES datasets(id) ON DELETE CASCADE,
    checked_out_by  INTEGER NOT NULL REFERENCES users(id),
    checked_out_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    station_name    TEXT    NOT NULL DEFAULT '',
    lock_file_path  TEXT    NOT NULL DEFAULT '',
    temp_path       TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS temp_files (
    id             INTEGER PRIMARY KEY,
    checkout_id    INTEGER REFERENCES checkouts(id) ON DELETE CASCADE,
    dataset_id     INTEGER NOT NULL REFERENCES datasets(id),
    username       TEXT    NOT NULL,
    temp_path      TEXT    NOT NULL,
    is_checked_out INTEGER NOT NULL DEFAULT 0,
    copied_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflows (
    id           INTEGER PRIMARY KEY,
    item_type_id INTEGER NOT NULL UNIQUE REFERENCES item_types(id) ON DELETE CASCADE,
    config_json  TEXT    NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS audit_log (
    id           INTEGER PRIMARY KEY,
    action       TEXT    NOT NULL,
    entity_type  TEXT    NOT NULL,
    entity_id    TEXT    NOT NULL,
    performed_by INTEGER REFERENCES users(id),
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    detail       TEXT    NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS item_relationships (
    id             INTEGER PRIMARY KEY,
    parent_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    child_item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    quantity       INTEGER NOT NULL DEFAULT 1,
    added_by       INTEGER REFERENCES users(id),
    added_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_item_id, child_item_id)
);

CREATE TABLE IF NOT EXISTS item_attributes (
    id         INTEGER PRIMARY KEY,
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    attr_key   TEXT    NOT NULL,
    attr_value TEXT    NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(item_id, attr_key)
);
CREATE INDEX IF NOT EXISTS idx_attrs_item_id ON item_attributes(item_id);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_items_item_id        ON items(item_id);
CREATE INDEX IF NOT EXISTS idx_revisions_item_id    ON item_revisions(item_id);
CREATE INDEX IF NOT EXISTS idx_datasets_filename    ON datasets(filename);
CREATE INDEX IF NOT EXISTS idx_checkouts_dataset_id ON checkouts(dataset_id);
CREATE INDEX IF NOT EXISTS idx_rel_parent ON item_relationships(parent_item_id);
CREATE INDEX IF NOT EXISTS idx_rel_child  ON item_relationships(child_item_id);
CREATE INDEX IF NOT EXISTS idx_temp_files_username  ON temp_files(username);
CREATE INDEX IF NOT EXISTS idx_temp_files_dataset   ON temp_files(dataset_id);

-- Seed item types
INSERT OR IGNORE INTO item_types(name, lifecycle_mode) VALUES
    ('Mechanical Part', 'production'),
    ('Assembly',        'production'),
    ('Prototype',       'prototype'),
    ('Document',        'production');
