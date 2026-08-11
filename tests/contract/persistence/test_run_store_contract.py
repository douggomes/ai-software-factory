"""Contract tests for RunStore protocol implementations.

These tests verify that any RunStore implementation correctly handles
the core persistence operations defined by the protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import Run, RunStatus, TaskExecution, TaskStage
from ai_software_factory.core.state_machine import Transition
from ai_software_factory.ports.persistence import (
    OptimisticLockError,
    RunNotFoundError,
    RunStore,
    TaskExecutionNotFoundError,
)


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


async def test_create_run_persists_run(store: RunStore) -> None:
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    snapshot = await store.load_run(run.run_id)
    assert snapshot.run.run_id == run.run_id
    assert snapshot.run.spec_id == run.spec_id
    assert snapshot.run.base_commit == run.base_commit
    assert snapshot.run.status == run.status
    assert snapshot.run.config_hash == run.config_hash


async def test_create_run_records_event(store: RunStore) -> None:
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    snapshot = await store.load_run(run.run_id)
    assert snapshot.event_count == 1


async def test_load_run_not_found_raises(store: RunStore) -> None:
    with pytest.raises(RunNotFoundError):
        await store.load_run(RunId("run-zzz999zzz999"))


async def test_create_task_execution_persists(store: RunStore) -> None:
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
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.task_id == te.task_id
    assert loaded.stage == te.stage
    assert loaded.worktree_path == te.worktree_path


async def test_transition_updates_stage(store: RunStore) -> None:
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
    transition_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition = Transition(
        from_stage=TaskStage.QUEUED,
        to_stage=TaskStage.PREFLIGHT,
        event=transition_event,
    )
    await store.transition(te.task_id, transition)
    loaded = await store.load_task_execution(run.run_id, te.task_id)
    assert loaded.stage == TaskStage.PREFLIGHT


async def test_transition_records_event(store: RunStore) -> None:
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
    transition_event = DomainEvent(
        event_type=EventType.TASK_STAGE_CHANGED,
        timestamp=datetime.now(UTC),
        run_id=run.run_id,
        task_id=te.task_id,
    )
    transition = Transition(
        from_stage=TaskStage.QUEUED,
        to_stage=TaskStage.PREFLIGHT,
        event=transition_event,
    )
    await store.transition(te.task_id, transition)
    snapshot = await store.load_run(run.run_id)
    expected_event_count = 3
    assert snapshot.event_count == expected_event_count


async def test_transition_optimistic_lock_conflict(store: RunStore) -> None:
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


async def test_load_task_execution_not_found_raises(store: RunStore) -> None:
    run = _make_run()
    event = _make_event()
    await store.create_run(run, event)
    with pytest.raises(TaskExecutionNotFoundError):
        await store.load_task_execution(run.run_id, TaskId("TASK-999"))
