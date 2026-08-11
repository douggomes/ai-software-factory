"""SQLAlchemy schema definitions for the SQLite persistence layer.

Tables are defined using SQLAlchemy Core metadata. The schema enforces
foreign keys, constraints and indexes as required by the domain model.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Text

SCHEMA_VERSION: Final[int] = 1

metadata = MetaData()

schema_version_table = Table(
    "schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime, nullable=False),
)

runs_table = Table(
    "runs",
    metadata,
    Column("run_id", String(32), primary_key=True),
    Column("spec_id", String(128), nullable=False),
    Column("base_commit", String(40), nullable=False),
    Column("status", String(32), nullable=False),
    Column("config_hash", String(64), nullable=False),
)

task_executions_table = Table(
    "task_executions",
    metadata,
    Column("run_id", String(32), ForeignKey("runs.run_id"), primary_key=True),
    Column("task_id", String(32), primary_key=True),
    Column("base_commit", String(40), nullable=False),
    Column("worktree_path", Text, nullable=False),
    Column("stage", String(32), nullable=False),
    Column("repair_count", Integer, nullable=False, default=0),
    Column("failover_count", Integer, nullable=False, default=0),
    Column("version", Integer, nullable=False, default=1),
    Index("idx_task_executions_task_id", "task_id"),
)

events_table = Table(
    "events",
    metadata,
    Column("event_id", Integer, primary_key=True, autoincrement=True),
    Column("event_type", String(64), nullable=False),
    Column("timestamp", DateTime, nullable=False),
    Column("run_id", String(32), ForeignKey("runs.run_id"), nullable=False),
    Column("task_id", String(32), nullable=True),
    Column("attempt_id", String(32), nullable=True),
    Column("payload", Text, nullable=True),
    Column("schema_version", Integer, nullable=False, default=1),
    Index("idx_events_run_id", "run_id"),
    Index("idx_events_task_id", "task_id"),
)
