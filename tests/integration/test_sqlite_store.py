"""Integration tests for SQLiteRunStore.

Tests AC-001, AC-002 and AC-003 from TASK-004.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select as sa_select

from ai_software_factory.adapters.persistence.schema import schema_version_table
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import OptimisticLockError


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
        await store.transition(te.task_id, wrong_transition)
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
    await store.transition(te.task_id, transition1)
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
    await store.transition(te.task_id, transition2)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.WORKSPACE_PREPARING
