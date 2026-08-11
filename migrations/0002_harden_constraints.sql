-- Migration 0002: harden identifiers, hashes, enums and counters.
-- Version: 2
-- Rebuilds V1 tables because SQLite cannot add CHECK constraints in place.

DROP INDEX idx_events_run_id;
DROP INDEX idx_events_task_id;
DROP INDEX idx_task_executions_task_id;

ALTER TABLE events RENAME TO events_v1;
ALTER TABLE task_executions RENAME TO task_executions_v1;
ALTER TABLE runs RENAME TO runs_v1;

CREATE TABLE runs (
    run_id VARCHAR(32) NOT NULL,
    spec_id VARCHAR(128) NOT NULL,
    base_commit VARCHAR(40) NOT NULL,
    status VARCHAR(32) NOT NULL,
    config_hash VARCHAR(64) NOT NULL,
    PRIMARY KEY (run_id),
    CONSTRAINT ck_runs_run_id_format CHECK (
        substr(run_id, 1, 4) = 'run-'
        AND length(run_id) = 16
        AND substr(run_id, 5) NOT GLOB '*[^a-z0-9]*'
    ),
    CONSTRAINT ck_runs_base_commit CHECK (
        length(base_commit) = 40
        AND base_commit NOT GLOB '*[^0-9a-f]*'
    ),
    CONSTRAINT ck_runs_config_hash CHECK (
        length(config_hash) = 64
        AND config_hash NOT GLOB '*[^0-9a-f]*'
    ),
    CONSTRAINT ck_runs_status_enum CHECK (
        status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')
    )
);

CREATE TABLE task_executions (
    run_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32) NOT NULL,
    base_commit VARCHAR(40) NOT NULL,
    worktree_path TEXT NOT NULL,
    stage VARCHAR(32) NOT NULL,
    repair_count INTEGER NOT NULL,
    failover_count INTEGER NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (run_id, task_id),
    CONSTRAINT ck_task_executions_task_id_format CHECK (
        substr(task_id, 1, 5) = 'TASK-'
        AND length(task_id) >= 8
        AND substr(task_id, 6) NOT GLOB '*[^0-9]*'
    ),
    CONSTRAINT ck_task_executions_base_commit CHECK (
        length(base_commit) = 40
        AND base_commit NOT GLOB '*[^0-9a-f]*'
    ),
    CONSTRAINT ck_task_executions_stage_enum CHECK (
        stage IN (
            'QUEUED', 'PREFLIGHT', 'WORKSPACE_PREPARING', 'CONTEXT_BUILDING',
            'PLANNING', 'IMPLEMENTING', 'NORMALIZING_FAILURE',
            'CREATING_CONTINUATION', 'WAITING_FOR_CONTINUATION',
            'DETERMINISTIC_VALIDATION', 'REVIEWING', 'REPAIRING',
            'AWAITING_HUMAN_APPROVAL', 'SUCCEEDED', 'REJECTED', 'ESCALATED',
            'FAILED', 'CANCELLED'
        )
    ),
    CONSTRAINT ck_task_executions_repair_count CHECK (repair_count >= 0),
    CONSTRAINT ck_task_executions_failover_count CHECK (failover_count >= 0),
    CONSTRAINT ck_task_executions_version CHECK (version >= 1),
    FOREIGN KEY(run_id) REFERENCES runs (run_id)
);

CREATE INDEX idx_task_executions_task_id ON task_executions (task_id);

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type VARCHAR(64) NOT NULL,
    timestamp DATETIME NOT NULL,
    run_id VARCHAR(32) NOT NULL,
    task_id VARCHAR(32),
    attempt_id VARCHAR(32),
    payload TEXT,
    schema_version INTEGER NOT NULL,
    CONSTRAINT ck_events_event_type_enum CHECK (
        event_type IN (
            'RUN_STARTED', 'RUN_COMPLETED', 'RUN_FAILED', 'RUN_CANCELLED',
            'TASK_QUEUED', 'TASK_STAGE_CHANGED', 'TASK_SUCCEEDED', 'TASK_FAILED',
            'TASK_CANCELLED', 'ATTEMPT_STARTED', 'ATTEMPT_COMPLETED',
            'ATTEMPT_FAILED', 'FAILURE_NORMALIZED', 'CONTINUATION_CREATED',
            'CONTINUATION_STARTED', 'VALIDATION_SNAPSHOT', 'REPAIR_STARTED',
            'REPAIR_COMPLETED', 'HUMAN_APPROVAL_REQUESTED', 'HUMAN_APPROVED',
            'HUMAN_REJECTED'
        )
    ),
    CONSTRAINT ck_events_task_id_format CHECK (
        task_id IS NULL OR (
            substr(task_id, 1, 5) = 'TASK-'
            AND length(task_id) >= 8
            AND substr(task_id, 6) NOT GLOB '*[^0-9]*'
        )
    ),
    CONSTRAINT ck_events_attempt_id_format CHECK (
        attempt_id IS NULL OR (
            substr(attempt_id, 1, 4) = 'att-'
            AND length(attempt_id) = 16
            AND substr(attempt_id, 5) NOT GLOB '*[^a-z0-9]*'
        )
    ),
    CONSTRAINT ck_events_schema_version CHECK (schema_version >= 1),
    FOREIGN KEY(run_id) REFERENCES runs (run_id)
);

CREATE INDEX idx_events_run_id ON events (run_id);
CREATE INDEX idx_events_task_id ON events (task_id);

INSERT INTO runs (run_id, spec_id, base_commit, status, config_hash)
SELECT run_id, spec_id, base_commit, status, config_hash FROM runs_v1;

INSERT INTO task_executions (
    run_id, task_id, base_commit, worktree_path, stage,
    repair_count, failover_count, version
)
SELECT
    run_id, task_id, base_commit, worktree_path, stage,
    repair_count, failover_count, version
FROM task_executions_v1;

INSERT INTO events (
    event_id, event_type, timestamp, run_id, task_id,
    attempt_id, payload, schema_version
)
SELECT
    event_id, event_type, timestamp, run_id, task_id,
    attempt_id, payload, schema_version
FROM events_v1;

DROP TABLE events_v1;
DROP TABLE task_executions_v1;
DROP TABLE runs_v1;

CREATE TABLE schema_version_v2 (
    version INTEGER NOT NULL,
    applied_at DATETIME NOT NULL,
    PRIMARY KEY (version),
    CONSTRAINT ck_schema_version_positive CHECK (version >= 1)
);

INSERT INTO schema_version_v2 (version, applied_at)
SELECT version, applied_at FROM schema_version;

INSERT INTO schema_version_v2 (version, applied_at)
VALUES (2, datetime('now'));

DROP TABLE schema_version;
ALTER TABLE schema_version_v2 RENAME TO schema_version;
