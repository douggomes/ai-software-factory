-- Migration 0001 — initial schema.
--
-- Generated from ai_software_factory.adapters.persistence.schema.metadata
-- (SQLAlchemy Core, sqlite dialect). That module is the single source of
-- truth for the schema, including CHECK constraints; this file is its
-- versioned, auditable, executable form and is the only path the adapter
-- uses to initialize or upgrade a database. Do not hand-edit the DDL here
-- without regenerating it from schema.py, or the two will drift.

CREATE TABLE runs (
	run_id VARCHAR(32) NOT NULL,
	spec_id VARCHAR(128) NOT NULL,
	base_commit VARCHAR(40) NOT NULL,
	status VARCHAR(32) NOT NULL,
	config_hash VARCHAR(64) NOT NULL,
	PRIMARY KEY (run_id),
	CONSTRAINT ck_runs_run_id_format CHECK (run_id GLOB 'run-*' AND length(run_id) = 16),
	CONSTRAINT ck_runs_base_commit CHECK (length(base_commit) = 40),
	CONSTRAINT ck_runs_config_hash CHECK (length(config_hash) = 64),
	CONSTRAINT ck_runs_status_enum CHECK (status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED'))
);

CREATE TABLE schema_version (
	version INTEGER NOT NULL,
	applied_at DATETIME NOT NULL,
	PRIMARY KEY (version),
	CONSTRAINT ck_schema_version_positive CHECK (version >= 1)
);

CREATE TABLE events (
	event_id INTEGER NOT NULL,
	event_type VARCHAR(64) NOT NULL,
	timestamp DATETIME NOT NULL,
	run_id VARCHAR(32) NOT NULL,
	task_id VARCHAR(32),
	attempt_id VARCHAR(32),
	payload TEXT,
	schema_version INTEGER NOT NULL,
	PRIMARY KEY (event_id),
	CONSTRAINT ck_events_event_type_enum CHECK (event_type IN ('RUN_STARTED', 'RUN_COMPLETED', 'RUN_FAILED', 'RUN_CANCELLED', 'TASK_QUEUED', 'TASK_STAGE_CHANGED', 'TASK_SUCCEEDED', 'TASK_FAILED', 'TASK_CANCELLED', 'ATTEMPT_STARTED', 'ATTEMPT_COMPLETED', 'ATTEMPT_FAILED', 'FAILURE_NORMALIZED', 'CONTINUATION_CREATED', 'CONTINUATION_STARTED', 'VALIDATION_SNAPSHOT', 'REPAIR_STARTED', 'REPAIR_COMPLETED', 'HUMAN_APPROVAL_REQUESTED', 'HUMAN_APPROVED', 'HUMAN_REJECTED')),
	CONSTRAINT ck_events_task_id_format CHECK (task_id IS NULL OR (task_id GLOB 'TASK-*' AND length(task_id) >= 8)),
	CONSTRAINT ck_events_attempt_id_format CHECK (attempt_id IS NULL OR (attempt_id GLOB 'att-*' AND length(attempt_id) = 16)),
	CONSTRAINT ck_events_schema_version CHECK (schema_version >= 1),
	FOREIGN KEY(run_id) REFERENCES runs (run_id)
);

CREATE INDEX idx_events_run_id ON events (run_id);

CREATE INDEX idx_events_task_id ON events (task_id);

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
	CONSTRAINT ck_task_executions_task_id_format CHECK (task_id GLOB 'TASK-*' AND length(task_id) >= 8),
	CONSTRAINT ck_task_executions_base_commit CHECK (length(base_commit) = 40),
	CONSTRAINT ck_task_executions_stage_enum CHECK (stage IN ('QUEUED', 'PREFLIGHT', 'WORKSPACE_PREPARING', 'CONTEXT_BUILDING', 'PLANNING', 'IMPLEMENTING', 'NORMALIZING_FAILURE', 'CREATING_CONTINUATION', 'WAITING_FOR_CONTINUATION', 'DETERMINISTIC_VALIDATION', 'REVIEWING', 'REPAIRING', 'AWAITING_HUMAN_APPROVAL', 'SUCCEEDED', 'REJECTED', 'ESCALATED', 'FAILED', 'CANCELLED')),
	CONSTRAINT ck_task_executions_repair_count CHECK (repair_count >= 0),
	CONSTRAINT ck_task_executions_failover_count CHECK (failover_count >= 0),
	CONSTRAINT ck_task_executions_version CHECK (version >= 1),
	FOREIGN KEY(run_id) REFERENCES runs (run_id)
);

CREATE INDEX idx_task_executions_task_id ON task_executions (task_id);
