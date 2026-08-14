"""Shared structural contract for every AgentWorker implementation."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.core.agent_events import AgentEvent, AgentEventType
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.core.workspace_models import Workspace, WorkspaceRequest
from ai_software_factory.ports.workers import (
    AgentExecutionRequest,
    AgentWorker,
    WorkerCapability,
    WorkerProbe,
)


def _workspace(tmp_path: Path) -> Workspace:
    """Create a minimal workspace for testing."""
    return Workspace(
        repository=tmp_path,
        factory_home=tmp_path / "factory-home",
        worktree_path=tmp_path / "worktree",
        lock_path=tmp_path / "lock",
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-999"),
        base_commit="a" * 40,
        branch_name="aif/test",
    )


def _request(workspace: Workspace) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-999"),
        attempt_id=AttemptId("att-111111111111"),
        workspace=workspace,
        spec_text="test spec",
        allowed_paths=("src/**", "tests/**"),
    )


async def _collect_events(worker: AgentWorker, request: AgentExecutionRequest) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    async for event in worker.execute(request):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_worker_produces_typed_events(tmp_path: Path) -> None:
    """Every worker must produce a stream of typed AgentEvents."""
    from ai_software_factory.adapters.agents.fake import create_fake_worker

    workspace = _workspace(tmp_path)
    workspace.worktree_path.mkdir(parents=True, exist_ok=True)
    request = _request(workspace)

    worker = create_fake_worker("fake-success")
    events = await _collect_events(worker, request)

    assert all(isinstance(e, AgentEvent) for e in events)
    assert all(e.schema_version == 1 for e in events)
    assert all(e.run_id.value == "run-abc123def456" for e in events)
    assert all(e.task_id.value == "TASK-999" for e in events)
    assert all(e.attempt_id.value == "att-111111111111" for e in events)


@pytest.mark.asyncio
async def test_worker_terminates_with_terminal_event(tmp_path: Path) -> None:
    """Worker stream must terminate with a terminal event."""
    from ai_software_factory.adapters.agents.fake import create_fake_worker

    workspace = _workspace(tmp_path)
    workspace.worktree_path.mkdir(parents=True, exist_ok=True)
    request = _request(workspace)

    worker = create_fake_worker("fake-success")
    events = await _collect_events(worker, request)

    terminal_events = [
        e for e in events
        if e.event_type in (
            AgentEventType.ATTEMPT_SUCCEEDED,
            AgentEventType.ATTEMPT_FAILED,
            AgentEventType.ATTEMPT_CANCELLED,
        )
    ]
    assert len(terminal_events) == 1
    assert terminal_events[0] == events[-1]


@pytest.mark.asyncio
async def test_worker_respects_allowed_paths(tmp_path: Path) -> None:
    """Worker must not apply edits outside allowed_paths."""
    from ai_software_factory.adapters.agents.fake import create_fake_worker

    workspace = _workspace(tmp_path)
    workspace.worktree_path.mkdir(parents=True, exist_ok=True)
    # Allowed paths only include src/**, not etc/**
    request = AgentExecutionRequest(
        run_id=RunId("run-abc123def456"),
        task_id=TaskId("TASK-999"),
        attempt_id=AttemptId("att-111111111111"),
        workspace=workspace,
        spec_text="test spec",
        allowed_paths=("src/**",),
    )

    worker = create_fake_worker("fake-prompt-injection")
    events = await _collect_events(worker, request)

    # Should end with failure, not success
    terminal = events[-1]
    assert terminal.event_type == AgentEventType.ATTEMPT_FAILED


@pytest.mark.asyncio
async def test_worker_probe_returns_capability() -> None:
    """Worker probe must return a WorkerCapability."""
    from ai_software_factory.adapters.agents.fake import FakeWorkerProbe

    probe = FakeWorkerProbe()
    capability = await probe.probe()

    assert isinstance(capability, WorkerCapability)
    assert capability.worker_id == "fake"
    assert capability.version == "1.0.0"
    assert "fake-success" in capability.capabilities
    assert "fake-failure" in capability.capabilities
    assert "fake-error" in capability.capabilities
    assert "fake-prompt-injection" in capability.capabilities


@pytest.mark.asyncio
async def test_worker_produces_edit_events(tmp_path: Path) -> None:
    """Successful worker must produce EDIT_PROPOSED and EDIT_APPLIED events."""
    from ai_software_factory.adapters.agents.fake import create_fake_worker

    workspace = _workspace(tmp_path)
    workspace.worktree_path.mkdir(parents=True, exist_ok=True)
    request = _request(workspace)

    worker = create_fake_worker("fake-success")
    events = await _collect_events(worker, request)

    proposed = [e for e in events if e.event_type == AgentEventType.EDIT_PROPOSED]
    applied = [e for e in events if e.event_type == AgentEventType.EDIT_APPLIED]

    assert len(proposed) >= 1
    assert len(applied) >= 1
    for event in proposed + applied:
        assert event.payload is not None
        assert "file_path" in event.payload


__all__ = [
    "test_worker_produces_typed_events",
    "test_worker_terminates_with_terminal_event",
    "test_worker_respects_allowed_paths",
    "test_worker_probe_returns_capability",
    "test_worker_produces_edit_events",
]