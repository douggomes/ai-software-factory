-- Migration 0001: Initial schema for AI Software Factory
-- Version: 1
-- Description: Create core tables for runs, task executions and events

CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME NOT NULL
);

CREATE TABLE runs (
    run_id TEXT PRIMARY KEY CHECK(length(run_id) <= 32),
    spec_id TEXT NOT NULL CHECK(length(spec_id) <= 128),
    base_commit TEXT NOT NULL CHECK(length(base_commit) = 40),
    status TEXT NOT NULL CHECK(length(status) <= 32),
    config_hash TEXT NOT NULL CHECK(length(config_hash) <= 64)
);

CREATE TABLE task_executions (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT NOT NULL CHECK(length(task_id) <= 32),
    base_commit TEXT NOT NULL CHECK(length(base_commit) = 40),
    worktree_path TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(length(stage) <= 32),
    repair_count INTEGER NOT NULL DEFAULT 0 CHECK(repair_count >= 0),
    failover_count INTEGER NOT NULL DEFAULT 0 CHECK(failover_count >= 0),
    version INTEGER NOT NULL DEFAULT 1 CHECK(version >= 1),
    PRIMARY KEY (run_id, task_id)
);

CREATE INDEX idx_task_executions_task_id ON task_executions(task_id);

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL CHECK(length(event_type) <= 64),
    timestamp DATETIME NOT NULL,
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    task_id TEXT CHECK(length(task_id) <= 32),
    attempt_id TEXT CHECK(length(attempt_id) <= 32),
    payload TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX idx_events_run_id ON events(run_id);
CREATE INDEX idx_events_task_id ON events(task_id);

INSERT INTO schema_version (version, applied_at) VALUES (1, datetime('now'));
