"""Integration tests for SQLiteRunStore.

Tests AC-001, AC-002 and AC-003 from TASK-004.
"""

from __future__ import annotations

import os
import stat
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, text
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ai_software_factory.adapters.persistence import sqlite as sqlite_module
from ai_software_factory.adapters.persistence.schema import runs_table, schema_version_table
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import OptimisticLockError, SchemaVersionError


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[SQLiteRunStore]:
    db_path = tmp_path / "test.db"
    store = await SQLiteRunStore.create(db_path)
    try:
        yield store
    finally:
        await store.close()


def _make_run(run_id: str = "run-abc123def456") -> Run:
    return Run(
        run_id=RunId(run_id),
        spec_id="spec-001",
        base_commit="a" * 40,
        status=RunStatus.QUEUED,
        config_hash="b" * 64,
    )


def _make_event(run_id: str = "run-abc123def456") -> DomainEvent:
    return DomainEvent(
        event_type=EventType.RUN_STARTED,
        timestamp=datetime.now(UTC),
        run_id=RunId(run_id),
    )


def _make_task_execution(
    run_id: str = "run-abc123def456", task_id: str = "TASK-001"
) -> TaskExecution:
    return TaskExecution(
        run_id=RunId(run_id),
        task_id=TaskId(task_id),
        base_commit="a" * 40,
        worktree_path="/worktrees/test",
        stage=TaskStage.QUEUED,
    )


async def test_persists_across_reopen(tmp_path: Path) -> None:
    """AC-001: Run created can be loaded after closing and reopening the store."""
    db_path = tmp_path / "test.db"
    store1 = await SQLiteRunStore.create(db_path)
    run = _make_run()
    event = _make_event()
    await store1.create_run(run, event)
    await store1.close()
    store2 = await SQLiteRunStore.create(db_path)
    snapshot = await store2.load_run(run.run_id)
    assert snapshot.run.run_id == run.run_id
    assert snapshot.run.spec_id == run.spec_id
    assert snapshot.run.base_commit == run.base_commit
    assert snapshot.run.status == run.status
    assert snapshot.run.config_hash == run.config_hash
    assert snapshot.event_count == 1
    await store2.close()


async def test_event_failure_rolls_back_transition(store: SQLiteRunStore) -> None:
    """AC-002: Event write failure rolls back the entire transition."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te = _make_task_execution()
    te_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    await store.create_task_execution(te, te_event)
    snapshot_before = await store.load_run(run.run_id)
    event_count_before = snapshot_before.event_count
    transition_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    wrong_transition = Transition(
        from_stage=TaskStage.IMPLEMENTING,
        to_stage=TaskStage.DETERMINISTIC_VALIDATION,
        event=transition_event,
    )
    with pytest.raises(OptimisticLockError):
        await store.transition(run.run_id, te.task_id, wrong_transition)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.QUEUED
    snapshot_after = await store.load_run(run.run_id)
    assert snapshot_after.event_count == event_count_before


async def test_concurrent_sessions(tmp_path: Path) -> None:
    """AC-003: Concurrent sessions can read and write without corruption."""
    db_path = tmp_path / "test.db"
    store1 = await SQLiteRunStore.create(db_path)
    store2 = await SQLiteRunStore.create(db_path)
    run1 = _make_run("run-aaa111bbb222")
    event1 = _make_event("run-aaa111bbb222")
    run2 = _make_run("run-ccc333ddd444")
    event2 = _make_event("run-ccc333ddd444")
    await store1.create_run(run1, event1)
    await store2.create_run(run2, event2)
    snapshot1 = await store2.load_run(run1.run_id)
    snapshot2 = await store1.load_run(run2.run_id)
    assert snapshot1.run.run_id == run1.run_id
    assert snapshot2.run.run_id == run2.run_id
    await store1.close()
    await store2.close()


async def test_schema_version_recorded(store: SQLiteRunStore) -> None:
    """Verify schema version is recorded during initialization."""
    async with store._engine.connect() as conn:  # pyright: ignore[reportPrivateUsage]
        result = await conn.execute(sa_select(schema_version_table.c.version))
        row = result.first()
        assert row is not None
        assert row.version == 1


async def test_multiple_task_executions(store: SQLiteRunStore) -> None:
    """Verify multiple task executions can be created for the same run."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te1 = _make_task_execution(task_id="TASK-001")
    te2 = _make_task_execution(task_id="TASK-002")
    te1_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te1.task_id,
    )
    te2_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te2.task_id,
    )
    await store.create_task_execution(te1, te1_event)
    await store.create_task_execution(te2, te2_event)
    snapshot = await store.load_run(run.run_id)
    expected_task_count = 2
    assert len(snapshot.task_executions) == expected_task_count
    task_ids = {te.task_id.value for te in snapshot.task_executions}
    assert task_ids == {"TASK-001", "TASK-002"}


async def test_transition_sequence(store: SQLiteRunStore) -> None:
    """Verify a sequence of transitions works correctly."""
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    te = _make_task_execution()
    te_event = DomainEvent(
        event_type=EventType.TASK_QUEUED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    await store.create_task_execution(te, te_event)
    transition1_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition1 = Transition(
        from_stage=TaskStage.QUEUED,
        to_stage=TaskStage.PREFLIGHT,
        event=transition1_event,
    )
    await store.transition(run.run_id, te.task_id, transition1)
    transition2_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition2 = Transition(
        from_stage=TaskStage.PREFLIGHT,
        to_stage=TaskStage.WORKSPACE_PREPARING,
        event=transition2_event,
    )
    await store.transition(run.run_id, te.task_id, transition2)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.WORKSPACE_PREPARING


async def test_foreign_keys_enabled_on_every_pooled_connection(store: SQLiteRunStore) -> None:
    """QA-004-002 regression: every pooled connection enforces foreign keys, not just the first."""
    async with store._engine.connect() as conn1:  # pyright: ignore[reportPrivateUsage]
        first = (await conn1.execute(text("PRAGMA foreign_keys"))).scalar_one()
        async with store._engine.connect() as conn2:  # pyright: ignore[reportPrivateUsage]
            second = (await conn2.execute(text("PRAGMA foreign_keys"))).scalar_one()
    assert first == 1
    assert second == 1


async def test_runtime_directory_and_database_have_restrictive_permissions(
    tmp_path: Path,
) -> None:
    """QA-004-004 regression: runtime dir is 0700 and DB file is 0600 regardless of umask."""
    expected_dir_mode = 0o700
    expected_db_mode = 0o600
    permissive_umask = 0o022
    original_umask = os.umask(permissive_umask)
    try:
        db_path = tmp_path / "runtime" / "test.db"
        store = await SQLiteRunStore.create(db_path)
        try:
            dir_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
            db_mode = stat.S_IMODE(db_path.stat().st_mode)
            assert dir_mode == expected_dir_mode
            assert db_mode == expected_db_mode
        finally:
            await store.close()
    finally:
        os.umask(original_umask)


async def test_future_schema_version_is_rejected(tmp_path: Path) -> None:
    """QA-004-005 regression: a schema version newer than supported fails closed."""
    db_path = tmp_path / "future.db"
    seed_store = await SQLiteRunStore.create(db_path)
    await seed_store.close()

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            await conn.execute(
                schema_version_table.insert().values(version=999, applied_at=datetime.now(UTC))
            )
    finally:
        await engine.dispose()

    with pytest.raises(SchemaVersionError):
        await SQLiteRunStore.create(db_path)


async def test_database_rejects_base_commit_of_wrong_length(store: SQLiteRunStore) -> None:
    """QA-004-006 regression: DB CHECK constraints back domain validation, not just create_all."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-zzzzzzzzzzzz",
                    spec_id="spec-1",
                    base_commit="short",
                    status="QUEUED",
                    config_hash="b" * 64,
                )
            )


async def test_database_rejects_unknown_status_enum_value(store: SQLiteRunStore) -> None:
    """QA-004-006 regression: status is constrained to the domain's RunStatus enum values."""
    with pytest.raises(IntegrityError):
        async with store._engine.begin() as conn:  # pyright: ignore[reportPrivateUsage]
            await conn.execute(
                insert(runs_table).values(
                    run_id="run-yyyyyyyyyyyy",
                    spec_id="spec-1",
                    base_commit="a" * 40,
                    status="NOT_A_REAL_STATUS",
                    config_hash="b" * 64,
                )
            )


def test_load_migrations_skips_non_matching_filenames(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "0001_initial.sql").write_text("CREATE TABLE t (id INTEGER);", encoding="utf-8")
    (tmp_path / "not_a_migration.sql").write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(sqlite_module, "_MIGRATIONS_ROOT", tmp_path)

    migrations = sqlite_module._load_migrations()  # pyright: ignore[reportPrivateUsage]

    assert [version for version, _ in migrations] == [1]


async def test_missing_migrations_raise_schema_version_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-004-005: with no migration to apply, the store fails closed instead of no-op."""
    empty_migrations_dir = tmp_path / "empty-migrations"
    empty_migrations_dir.mkdir()
    monkeypatch.setattr(sqlite_module, "_MIGRATIONS_ROOT", empty_migrations_dir)

    with pytest.raises(SchemaVersionError):
        await SQLiteRunStore.create(tmp_path / "orphan.db")


def test_statements_skips_empty_segments_between_semicolons() -> None:
    sql = "SELECT 1;;  -- trailing comment, no further statement\n"

    assert sqlite_module._statements(sql) == ["SELECT 1"]  # pyright: ignore[reportPrivateUsage]


def test_statements_includes_final_statement_without_trailing_semicolon() -> None:
    sql = "SELECT 1"

    assert sqlite_module._statements(sql) == ["SELECT 1"]  # pyright: ignore[reportPrivateUsage]
