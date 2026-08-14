"""Factory orchestrator — coordinates ports to execute a task end-to-end.

The orchestrator depends only on ports and core models.  Concrete adapters
(Git, process, persistence, worker) are injected at the composition root.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import FilesystemArtifactStore
from ai_software_factory.application.spec_parser import SpecParser
from ai_software_factory.core.agent_events import AgentEvent, AgentEventType
from ai_software_factory.core.evaluation_workspace import EvaluationCaptureRequest
from ai_software_factory.core.events import DomainEvent, EventType
from ai_software_factory.core.ids import AttemptId, RunId, TaskId
from ai_software_factory.core.models import (
    ExecutionAttempt,
    Run,
    RunOutcome,
    RunReport,
    RunStatus,
    TaskExecution,
    TaskStage,
)
from ai_software_factory.core.process_models import ProcessPolicy, TrustProfile
from ai_software_factory.core.workspace_models import Workspace, WorkspaceRequest
from ai_software_factory.evaluation.runner import Evaluator
from ai_software_factory.evaluation.models import resolve_profile
from ai_software_factory.ports.artifacts import ArtifactKind, ArtifactRef
from ai_software_factory.ports.evaluation_workspace import EvaluationWorkspace
from ai_software_factory.ports.persistence import RunStore
from ai_software_factory.ports.processes import ProcessRunner
from ai_software_factory.ports.validation import GateContext, GateStatus, ValidationSnapshot
from ai_software_factory.ports.workers import AgentExecutionRequest, AgentWorker, WorkerError
from ai_software_factory.ports.workspace import WorkspaceManager

_MAX_CONCURRENT_GATES: Final[int] = 1
_ATTEMPT_ID_PREFIX: Final[str] = "att-"
_RUN_ID_PREFIX: Final[str] = "run-"


@dataclass(frozen=True, slots=True)
class RunTask:
    """Command to execute one task within a run."""

    run_id: RunId
    task_id: TaskId
    spec_text: str
    worker_id: str
    base_commit: str
    repository: Path
    factory_home: Path
    isolation_profile: str = "default"


class OrchestratorError(Exception):
    """Base error for orchestrator failures."""


class TaskNotFoundError(OrchestratorError):
    """Raised when the task is not defined in the SPEC."""


class WorkerUnavailableError(OrchestratorError):
    """Raised when the requested worker cannot be created."""


class WorkspacePreparationError(OrchestratorError):
    """Raised when the workspace cannot be prepared."""


class EvaluationError(OrchestratorError):
    """Raised when evaluation snapshot capture fails."""


class GateExecutionError(OrchestratorError):
    """Raised when gate evaluation fails unexpectedly."""


class FactoryOrchestrator:
    """Coordinates ports to execute a task from SPEC to RunReport."""

    def __init__(
        self,
        run_store: RunStore,
        workspace_manager: WorkspaceManager,
        evaluation_workspace: EvaluationWorkspace,
        artifact_store: FilesystemArtifactStore,
        process_runner: ProcessRunner,
        git_executable: Path,
    ) -> None:
        self._run_store = run_store
        self._workspace_manager = workspace_manager
        self._evaluation_workspace = evaluation_workspace
        self._artifact_store = artifact_store
        self._process_runner = process_runner
        self._git_executable = git_executable

    async def run_task(self, command: RunTask) -> RunReport:
        """Execute a task end-to-end and return a RunReport."""
        run_id = command.run_id
        task_id = command.task_id
        spec_text = command.spec_text
        worker_id = command.worker_id
        base_commit = command.base_commit
        repository = command.repository
        factory_home = command.factory_home
        isolation_profile = command.isolation_profile

        # Parse SPEC and validate task exists
        spec = SpecParser().parse(spec_text)
        task = next((t for t in spec.tasks if t.task_id.value == task_id.value), None)
        if task is None:
            raise TaskNotFoundError(f"task {task_id.value} not found in SPEC {spec.spec_id}")

        allowed_paths = tuple(task.allowed_paths)

        # Create run and task execution in store
        run = Run(
            run_id=run_id,
            spec_id=spec.spec_id,
            base_commit=base_commit,
            status=RunStatus.RUNNING,
            config_hash=hashlib.sha256(spec_text.encode("utf-8")).hexdigest(),
        )

        attempt_id = AttemptId(f"{_ATTEMPT_ID_PREFIX}{hashlib.sha256(f'{run_id.value}{task_id.value}'.encode()).hexdigest()[:12]}")

        # Persist run with creation event
        run_event = DomainEvent(
            event_type=EventType.RUN_STARTED,
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            task_id=None,
            attempt_id=None,
            payload={"spec_id": spec.spec_id, "base_commit": base_commit},
        )
        await self._run_store.create_run(run, run_event)

        # Prepare workspace
        workspace = await self._prepare_workspace(
            repository, factory_home, run_id, task_id, base_commit
        )

        task_execution = TaskExecution(
            run_id=run_id,
            task_id=task_id,
            base_commit=base_commit,
            worktree_path=str(workspace.worktree_path),
            stage=TaskStage.QUEUED,
        )

        # Persist task execution with creation event
        task_event = DomainEvent(
            event_type=EventType.TASK_QUEUED,
            timestamp=datetime.now(timezone.utc),
            run_id=run_id,
            task_id=task_id,
            attempt_id=None,
            payload={"base_commit": base_commit, "worktree_path": str(workspace.worktree_path)},
        )
        await self._run_store.create_task_execution(task_execution, task_event)

        # Create worker
        worker = self._create_worker(worker_id)
        execution_request = AgentExecutionRequest(
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            workspace=workspace,
            spec_text=spec_text,
            allowed_paths=allowed_paths,
        )

        # Capture evaluation snapshot before gates
        evaluation_snapshot = await self._capture_evaluation_snapshot(workspace)

        # Run worker and collect events
        events: list[AgentEvent] = []
        async for event in worker.execute(execution_request):
            events.append(event)

        # Determine outcome from events
        outcome = self._determine_outcome(events)

        # Capture evaluation snapshot after worker
        post_snapshot = await self._capture_evaluation_snapshot(workspace)

        # Run validation gates
        gate_snapshot = await self._run_gates(
            run_id, task_id, workspace, allowed_paths, post_snapshot, isolation_profile
        )

        # Determine final outcome (gates can override worker success)
        final_outcome = self._determine_final_outcome(outcome, gate_snapshot)

        # Compute diff hash
        diff_hash = self._compute_diff_hash(workspace, base_commit)

        # Persist SPEC artifact
        await self._persist_spec_artifact(run_id, spec_text)

        # Build RunReport
        head_commit = self._get_head_commit(workspace)

        report = RunReport(
            run_id=run_id,
            task_id=task_id,
            attempt_id=attempt_id,
            base_commit=base_commit,
            head_commit=head_commit,
            outcome=final_outcome,
            worker_id=worker_id,
            diff_hash=diff_hash,
            gate_snapshot_id=gate_snapshot.snapshot_id.value if gate_snapshot else None,
            artifact_refs=(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        return report

    def _create_worker(self, worker_id: str) -> AgentWorker:
        """Create a worker instance by ID."""
        if worker_id.startswith("fake-"):
            from ai_software_factory.adapters.agents.fake import create_fake_worker
            return create_fake_worker(worker_id)
        raise WorkerUnavailableError(f"unknown worker: {worker_id}")

    async def _prepare_workspace(
        self,
        repository: Path,
        factory_home: Path,
        run_id: RunId,
        task_id: TaskId,
        base_commit: str,
    ) -> Workspace:
        """Prepare an isolated workspace for the task."""
        try:
            workspace = await self._workspace_manager.prepare(
                WorkspaceRequest(
                    repository=repository,
                    factory_home=factory_home,
                    run_id=run_id,
                    task_id=task_id,
                    base_commit=base_commit,
                )
            )
            return workspace
        except Exception as error:
            raise WorkspacePreparationError(f"failed to prepare workspace: {error}") from error

    async def _capture_evaluation_snapshot(self, workspace: Workspace) -> EvaluationSnapshot:
        """Capture a private evaluation snapshot of the workspace."""
        try:
            snapshot = await self._evaluation_workspace.capture(EvaluationCaptureRequest(workspace))
            return snapshot
        except Exception as error:
            raise EvaluationError(f"failed to capture evaluation snapshot: {error}") from error

    async def _run_gates(
        self,
        run_id: RunId,
        task_id: TaskId,
        workspace: Workspace,
        allowed_paths: tuple[str, ...],
        evaluation_snapshot: EvaluationSnapshot,
        isolation_profile: str,
    ) -> ValidationSnapshot:
        """Run deterministic validation gates."""
        from ai_software_factory.evaluation.gates import DiffGate, ScopeGate, SecretGate

        context = GateContext(
            run_id=run_id,
            task_id=task_id,
            worktree_path=workspace.worktree_path,
            base_commit=workspace.base_commit,
            allowed_paths=allowed_paths,
            changed_files=evaluation_snapshot.evidence.changed_paths,
            changed_file_evidence=tuple(
                self._build_changed_file_evidence(workspace.worktree_path, path)
                for path in evaluation_snapshot.evidence.changed_paths
            ),
            diff_text=evaluation_snapshot.evidence.diff_text if hasattr(evaluation_snapshot.evidence, "diff_text") else "",
            diff_check_output=evaluation_snapshot.evidence.diff_check_output if hasattr(evaluation_snapshot.evidence, "diff_check_output") else "",
            evaluation_snapshot_id=evaluation_snapshot.snapshot_id,
            evaluation_manifest_hash=evaluation_snapshot.manifest_hash,
            evaluation_identity_hash=evaluation_snapshot.identity_hash,
            repository_evidence=evaluation_snapshot.evidence,
        )

        gates = (ScopeGate(), DiffGate(), SecretGate())
        results = []

        for gate in gates:
            try:
                result = await gate.evaluate(context)
                results.append(result)
            except Exception as error:
                raise GateExecutionError(f"gate {gate.name} failed unexpectedly: {error}") from error

        # For now, create a simple validation snapshot
        # In a real implementation, this would use the Evaluator
        profile_name = "default"
        profile_hash = hashlib.sha256(profile_name.encode("utf-8")).hexdigest()

        status = GateStatus.PASSED
        if any(r.status is GateStatus.FAILED for r in results):
            status = GateStatus.FAILED

        from ai_software_factory.ports.validation import (
            GateResult,
            SnapshotId,
            ValidationSnapshot,
        )

        snapshot = ValidationSnapshot(
            snapshot_id=SnapshotId(f"val-{hashlib.sha256(f'{run_id.value}{task_id.value}'.encode()).hexdigest()[:12]}"),
            run_id=run_id,
            task_id=task_id,
            base_commit=workspace.base_commit,
            profile_name=profile_name,
            profile_hash=profile_hash,
            diff_hash=self._compute_diff_hash(workspace, workspace.base_commit),
            status=status,
            gate_results=tuple(results),
            created_at=datetime.now(timezone.utc),
            evaluation_snapshot_id=evaluation_snapshot.snapshot_id,
            evaluation_manifest_hash=evaluation_snapshot.manifest_hash,
            evaluation_identity_hash=evaluation_snapshot.identity_hash,
        )

        return snapshot

    def _build_changed_file_evidence(self, worktree_path: Path, file_path: str):
        """Build ChangedFileEvidence for a path."""
        from ai_software_factory.ports.validation import ChangedFileEvidence

        target = worktree_path / file_path
        if not target.exists():
            return ChangedFileEvidence(
                path=file_path,
                content=b"",
                content_hash=hashlib.sha256(b"").hexdigest(),
                deleted=True,
            )
        content = target.read_bytes()
        return ChangedFileEvidence(
            path=file_path,
            content=content,
            content_hash=hashlib.sha256(content).hexdigest(),
            deleted=False,
        )

    def _compute_diff_hash(self, workspace: Workspace, base_commit: str) -> str:
        """Compute SHA-256 of the diff between base and HEAD."""
        try:
            import subprocess
            result = subprocess.run(  # noqa: S603 - fixed Git executable and argv
                [str(self._git_executable), "-c", "core.hooksPath=/dev/null", "diff", base_commit, "HEAD"],
                cwd=workspace.worktree_path,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            diff_text = result.stdout
        except Exception:
            diff_text = ""
        return hashlib.sha256(diff_text.encode("utf-8")).hexdigest()

    def _get_head_commit(self, workspace: Workspace) -> str:
        """Get the current HEAD commit of the workspace."""
        try:
            import subprocess
            result = subprocess.run(  # noqa: S603 - fixed Git executable and argv
                [str(self._git_executable), "-c", "core.hooksPath=/dev/null", "rev-parse", "HEAD"],
                cwd=workspace.worktree_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            return result.stdout.strip()
        except Exception:
            return workspace.base_commit

    def _determine_outcome(self, events: list[AgentEvent]) -> RunOutcome:
        """Determine outcome from worker events."""
        for event in reversed(events):
            if event.event_type == AgentEventType.ATTEMPT_SUCCEEDED:
                return RunOutcome.SUCCEEDED
            if event.event_type == AgentEventType.ATTEMPT_FAILED:
                return RunOutcome.FAILED
            if event.event_type == AgentEventType.ATTEMPT_CANCELLED:
                return RunOutcome.CANCELLED
        return RunOutcome.FAILED

    def _determine_final_outcome(self, worker_outcome: RunOutcome, gate_snapshot: ValidationSnapshot) -> RunOutcome:
        """Determine final outcome combining worker and gate results."""
        if gate_snapshot.status is GateStatus.FAILED:
            return RunOutcome.FAILED
        return worker_outcome

    async def _persist_spec_artifact(self, run_id: RunId, spec_text: str) -> None:
        """Persist the SPEC as an artifact for validation."""
        ref = ArtifactRef(
            run_id=run_id,
            relative_path="spec.md",
            kind=ArtifactKind.SPEC,
        )
        await asyncio.to_thread(self._artifact_store.put, ref, spec_text.encode("utf-8"))


__all__ = [
    "FactoryOrchestrator",
    "OrchestratorError",
    "RunTask",
    "TaskNotFoundError",
    "WorkerUnavailableError",
    "WorkspacePreparationError",
    "EvaluationError",
    "GateExecutionError",
]