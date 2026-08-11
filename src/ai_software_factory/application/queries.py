"""Read-only queries for run status and deterministic event export.

Status and NDJSON exports are pure projections of the persistence ledger.
They never mutate state and never treat an on-disk NDJSON file as authority.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ai_software_factory.core.events import DomainEvent
from ai_software_factory.core.ids import RunId
from ai_software_factory.core.models import Run, TaskExecution
from ai_software_factory.ports.persistence import RunNotFoundError, RunSnapshot, RunStore


@runtime_checkable
class EventLogReader(Protocol):
    """Port for ordered event reads used by NDJSON export."""

    async def list_events(self, run_id: RunId) -> tuple[DomainEvent, ...]: ...


@dataclass(frozen=True, slots=True)
class TaskStatusView:
    task_id: str
    stage: str
    base_commit: str
    worktree_path: str
    repair_count: int
    failover_count: int


@dataclass(frozen=True, slots=True)
class RunStatusView:
    run_id: str
    spec_id: str
    base_commit: str
    status: str
    config_hash: str
    event_count: int
    tasks: tuple[TaskStatusView, ...]


def _task_view(task: TaskExecution) -> TaskStatusView:
    return TaskStatusView(
        task_id=task.task_id.value,
        stage=task.stage.name,
        base_commit=task.base_commit,
        worktree_path=task.worktree_path,
        repair_count=task.repair_count,
        failover_count=task.failover_count,
    )


def _run_view(snapshot: RunSnapshot) -> RunStatusView:
    ordered_tasks = tuple(
        sorted((_task_view(task) for task in snapshot.task_executions), key=lambda t: t.task_id)
    )
    run: Run = snapshot.run
    return RunStatusView(
        run_id=run.run_id.value,
        spec_id=run.spec_id,
        base_commit=run.base_commit,
        status=run.status.name,
        config_hash=run.config_hash,
        event_count=snapshot.event_count,
        tasks=ordered_tasks,
    )


def run_status_to_json_dict(view: RunStatusView) -> dict[str, object]:
    """Canonical JSON-ready mapping for ``aif status --json``."""
    return {
        "base_commit": view.base_commit,
        "config_hash": view.config_hash,
        "event_count": view.event_count,
        "run_id": view.run_id,
        "spec_id": view.spec_id,
        "status": view.status,
        "tasks": [
            {
                "base_commit": task.base_commit,
                "failover_count": task.failover_count,
                "repair_count": task.repair_count,
                "stage": task.stage,
                "task_id": task.task_id,
                "worktree_path": task.worktree_path,
            }
            for task in view.tasks
        ],
    }


def format_run_status_json(view: RunStatusView) -> str:
    """Serialize status with stable key order and formatting."""
    return (
        json.dumps(
            run_status_to_json_dict(view),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )


def _timestamp_to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat(timespec="microseconds") + "+00:00"
    return value.isoformat(timespec="microseconds")


def event_to_json_dict(event: DomainEvent) -> dict[str, object]:
    """Canonical mapping for one NDJSON event line."""
    return {
        "attempt_id": event.attempt_id.value if event.attempt_id is not None else None,
        "event_type": event.event_type.name,
        "payload": event.payload,
        "run_id": event.run_id.value,
        "schema_version": event.schema_version,
        "task_id": event.task_id.value if event.task_id is not None else None,
        "timestamp": _timestamp_to_iso(event.timestamp),
    }


def format_events_ndjson(events: Sequence[DomainEvent]) -> str:
    """Deterministic NDJSON export reconstructed from ledger events."""
    lines = [
        json.dumps(
            event_to_json_dict(event),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for event in events
    ]
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


class RunStatusQuery:
    """Load a run snapshot and project it to a status view."""

    def __init__(self, store: RunStore) -> None:
        self._store = store

    async def execute(self, run_id: RunId) -> RunStatusView:
        snapshot = await self._store.load_run(run_id)
        return _run_view(snapshot)


class RunEventsQuery:
    """Load ordered domain events for NDJSON export."""

    def __init__(self, store: RunStore, events: EventLogReader) -> None:
        self._store = store
        self._events = events

    async def execute(self, run_id: RunId) -> tuple[DomainEvent, ...]:
        await self._store.load_run(run_id)
        return await self._events.list_events(run_id)


__all__ = [
    "EventLogReader",
    "RunEventsQuery",
    "RunNotFoundError",
    "RunStatusQuery",
    "RunStatusView",
    "TaskStatusView",
    "event_to_json_dict",
    "format_events_ndjson",
    "format_run_status_json",
    "run_status_to_json_dict",
]
