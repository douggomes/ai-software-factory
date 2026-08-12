"""Immutable workspace identities and snapshots.

The models describe the requested Git workspace without performing filesystem
or Git I/O.  The adapter owns canonicalization, locking and command effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ai_software_factory.core.ids import RunId, TaskId

_BASE_COMMIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_BRANCH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


class WorkspaceModelError(ValueError):
    """Raised when a workspace identity is malformed."""


@dataclass(frozen=True, slots=True)
class WorkspaceRequest:
    """Identity and roots required to prepare one isolated worktree."""

    repository: Path
    factory_home: Path
    run_id: RunId
    task_id: TaskId
    base_commit: str
    branch_name: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", Path(self.repository))
        object.__setattr__(self, "factory_home", Path(self.factory_home))
        if not _BASE_COMMIT_PATTERN.fullmatch(self.base_commit):
            raise WorkspaceModelError(f"invalid base_commit: {self.base_commit!r}")
        branch = self.branch_name or f"aif/{self.run_id.value}/{self.task_id.value}"
        _validate_branch_name(branch)
        object.__setattr__(self, "branch_name", branch)


@dataclass(frozen=True, slots=True)
class Workspace:
    """Persisted identity of a prepared workspace and its writer lock."""

    repository: Path
    factory_home: Path
    worktree_path: Path
    lock_path: Path
    run_id: RunId
    task_id: TaskId
    base_commit: str
    branch_name: str

    def __post_init__(self) -> None:
        for field_name in ("repository", "factory_home", "worktree_path", "lock_path"):
            object.__setattr__(self, field_name, Path(getattr(self, field_name)))
        if not _BASE_COMMIT_PATTERN.fullmatch(self.base_commit):
            raise WorkspaceModelError(f"invalid base_commit: {self.base_commit!r}")
        _validate_branch_name(self.branch_name)


@dataclass(frozen=True, slots=True)
class WorkspaceSnapshot:
    """Deterministic inspection result for a prepared workspace."""

    workspace: Workspace
    head_commit: str
    branch_name: str
    clean: bool
    changed_files: tuple[str, ...]
    diff_stat: str

    def __post_init__(self) -> None:
        if not _BASE_COMMIT_PATTERN.fullmatch(self.head_commit):
            raise WorkspaceModelError(f"invalid head_commit: {self.head_commit!r}")
        _validate_branch_name(self.branch_name)
        object.__setattr__(self, "changed_files", tuple(self.changed_files))


def _validate_branch_name(branch_name: str) -> None:
    if (
        not _BRANCH_PATTERN.fullmatch(branch_name)
        or "//" in branch_name
        or ".." in branch_name
        or branch_name.endswith("/")
        or branch_name.endswith(".")
        or "@{" in branch_name
    ):
        raise WorkspaceModelError(f"unsafe branch name: {branch_name!r}")
