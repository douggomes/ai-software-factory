"""SQLAlchemy schema definitions for the SQLite persistence layer.

Tables are defined using SQLAlchemy Core metadata. This metadata is the
single source of truth for the schema: enum-valued columns constrain
against the domain's own enums (no duplicated string lists to drift), and
CHECK constraints mirror the value-object invariants from
``ai_software_factory.core.ids`` as a database-level backstop. The versioned
SQL in ``migrations/`` is generated from this metadata rather than hand
duplicated, so there is exactly one definition to keep correct.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)

from ai_software_factory.core.events import EventType
from ai_software_factory.core.models import RunStatus, TaskStage

SCHEMA_VERSION: Final[int] = 2

#: Mirror ai_software_factory.core.ids value-object formats: "run-" + 12
#: lowercase alphanumerics, "att-" + 12 lowercase alphanumerics.
RUN_ID_LENGTH: Final[int] = 16
ATTEMPT_ID_LENGTH: Final[int] = 16
#: "TASK-" plus at least 3 digits.
TASK_ID_MIN_LENGTH: Final[int] = 8
#: Git commit SHA-1, hex.
BASE_COMMIT_LENGTH: Final[int] = 40
#: SHA-256 config hash, hex.
CONFIG_HASH_LENGTH: Final[int] = 64

metadata = MetaData()


def _enum_check(column: str, values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({rendered})"


_RUN_STATUS_VALUES: Final[tuple[str, ...]] = tuple(status.name for status in RunStatus)
_TASK_STAGE_VALUES: Final[tuple[str, ...]] = tuple(stage.name for stage in TaskStage)
_EVENT_TYPE_VALUES: Final[tuple[str, ...]] = tuple(event_type.name for event_type in EventType)

schema_version_table = Table(
    "schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime, nullable=False),
    CheckConstraint("version >= 1", name="ck_schema_version_positive"),
)

runs_table = Table(
    "runs",
    metadata,
    Column("run_id", String(32), primary_key=True),
    Column("spec_id", String(128), nullable=False),
    Column("base_commit", String(40), nullable=False),
    Column("status", String(32), nullable=False),
    Column("config_hash", String(64), nullable=False),
    CheckConstraint(
        f"substr(run_id, 1, 4) = 'run-' "
        f"AND length(run_id) = {RUN_ID_LENGTH} "
        "AND substr(run_id, 5) NOT GLOB '*[^a-z0-9]*'",
        name="ck_runs_run_id_format",
    ),
    CheckConstraint(
        f"length(base_commit) = {BASE_COMMIT_LENGTH} AND base_commit NOT GLOB '*[^0-9a-f]*'",
        name="ck_runs_base_commit",
    ),
    CheckConstraint(
        f"length(config_hash) = {CONFIG_HASH_LENGTH} AND config_hash NOT GLOB '*[^0-9a-f]*'",
        name="ck_runs_config_hash",
    ),
    CheckConstraint(_enum_check("status", _RUN_STATUS_VALUES), name="ck_runs_status_enum"),
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
    CheckConstraint(
        f"substr(task_id, 1, 5) = 'TASK-' "
        f"AND length(task_id) >= {TASK_ID_MIN_LENGTH} "
        "AND substr(task_id, 6) NOT GLOB '*[^0-9]*'",
        name="ck_task_executions_task_id_format",
    ),
    CheckConstraint(
        f"length(base_commit) = {BASE_COMMIT_LENGTH} AND base_commit NOT GLOB '*[^0-9a-f]*'",
        name="ck_task_executions_base_commit",
    ),
    CheckConstraint(_enum_check("stage", _TASK_STAGE_VALUES), name="ck_task_executions_stage_enum"),
    CheckConstraint("repair_count >= 0", name="ck_task_executions_repair_count"),
    CheckConstraint("failover_count >= 0", name="ck_task_executions_failover_count"),
    CheckConstraint("version >= 1", name="ck_task_executions_version"),
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
    CheckConstraint(
        _enum_check("event_type", _EVENT_TYPE_VALUES), name="ck_events_event_type_enum"
    ),
    CheckConstraint(
        f"task_id IS NULL OR (substr(task_id, 1, 5) = 'TASK-' "
        f"AND length(task_id) >= {TASK_ID_MIN_LENGTH} "
        "AND substr(task_id, 6) NOT GLOB '*[^0-9]*')",
        name="ck_events_task_id_format",
    ),
    CheckConstraint(
        f"attempt_id IS NULL OR "
        f"(substr(attempt_id, 1, 4) = 'att-' "
        f"AND length(attempt_id) = {ATTEMPT_ID_LENGTH} "
        "AND substr(attempt_id, 5) NOT GLOB '*[^a-z0-9]*')",
        name="ck_events_attempt_id_format",
    ),
    CheckConstraint("schema_version >= 1", name="ck_events_schema_version"),
    sqlite_autoincrement=True,
)
