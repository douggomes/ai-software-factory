"""Workspace manager port for isolated Git worktrees."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ai_software_factory.core.workspace_models import Workspace, WorkspaceRequest, WorkspaceSnapshot


class WorkspaceError(RuntimeError):
    """Base error for workspace operations."""


class WorkspacePolicyError(WorkspaceError):
    """Raised when a repository, path or identity violates policy."""


class WorkspaceLockError(WorkspaceError):
    """Raised when another writer owns the task workspace lock."""


class WorkspaceIdentityError(WorkspaceError):
    """Raised when an existing path does not match the requested identity."""


class WorkspaceCommandError(WorkspaceError):
    """Raised when a controlled Git command fails."""


class WorkspaceCleanupError(WorkspaceError):
    """Raised when cleanup lacks confirmation or fails closed."""


@runtime_checkable
class WorkspaceManager(Protocol):
    """Create, inspect and explicitly clean one task workspace."""

    async def prepare(self, request: WorkspaceRequest) -> Workspace:
        """Prepare or idempotently reopen a workspace at its exact base."""
        ...

    async def inspect(self, workspace: Workspace) -> WorkspaceSnapshot:
        """Return status, diff and identity without mutating the workspace."""
        ...

    async def clean(self, workspace: Workspace, *, confirm: bool = False) -> None:
        """Remove only the confirmed, identity-matching workspace."""
        ...
