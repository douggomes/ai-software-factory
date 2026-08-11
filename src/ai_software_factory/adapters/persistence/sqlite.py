"""SQLite adapter for RunStore — async persistence with WAL and transactions.

Implements the RunStore protocol using SQLAlchemy async with aiosqlite.
State and events are persisted atomically in the same transaction.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ai_software_factory.adapters.persistence.schema import (
    SCHEMA_VERSION,
    events_table,
    metadata,
    runs_table,
    schema_version_table,
    task_executions_table,
)
from ai_software_factory.core.events import DomainEvent
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import (
    OptimisticLockError,
    RunNotFoundError,
    RunSnapshot,
    TaskExecutionNotFoundError,
)

BUSY_TIMEOUT_MS: Final[int] = 5000


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
        connection_string = f"sqlite+aiosqlite:///{db_path}"
        engine = create_async_engine(
            connection_string,
            echo=False,
            connect_args={
                "timeout": BUSY_TIMEOUT_MS / 1000,
            },
        )
        store = cls(engine)
        await store._initialize_schema()
        return store

    async def _initialize_schema(self) -> None:
        """Create tables if they don't exist and record schema version."""
        async with self._engine.begin() as conn:
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA foreign_keys=ON"))
            await conn.execute(text(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}"))
            await conn.run_sync(metadata.create_all)
            result = await conn.execute(select(schema_version_table.c.version))
            row = result.first()
            if row is None:
                await conn.execute(
                    schema_version_table.insert().values(
                        version=SCHEMA_VERSION, applied_at=datetime.now(UTC)
                    )
                )

    async def create_run(self, run: Run, event: DomainEvent) -> None:
        """Persist a new run and its creation event atomically."""
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

    async def transition(self, task_id: TaskId, transition: Transition) -> None:
        """Apply a state transition with optimistic version check."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                select(
                    task_executions_table.c.run_id,
                    task_executions_table.c.stage,
                    task_executions_table.c.version,
                ).where(task_executions_table.c.task_id == task_id.value)
            )
            row = result.first()
            if row is None:
                raise TaskExecutionNotFoundError(RunId("run-000000000000"), task_id)
            current_stage = row.stage
            current_version = row.version
            if current_stage != transition.from_stage.name:
                raise OptimisticLockError(task_id, transition.from_stage.name, current_stage)
            await conn.execute(
                update(task_executions_table)
                .where(
                    task_executions_table.c.task_id == task_id.value,
                    task_executions_table.c.version == current_version,
                )
                .values(
                    stage=transition.to_stage.name,
                    version=current_version + 1,
                )
            )
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
