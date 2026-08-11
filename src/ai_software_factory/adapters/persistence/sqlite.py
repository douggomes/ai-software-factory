"""SQLite adapter for RunStore — async persistence with WAL and transactions.

Implements the RunStore protocol using SQLAlchemy async with aiosqlite.
State and events are persisted atomically in the same transaction. The
database is initialized and upgraded exclusively through the versioned SQL
migrations in ``migrations/`` (see ``migrations/README.md``); a schema
version newer than the latest known migration is rejected before any
statement runs.
"""

from __future__ import annotations

import json
import os
import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any, Final

from sqlalchemy import event as sa_event
from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from ai_software_factory.adapters.persistence.schema import (
    events_table,
    runs_table,
    schema_version_table,
    task_executions_table,
)
from ai_software_factory.core.events import DomainEvent
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import (
    CorrelationMismatchError,
    OptimisticLockError,
    RunNotFoundError,
    RunSnapshot,
    SchemaVersionError,
    TaskExecutionNotFoundError,
)

BUSY_TIMEOUT_MS: Final[int] = 5000

_DIR_MODE: Final[int] = 0o700
_FILE_MODE: Final[int] = 0o600
_DB_SIDE_FILE_SUFFIXES: Final[tuple[str, ...]] = ("", "-wal", "-shm", "-journal")


def _resolve_migrations_root() -> Traversable:
    """Locate migrations both in an installed wheel and in a source checkout."""
    packaged = files("ai_software_factory").joinpath("migrations")
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[4] / "migrations"


_MIGRATIONS_ROOT: Final[Traversable] = _resolve_migrations_root()
_MIGRATION_FILE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?P<version>\d{4})_[a-z0-9_]+\.sql$"
)


def _configure_connection(dbapi_connection: Any, connection_record: Any) -> None:
    """Apply PRAGMAs to every new pooled connection, not just the first.

    ``foreign_keys`` and ``busy_timeout`` are per-connection settings in
    SQLite; setting them once on the engine's first connection leaves later
    pooled connections without foreign key enforcement. Parameters are typed
    ``Any``: this is SQLAlchemy's DBAPI-connect hook signature, whose
    connection type is an internal driver adapter not exported for typing.
    """
    del connection_record
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        cursor.execute("PRAGMA journal_mode=WAL")
    finally:
        cursor.close()


def _begin_transaction(connection: Connection) -> None:
    """Start every SQLite transaction explicitly, including migration DDL."""
    connection.exec_driver_sql("BEGIN")


def _load_migrations() -> list[tuple[int, Traversable]]:
    migrations: list[tuple[int, Traversable]] = []
    if not _MIGRATIONS_ROOT.is_dir():
        return migrations
    for resource in _MIGRATIONS_ROOT.iterdir():
        if not resource.is_file():
            continue
        match = _MIGRATION_FILE_PATTERN.match(resource.name)
        if match is None:
            continue
        migrations.append((int(match.group("version")), resource))
    migrations.sort(key=lambda item: item[0])
    return migrations


def _statements(sql: str) -> list[str]:
    """Split a migration file into top-level statements.

    Aware of ``--`` line comments and single-quoted string literals so a
    semicolon inside a comment or a CHECK constraint's string values never
    splits a statement in the wrong place.
    """
    statements: list[str] = []
    buffer: list[str] = []
    in_string = False
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if in_string:
            buffer.append(char)
            if char == "'":
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            buffer.append(char)
            index += 1
            continue
        if sql[index : index + 2] == "--":
            newline = sql.find("\n", index)
            index = length if newline == -1 else newline + 1
            continue
        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _secure_db_files(db_path: Path) -> None:
    """Enforce 0700/0600 on the runtime dir and DB files regardless of umask."""
    os.chmod(db_path.parent, _DIR_MODE)
    for suffix in _DB_SIDE_FILE_SUFFIXES:
        candidate = db_path.with_name(db_path.name + suffix)
        if candidate.exists():
            os.chmod(candidate, _FILE_MODE)


def _require_run_correlation(run: Run, event: DomainEvent) -> None:
    if event.run_id != run.run_id:
        raise CorrelationMismatchError(
            f"event run_id {event.run_id.value!r} does not match run {run.run_id.value!r}"
        )


def _require_task_correlation(task_execution: TaskExecution, event: DomainEvent) -> None:
    if event.run_id != task_execution.run_id:
        raise CorrelationMismatchError(
            f"event run_id {event.run_id.value!r} does not match task execution run "
            f"{task_execution.run_id.value!r}"
        )
    if event.task_id != task_execution.task_id:
        raise CorrelationMismatchError(
            f"event task_id {event.task_id!r} does not match task execution task "
            f"{task_execution.task_id!r}"
        )


def _require_transition_correlation(run_id: RunId, task_id: TaskId, event: DomainEvent) -> None:
    if event.run_id != run_id:
        raise CorrelationMismatchError(
            f"event run_id {event.run_id.value!r} does not match transition run {run_id.value!r}"
        )
    if event.task_id != task_id:
        raise CorrelationMismatchError(
            f"event task_id {event.task_id!r} does not match transition task {task_id!r}"
        )


class SQLiteRunStore:
    """SQLite-backed RunStore implementation.

    Uses WAL mode, foreign keys and busy_timeout as required by the domain.
    Each operation uses a short transaction to minimize contention.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    async def create(cls, db_path: Path) -> SQLiteRunStore:
        """Create a new SQLiteRunStore with proper SQLite configuration."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(db_path.parent, _DIR_MODE)
        connection_string = f"sqlite+aiosqlite:///{db_path}"
        engine = create_async_engine(
            connection_string,
            echo=False,
            connect_args={
                "timeout": BUSY_TIMEOUT_MS / 1000,
            },
        )
        sa_event.listens_for(engine.sync_engine, "connect")(_configure_connection)
        sa_event.listens_for(engine.sync_engine, "begin")(_begin_transaction)
        store = cls(engine)
        try:
            await store._initialize_schema()
            _secure_db_files(db_path)
        except BaseException:
            await engine.dispose()
            raise
        return store

    async def _initialize_schema(self) -> None:
        """Apply pending migrations; fail closed on an unsupported version."""
        migrations = _load_migrations()
        if not migrations:
            raise SchemaVersionError(found=0, latest_supported=0)
        latest_supported = migrations[-1][0]
        async with self._engine.begin() as conn:
            current_version = await self._current_schema_version(conn)
            if current_version > latest_supported:
                raise SchemaVersionError(found=current_version, latest_supported=latest_supported)
            for version, resource in migrations:
                if version <= current_version:
                    continue
                for statement in _statements(resource.read_text(encoding="utf-8")):
                    await conn.execute(text(statement))
                applied_version = await self._current_schema_version(conn)
                if applied_version != version:
                    raise SchemaVersionError(
                        found=applied_version,
                        latest_supported=version,
                    )
                current_version = applied_version

    @staticmethod
    async def _current_schema_version(conn: AsyncConnection) -> int:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
        )
        if result.first() is None:
            return 0
        row = (await conn.execute(select(func.max(schema_version_table.c.version)))).first()
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    async def create_run(self, run: Run, event: DomainEvent) -> None:
        """Persist a new run and its creation event atomically."""
        _require_run_correlation(run, event)
        async with self._engine.begin() as conn:
            await conn.execute(
                runs_table.insert().values(
                    run_id=run.run_id.value,
                    spec_id=run.spec_id,
                    base_commit=run.base_commit,
                    status=run.status.name,
                    config_hash=run.config_hash,
                )
            )
            await conn.execute(
                events_table.insert().values(
                    event_type=event.event_type.name,
                    timestamp=event.timestamp,
                    run_id=event.run_id.value,
                    task_id=event.task_id.value if event.task_id else None,
                    attempt_id=event.attempt_id.value if event.attempt_id else None,
                    payload=json.dumps(event.payload) if event.payload else None,
                    schema_version=event.schema_version,
                )
            )

    async def create_task_execution(
        self, task_execution: TaskExecution, event: DomainEvent
    ) -> None:
        """Persist a new task execution and its event atomically."""
        _require_task_correlation(task_execution, event)
        async with self._engine.begin() as conn:
            await conn.execute(
                task_executions_table.insert().values(
                    run_id=task_execution.run_id.value,
                    task_id=task_execution.task_id.value,
                    base_commit=task_execution.base_commit,
                    worktree_path=task_execution.worktree_path,
                    stage=task_execution.stage.name,
                    repair_count=task_execution.repair_count,
                    failover_count=task_execution.failover_count,
                    version=1,
                )
            )
            await conn.execute(
                events_table.insert().values(
                    event_type=event.event_type.name,
                    timestamp=event.timestamp,
                    run_id=event.run_id.value,
                    task_id=event.task_id.value if event.task_id else None,
                    attempt_id=event.attempt_id.value if event.attempt_id else None,
                    payload=json.dumps(event.payload) if event.payload else None,
                    schema_version=event.schema_version,
                )
            )

    async def transition(self, run_id: RunId, task_id: TaskId, transition: Transition) -> None:
        """Apply a state transition with optimistic version check.

        Identity is the composite (run_id, task_id) so that two runs sharing
        the same TaskId can never contaminate each other's state or events.
        """
        _require_transition_correlation(run_id, task_id, transition.event)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                select(
                    task_executions_table.c.stage,
                    task_executions_table.c.version,
                ).where(
                    task_executions_table.c.run_id == run_id.value,
                    task_executions_table.c.task_id == task_id.value,
                )
            )
            row = result.first()
            if row is None:
                raise TaskExecutionNotFoundError(run_id, task_id)
            current_stage = row.stage
            current_version = row.version
            if current_stage != transition.from_stage.name:
                raise OptimisticLockError(task_id, transition.from_stage.name, current_stage)
            update_result = await conn.execute(
                update(task_executions_table)
                .where(
                    task_executions_table.c.run_id == run_id.value,
                    task_executions_table.c.task_id == task_id.value,
                    task_executions_table.c.version == current_version,
                )
                .values(
                    stage=transition.to_stage.name,
                    version=current_version + 1,
                )
            )
            if update_result.rowcount != 1:
                raise OptimisticLockError(task_id, transition.from_stage.name, current_stage)
            await conn.execute(
                events_table.insert().values(
                    event_type=transition.event.event_type.name,
                    timestamp=transition.event.timestamp,
                    run_id=transition.event.run_id.value,
                    task_id=transition.event.task_id.value if transition.event.task_id else None,
                    attempt_id=transition.event.attempt_id.value
                    if transition.event.attempt_id
                    else None,
                    payload=json.dumps(transition.event.payload)
                    if transition.event.payload
                    else None,
                    schema_version=transition.event.schema_version,
                )
            )

    async def load_run(self, run_id: RunId) -> RunSnapshot:
        """Reconstruct run state from the persistence layer."""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(runs_table).where(runs_table.c.run_id == run_id.value)
            )
            row = result.first()
            if row is None:
                raise RunNotFoundError(run_id)
            run = Run(
                run_id=RunId(row.run_id),
                spec_id=row.spec_id,
                base_commit=row.base_commit,
                status=RunStatus[row.status],
                config_hash=row.config_hash,
            )
            te_result = await conn.execute(
                select(task_executions_table).where(task_executions_table.c.run_id == run_id.value)
            )
            task_executions = tuple(
                TaskExecution(
                    run_id=RunId(te.run_id),
                    task_id=TaskId(te.task_id),
                    base_commit=te.base_commit,
                    worktree_path=te.worktree_path,
                    stage=TaskStage[te.stage],
                    repair_count=te.repair_count,
                    failover_count=te.failover_count,
                )
                for te in te_result.fetchall()
            )
            event_result = await conn.execute(
                select(events_table).where(events_table.c.run_id == run_id.value)
            )
            event_count = len(event_result.fetchall())
            return RunSnapshot(run=run, task_executions=task_executions, event_count=event_count)

    async def load_task_execution(self, run_id: RunId, task_id: TaskId) -> TaskExecution:
        """Load a single task execution by run and task IDs."""
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(task_executions_table).where(
                    task_executions_table.c.run_id == run_id.value,
                    task_executions_table.c.task_id == task_id.value,
                )
            )
            row = result.first()
            if row is None:
                raise TaskExecutionNotFoundError(run_id, task_id)
            return TaskExecution(
                run_id=RunId(row.run_id),
                task_id=TaskId(row.task_id),
                base_commit=row.base_commit,
                worktree_path=row.worktree_path,
                stage=TaskStage[row.stage],
                repair_count=row.repair_count,
                failover_count=row.failover_count,
            )

    async def close(self) -> None:
        """Release the engine and connections."""
        await self._engine.dispose()
