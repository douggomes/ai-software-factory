"""Narrow ports for immutable evaluation snapshots and repository evidence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_software_factory.core.evaluation_workspace import (
    EvaluationCaptureRequest,
    EvaluationSnapshot,
    RepositoryEvidence,
)
from ai_software_factory.core.workspace_models import Workspace


class EvaluationWorkspaceError(RuntimeError):
    """Base error for snapshot and inspection failures."""


class EvaluationWorkspacePolicyError(EvaluationWorkspaceError):
    """Raised when identity, path, type or size violates snapshot policy."""


class EvaluationWorkspaceChangedError(EvaluationWorkspaceError):
    """Raised when the source changes during or after capture."""


class EvaluationWorkspaceArtifactError(EvaluationWorkspaceError):
    """Raised when manifest evidence cannot be stored or verified."""


class EvaluationWorkspaceCommandError(EvaluationWorkspaceError):
    """Raised when bounded Git metadata capture fails."""


@runtime_checkable
class WorkspaceLockLease(Protocol):
    """Opaque lease bound to one manager-owned workspace authority."""

    @property
    def active(self) -> bool:
        """Whether the original manager still authorizes this lease."""
        ...

    def close(self) -> None:
        """Return the lease without exposing its OS-level representation."""
        ...


@runtime_checkable
class WorkspaceLockCapability(Protocol):
    """Borrow an opaque lease from the workspace manager authority."""

    def borrow_lock_lease(self, workspace: Workspace) -> WorkspaceLockLease:
        """Return a lease for the exact active workspace lock."""
        ...


@runtime_checkable
class EvaluationWorkspace(Protocol):
    """Materialize a private, content-addressed copy of an authorized worktree."""

    async def capture(self, request: EvaluationCaptureRequest) -> EvaluationSnapshot:
        """Capture one immutable snapshot or fail before publishing it."""
        ...


@runtime_checkable
class RepositoryInspection(Protocol):
    """Verify a published snapshot and return only sanitized evidence."""

    def inspect(self, snapshot: EvaluationSnapshot) -> RepositoryEvidence:
        """Re-hash manifest and included files before returning evidence."""
        ...
