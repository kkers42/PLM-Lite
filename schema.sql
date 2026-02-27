-- PLM Lite V1.0 — SQLite Schema
-- Applied at startup via database.initialize()

-- ── Roles ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS roles (
    id           INTEGER PRIMARY KEY,
    name         TEXT    NOT NULL UNIQUE,
    can_release  INTEGER NOT NULL DEFAULT 1,
    can_view     INTEGER NOT NULL DEFAULT 1,
    can_write    INTEGER NOT NULL DEFAULT 1,
    can_upload   INTEGER NOT NULL DEFAULT 1,
    can_checkout INTEGER NOT NULL DEFAULT 1,
    can_admin    INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Users ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE,
    email         TEXT    UNIQUE,
    password_hash TEXT,                         -- bcrypt, NULL for OAuth users
    role_id       INTEGER REFERENCES roles(id) ON DELETE SET NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active   TIMESTAMP
);

-- ── Parts ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parts (
    id                   INTEGER PRIMARY KEY,
    part_number          TEXT    NOT NULL UNIQUE,
    part_name            TEXT    NOT NULL,
    part_revision        TEXT    NOT NULL DEFAULT 'A',
    description          TEXT,
    part_level           TEXT,               -- System / Subsystem / Component / etc.
    release_status       TEXT    NOT NULL DEFAULT 'Prototype',  -- Prototype | Released
    checked_out_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    checked_out_at       TIMESTAMP,
    checked_out_station  TEXT,               -- hostname or IP for multi-station tracking
    created_by           INTEGER NOT NULL REFERENCES users(id),
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_locked            INTEGER NOT NULL DEFAULT 0   -- 1 after release
);

-- ── Part Attributes (custom key-value, expandable) ──────────────────────────
CREATE TABLE IF NOT EXISTS part_attributes (
    id         INTEGER PRIMARY KEY,
    part_id    INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    attr_key   TEXT    NOT NULL,
    attr_value TEXT,
    attr_order INTEGER NOT NULL DEFAULT 0,   -- 1-10 for standard named slots
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(part_id, attr_key)
);

-- ── Part Revisions (history snapshots) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS part_revisions (
    id             INTEGER PRIMARY KEY,
    part_id        INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    revision_label TEXT    NOT NULL,          -- A, B, C ...
    description    TEXT,
    changed_by     INTEGER NOT NULL REFERENCES users(id),
    changed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    snapshot_json  TEXT                       -- JSON of parts row at this revision
);

-- ── Part Relationships (assembly tree) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS part_relationships (
    id                INTEGER PRIMARY KEY,
    parent_part_id    INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    child_part_id     INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    quantity          REAL    NOT NULL DEFAULT 1.0,
    relationship_type TEXT    NOT NULL DEFAULT 'assembly',  -- assembly | reference | drawing
    notes             TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(parent_part_id, child_part_id)
);

-- ── Documents (attached files — CAD or non-CAD) ─────────────────────────────
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY,
    part_id     INTEGER REFERENCES parts(id) ON DELETE SET NULL,   -- NULL = global doc
    filename    TEXT    NOT NULL,
    stored_path TEXT    NOT NULL,
    file_type   TEXT    NOT NULL,   -- lowercase extension without dot, e.g. 'prt', 'pdf'
    description TEXT,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── File Versions (backup history for CAD files only, max 3) ────────────────
CREATE TABLE IF NOT EXISTS file_versions (
    id            INTEGER PRIMARY KEY,
    document_id   INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_label TEXT    NOT NULL,   -- _MMDD_HHMM timestamp string
    backup_path   TEXT    NOT NULL,
    file_size     INTEGER,
    saved_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    saved_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_current    INTEGER NOT NULL DEFAULT 0   -- 1 = this is the active GOD file version
);

-- ── Audit Log ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action      TEXT    NOT NULL,          -- create_part, checkout, release, upload, etc.
    entity_type TEXT    NOT NULL,          -- part | document | user | role | relationship
    entity_id   INTEGER,
    detail_json TEXT,
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_parts_pn        ON parts(part_number);
CREATE INDEX IF NOT EXISTS idx_parts_status    ON parts(release_status);
CREATE INDEX IF NOT EXISTS idx_parts_checkout  ON parts(checked_out_by);
CREATE INDEX IF NOT EXISTS idx_parts_created   ON parts(created_by);
CREATE INDEX IF NOT EXISTS idx_attrs_part      ON part_attributes(part_id);
CREATE INDEX IF NOT EXISTS idx_revisions_part  ON part_revisions(part_id);
CREATE INDEX IF NOT EXISTS idx_rel_parent      ON part_relationships(parent_part_id);
CREATE INDEX IF NOT EXISTS idx_rel_child       ON part_relationships(child_part_id);
CREATE INDEX IF NOT EXISTS idx_docs_part       ON documents(part_id);
CREATE INDEX IF NOT EXISTS idx_versions_doc    ON file_versions(document_id);
CREATE INDEX IF NOT EXISTS idx_audit_time      ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_entity    ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_users_role      ON users(role_id);
