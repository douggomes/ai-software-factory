"""Fake agent worker — deterministic, offline implementation for testing.

This adapter implements the AgentWorker port with controlled behavior:
- fake-success: applies a predefined edit and succeeds
- fake-failure: applies a predefined edit that fails gates
- fake-error: raises an unexpected error during execution
- fake-prompt-injection: attempts to bypass policy (must be rejected)
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from ai_software_factory.core.agent_events import (
    AgentEvent,
    AgentEventType,
    EditApplied,
    EditProposed,
    EditRejected,
    ToolFailed,
    ToolInvoked,
    ToolSucceeded,
)
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.core.workspace_models import Workspace
from ai_software_factory.ports.workers import (
    AgentExecutionRequest,
    AgentWorker,
    WorkerCapability,
    WorkerError,
    WorkerExecutionError,
    WorkerPolicyError,
    WorkerProbe,
)

_FAKE_WORKER_VERSION: Final[str] = "1.0.0"
_SUPPORTED_MODES: Final[frozenset[str]] = frozenset(
    {"fake-success", "fake-failure", "fake-error", "fake-prompt-injection"}
)


@dataclass(frozen=True, slots=True)
class FakeWorkerMode:
    """Mode determines the fake worker's behavior."""

    value: str

    def __post_init__(self) -> None:
        if self.value not in _SUPPORTED_MODES:
            raise WorkerError(f"unsupported fake worker mode: {self.value!r}")


def _event(
    event_type: AgentEventType,
    run_id: RunId,
    task_id: TaskId,
    attempt_id: AttemptId,
    payload: dict[str, object] | None = None,
) -> AgentEvent:
    return AgentEvent(
        event_type=event_type,
        timestamp=datetime.utcnow(),
        run_id=run_id,
        task_id=task_id,
        attempt_id=attempt_id,
        payload=payload,
    )


def _apply_edit(workspace: Workspace, file_path: str, content: str) -> None:
    """Apply an edit to the workspace worktree."""
    target = workspace.worktree_path / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _compute_diff(original: str | None, new: str) -> str:
    """Compute a simple diff representation."""
    if original is None:
        return f"--- /dev/null\n+++ b/{new}\n@@ -0,0 +1 @@\n+{new}"
    return f"--- a/{original}\n+++ b/{new}\n@@ -1 +1 @@\n-{original}\n+{new}"


class FakeAgentWorker:
    """Deterministic fake worker for offline pipeline testing."""

    def __init__(self, mode: FakeWorkerMode) -> None:
        self._mode = mode

    @property
    def worker_id(self) -> str:
        return self._mode.value

    async def execute(self, request: AgentExecutionRequest) -> AsyncIterator[AgentEvent]:
        run_id = request.run_id
        task_id = request.task_id
        attempt_id = request.attempt_id
        workspace = request.workspace
        allowed_paths = request.allowed_paths

        yield _event(AgentEventType.ATTEMPT_STARTED, run_id, task_id, attempt_id)

        if self._mode.value == "fake-error":
            yield _event(
                AgentEventType.ATTEMPT_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"error": "simulated unexpected worker error"},
            )
            return

        if self._mode.value == "fake-prompt-injection":
            async for event in self._run_prompt_injection(
                run_id, task_id, attempt_id, workspace, allowed_paths
            ):
                yield event
            return

        if self._mode.value == "fake-failure":
            async for event in self._run_failure(run_id, task_id, attempt_id, workspace, allowed_paths):
                yield event
            return

        if self._mode.value == "fake-success":
            async for event in self._run_success(run_id, task_id, attempt_id, workspace, allowed_paths):
                yield event
            return

    async def _run_success(
        self,
        run_id: RunId,
        task_id: TaskId,
        attempt_id: AttemptId,
        workspace: Workspace,
        allowed_paths: tuple[str, ...],
    ) -> AsyncIterator[AgentEvent]:
        """Apply a valid edit that should pass gates."""
        file_path = "src/example.py"
        if not any(Path(file_path).match(pattern) for pattern in allowed_paths):
            yield _event(
                AgentEventType.EDIT_REJECTED,
                run_id,
                task_id,
                attempt_id,
                {"file_path": file_path, "reason": "outside allowed scope"},
            )
            yield _event(
                AgentEventType.ATTEMPT_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"error": "edit outside allowed scope"},
            )
            return

        yield _event(
            AgentEventType.EDIT_PROPOSED,
            run_id,
            task_id,
            attempt_id,
            {
                "file_path": file_path,
                "original_content": None,
                "proposed_content": "print('hello from fake-success')\n",
                "reason": "implement example feature",
            },
        )

        yield _event(
            AgentEventType.TOOL_INVOKED,
            run_id,
            task_id,
            attempt_id,
            {"tool_name": "write_file", "arguments": {"path": file_path, "content": "print('hello from fake-success')\n"}},
        )

        _apply_edit(workspace, file_path, "print('hello from fake-success')\n")

        yield _event(
            AgentEventType.TOOL_SUCCEEDED,
            run_id,
            task_id,
            attempt_id,
            {"tool_name": "write_file", "result_summary": f"wrote {file_path}"},
        )

        yield _event(
            AgentEventType.EDIT_APPLIED,
            run_id,
            task_id,
            attempt_id,
            {"file_path": file_path, "diff": _compute_diff(None, "print('hello from fake-success')\n")},
        )

        yield _event(
            AgentEventType.ATTEMPT_SUCCEEDED,
            run_id,
            task_id,
            attempt_id,
            {"message": "fake-success completed edits"},
        )

    async def _run_failure(
        self,
        run_id: RunId,
        task_id: TaskId,
        attempt_id: AttemptId,
        workspace: Workspace,
        allowed_paths: tuple[str, ...],
    ) -> AsyncIterator[AgentEvent]:
        """Apply an edit that will fail validation gates (e.g., introduces secret)."""
        file_path = "src/bad_example.py"
        if not any(Path(file_path).match(pattern) for pattern in allowed_paths):
            yield _event(
                AgentEventType.EDIT_REJECTED,
                run_id,
                task_id,
                attempt_id,
                {"file_path": file_path, "reason": "outside allowed scope"},
            )
            yield _event(
                AgentEventType.ATTEMPT_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"error": "edit outside allowed scope"},
            )
            return

        # This content will trigger the secret gate
        bad_content = 'api_key = "sk-1234567890abcdef"\n'

        yield _event(
            AgentEventType.EDIT_PROPOSED,
            run_id,
            task_id,
            attempt_id,
            {
                "file_path": file_path,
                "original_content": None,
                "proposed_content": bad_content,
                "reason": "add api key (will fail secret gate)",
            },
        )

        yield _event(
            AgentEventType.TOOL_INVOKED,
            run_id,
            task_id,
            attempt_id,
            {"tool_name": "write_file", "arguments": {"path": file_path, "content": bad_content}},
        )

        _apply_edit(workspace, file_path, bad_content)

        yield _event(
            AgentEventType.TOOL_SUCCEEDED,
            run_id,
            task_id,
            attempt_id,
            {"tool_name": "write_file", "result_summary": f"wrote {file_path}"},
        )

        yield _event(
            AgentEventType.EDIT_APPLIED,
            run_id,
            task_id,
            attempt_id,
            {"file_path": file_path, "diff": _compute_diff(None, bad_content)},
        )

        yield _event(
            AgentEventType.ATTEMPT_SUCCEEDED,
            run_id,
            task_id,
            attempt_id,
            {"message": "fake-failure completed edits (gates should fail)"},
        )

    async def _run_prompt_injection(
        self,
        run_id: RunId,
        task_id: TaskId,
        attempt_id: AttemptId,
        workspace: Workspace,
        allowed_paths: tuple[str, ...],
    ) -> AsyncIterator[AgentEvent]:
        """Attempt to write outside allowed paths (simulating prompt injection).

        The orchestrator must reject this before it reaches the filesystem.
        """
        # Try to write to a path outside allowed scope
        file_path = "../../../etc/passwd"

        # Check if path is allowed - this simulates the policy check
        if not any(Path(file_path).match(pattern) for pattern in allowed_paths):
            yield _event(
                AgentEventType.EDIT_REJECTED,
                run_id,
                task_id,
                attempt_id,
                {"file_path": file_path, "reason": "outside allowed scope (prompt injection blocked)"},
            )
            yield _event(
                AgentEventType.ATTEMPT_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"error": "prompt injection blocked: path outside allowed scope"},
            )
            return

        # The worker itself should not apply this - it should be rejected by policy
        # But we simulate the worker attempting it
        yield _event(
            AgentEventType.EDIT_PROPOSED,
            run_id,
            task_id,
            attempt_id,
            {
                "file_path": file_path,
                "original_content": None,
                "proposed_content": "injected\n",
                "reason": "attempt path traversal",
            },
        )

        yield _event(
            AgentEventType.TOOL_INVOKED,
            run_id,
            task_id,
            attempt_id,
            {"tool_name": "write_file", "arguments": {"path": file_path, "content": "injected\n"}},
        )

        # This should fail - the worker doesn't have authority to write outside worktree
        target = workspace.worktree_path / file_path
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("injected\n", encoding="utf-8")
            yield _event(
                AgentEventType.TOOL_SUCCEEDED,
                run_id,
                task_id,
                attempt_id,
                {"tool_name": "write_file", "result_summary": f"wrote {file_path}"},
            )
            yield _event(
                AgentEventType.EDIT_APPLIED,
                run_id,
                task_id,
                attempt_id,
                {"file_path": file_path, "diff": _compute_diff(None, "injected\n")},
            )
            yield _event(
                AgentEventType.ATTEMPT_SUCCEEDED,
                run_id,
                task_id,
                attempt_id,
                {"message": "prompt injection succeeded (policy failure)"},
            )
        except (OSError, ValueError) as error:
            yield _event(
                AgentEventType.TOOL_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"tool_name": "write_file", "error": str(error)},
            )
            yield _event(
                AgentEventType.EDIT_REJECTED,
                run_id,
                task_id,
                attempt_id,
                {"file_path": file_path, "reason": f"write failed: {error}"},
            )
            yield _event(
                AgentEventType.ATTEMPT_FAILED,
                run_id,
                task_id,
                attempt_id,
                {"error": f"prompt injection blocked: {error}"},
            )


class FakeWorkerProbe:
    """Probe for fake worker availability."""

    async def probe(self) -> WorkerCapability:
        return WorkerCapability(
            worker_id="fake",
            version=_FAKE_WORKER_VERSION,
            capabilities=frozenset(_SUPPORTED_MODES),
        )


def create_fake_worker(worker_id: str) -> AgentWorker:
    """Factory function to create a fake worker by ID."""
    mode = FakeWorkerMode(worker_id)
    return FakeAgentWorker(mode)


__all__ = [
    "FakeAgentWorker",
    "FakeWorkerMode",
    "FakeWorkerProbe",
    "create_fake_worker",
]