-- 0001_init.sql
-- Initial schema for RabbitSync.
--
-- Conventions:
--   * Every table has created_at and updated_at columns stored as ISO-8601
--     UTC strings (SQLite's date/time functions handle them transparently).
--   * Foreign keys are declared and enforced (PRAGMA foreign_keys = ON, set
--     in db/connection.py for every connection).
--   * Append-only / hash-chained tables (receipts, journal_entries) have no
--     UPDATE path in the application; rows are inserted only.
--   * Blobs on the filesystem are referenced by rows in `blobs` so every blob
--     has a row, an SHA-256, and a size -- drift is detectable.
--
-- Note: the `migrations` table is bootstrapped by db/connection.py before any
-- migration runs, so this file does not (re)create it.

CREATE TABLE settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

-- Credential references. The actual secret lives in the OS keyring under
-- (keyring_service, keyring_account); this table records only metadata.
CREATE TABLE credential_refs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,            -- 'github-pat' | 'git-https' | 'ssh-key-path'
    label               TEXT NOT NULL,
    keyring_service     TEXT NOT NULL,
    keyring_account     TEXT NOT NULL,
    extra_json          TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (keyring_service, keyring_account)
);

CREATE TABLE github_accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    login               TEXT NOT NULL UNIQUE,
    scopes              TEXT NOT NULL DEFAULT '',  -- comma-separated
    credential_ref_id   INTEGER NOT NULL REFERENCES credential_refs(id) ON DELETE RESTRICT,
    last_synced_at      TEXT,
    expires_at          TEXT,                      -- token expiration if known
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE github_repos (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES github_accounts(id) ON DELETE CASCADE,
    full_name           TEXT NOT NULL,             -- "owner/repo"
    default_branch      TEXT,
    ssh_url             TEXT,
    https_url           TEXT,
    private             INTEGER NOT NULL DEFAULT 0,
    description         TEXT,
    pushed_at           TEXT,
    cached_at           TEXT NOT NULL,
    UNIQUE (account_id, full_name)
);

CREATE TABLE pairs (
    id                          TEXT PRIMARY KEY,        -- UUIDv4
    label                       TEXT NOT NULL,
    source_path                 TEXT NOT NULL,
    source_git_root             TEXT,
    source_subpath              TEXT,
    copy_path                   TEXT NOT NULL,
    copy_git_root               TEXT,
    copy_subpath                TEXT,
    target_branch               TEXT,
    ignore_files_json           TEXT NOT NULL DEFAULT '[]',
    commit_message_template     TEXT NOT NULL DEFAULT 'sync: {src_branch}@{src_sha} — {n} files',
    auto_push                   INTEGER NOT NULL DEFAULT 0,
    sync_check_interval_s       INTEGER NOT NULL DEFAULT 30,
    secret_scan_enabled         INTEGER NOT NULL DEFAULT 1,
    snapshot_before_pipeline    INTEGER NOT NULL DEFAULT 1,
    created_at                  TEXT NOT NULL,
    updated_at                  TEXT NOT NULL
);

CREATE TABLE blobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL,                -- 'snapshot' | 'quarantine' | 'pipeline-artifact' | 'db-backup'
    path                TEXT NOT NULL,
    sha256              TEXT NOT NULL,
    size                INTEGER NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE INDEX idx_blobs_kind ON blobs(kind);

CREATE TABLE syncs (
    sync_id             TEXT PRIMARY KEY,             -- UUIDv4
    pair_id             TEXT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,                -- 'pending' | 'running' | 'ok' | 'aborted' | 'failed'
    files_added         INTEGER NOT NULL DEFAULT 0,
    files_modified      INTEGER NOT NULL DEFAULT 0,
    files_quarantined   INTEGER NOT NULL DEFAULT 0,
    snapshot_blob_id    INTEGER REFERENCES blobs(id) ON DELETE SET NULL,
    source_sha          TEXT,
    copy_commit_sha     TEXT
);

CREATE INDEX idx_syncs_pair ON syncs(pair_id, started_at DESC);

-- Append-only journal. fsynced per row during sync via synchronous=FULL.
CREATE TABLE journal_entries (
    sync_id             TEXT NOT NULL REFERENCES syncs(sync_id) ON DELETE CASCADE,
    seq                 INTEGER NOT NULL,
    action              TEXT NOT NULL,                -- 'plan' | 'snapshot' | 'write' | 'quarantine' | 'verify' | 'commit' | 'push' | 'close'
    rel_path            TEXT,
    prev_hash           TEXT,
    new_hash            TEXT,
    ts                  TEXT NOT NULL,
    extra_json          TEXT,
    PRIMARY KEY (sync_id, seq)
);

-- Hash-chained, append-only audit log.
CREATE TABLE receipts (
    sync_id             TEXT PRIMARY KEY REFERENCES syncs(sync_id) ON DELETE CASCADE,
    prev_receipt_hash   TEXT,                         -- NULL for the first row only
    snapshot_hash       TEXT,
    journal_hash        TEXT NOT NULL,
    payload_json        TEXT NOT NULL,
    hash                TEXT NOT NULL,
    created_at          TEXT NOT NULL
);

CREATE TABLE file_cache (
    pair_id             TEXT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    side                TEXT NOT NULL,                -- 'source' | 'copy'
    rel_path            TEXT NOT NULL,
    size                INTEGER NOT NULL,
    mtime_ns            INTEGER NOT NULL,
    content_hash        TEXT,                         -- xxhash hex; NULL until first verified
    last_seen_ts        TEXT NOT NULL,
    PRIMARY KEY (pair_id, side, rel_path)
);

CREATE TABLE pipelines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pair_id             TEXT NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    ordinal             INTEGER NOT NULL,
    pre_sync            INTEGER NOT NULL DEFAULT 0,
    post_sync           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (pair_id, name)
);

CREATE TABLE pipeline_steps (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id         INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    ordinal             INTEGER NOT NULL,
    name                TEXT NOT NULL,
    argv_json           TEXT NOT NULL,                -- JSON list of strings
    cwd_kind            TEXT NOT NULL DEFAULT 'source', -- 'source' | 'copy' | 'subpath'
    cwd_subpath         TEXT,                         -- only used when cwd_kind='subpath'
    env_extra_json      TEXT NOT NULL DEFAULT '{}',
    timeout_s           INTEGER NOT NULL DEFAULT 300,
    on_fail             TEXT NOT NULL DEFAULT 'abort', -- 'abort' | 'continue'
    inputs_globs_json   TEXT NOT NULL DEFAULT '[]',
    UNIQUE (pipeline_id, ordinal)
);

CREATE TABLE pipeline_runs (
    run_id              TEXT PRIMARY KEY,             -- UUIDv4
    pipeline_id         INTEGER NOT NULL REFERENCES pipelines(id) ON DELETE CASCADE,
    sync_id             TEXT REFERENCES syncs(sync_id) ON DELETE SET NULL,
    triggered_as        TEXT NOT NULL,                -- 'standalone' | 'pre-sync' | 'post-sync'
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,                -- 'running' | 'ok' | 'failed' | 'timeout' | 'cancelled'
    artifacts_dir       TEXT NOT NULL                 -- path under data/pipelines/
);

CREATE INDEX idx_pipeline_runs_pipeline ON pipeline_runs(pipeline_id, started_at DESC);

CREATE TABLE step_runs (
    run_id              TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    step_id             INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    ordinal             INTEGER NOT NULL,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,                -- 'running' | 'ok' | 'failed' | 'timeout' | 'cached' | 'skipped'
    exit_code           INTEGER,
    cached_from_run_id  TEXT REFERENCES pipeline_runs(run_id) ON DELETE SET NULL,
    PRIMARY KEY (run_id, step_id)
);

CREATE TABLE step_cache (
    step_id             INTEGER NOT NULL REFERENCES pipeline_steps(id) ON DELETE CASCADE,
    input_hash          TEXT NOT NULL,
    source_run_id       TEXT NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    expires_at          TEXT,
    PRIMARY KEY (step_id, input_hash)
);
