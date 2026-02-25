-- PLMLITE database schema
-- SQLite schema for tracking NX12 CAD datasets

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL UNIQUE,
    current_version INTEGER DEFAULT 1,
    lifecycle_state TEXT DEFAULT 'design',
    checked_out_by TEXT,
    checked_out_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS versions (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    version_num INTEGER NOT NULL,
    backup_path TEXT,
    saved_by TEXT,
    saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    file_size INTEGER,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY,
    parent_file_id INTEGER NOT NULL,
    child_file_id INTEGER NOT NULL,
    relationship_type TEXT DEFAULT 'assembly',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_file_id) REFERENCES files(id) ON DELETE CASCADE,
    FOREIGN KEY (child_file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkout_log (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    username TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_versions_file_id ON versions(file_id);
CREATE INDEX IF NOT EXISTS idx_versions_file_saved ON versions(file_id, saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS idx_checkout_log_file ON checkout_log(file_id);
CREATE INDEX IF NOT EXISTS idx_checkout_log_time ON checkout_log(timestamp);
