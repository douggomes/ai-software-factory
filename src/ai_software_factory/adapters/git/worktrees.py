"""Secure Git worktree adapter.

All Git effects pass through the ProcessRunner port.  The adapter holds one
OS-level non-blocking lock per task, disables hooks on every Git command and
refuses paths or existing worktrees whose canonical identity is unexpected.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import stat
import uuid
from pathlib import Path
from typing import Final, cast

from ai_software_factory.core.ids import AttemptId
from ai_software_factory.core.process_models import ProcessPolicy, ProcessRequest, TrustProfile
from ai_software_factory.core.workspace_models import Workspace, WorkspaceRequest, WorkspaceSnapshot
from ai_software_factory.ports.artifacts import ArtifactError, ArtifactRef, ArtifactStore
from ai_software_factory.ports.processes import ProcessRunner
from ai_software_factory.ports.workspace import (
    WorkspaceCleanupError,
    WorkspaceCommandError,
    WorkspaceIdentityError,
    WorkspaceLockError,
    WorkspaceManager,
    WorkspacePolicyError,
)

_DIRECTORY_MODE: Final[int] = 0o700
_LOCK_MODE: Final[int] = 0o600
_HOOKS_CONFIG: Final[str] = "core.hooksPath=/dev/null"
_WORKTREES_DIR: Final[str] = "worktrees"
_LOCKS_DIR: Final[str] = "locks"
_STATUS_PATH_OFFSET: Final[int] = 3


class GitWorktreeManager(WorkspaceManager):
    """Manage one or more isolated Git workspaces through injected ports."""

    def __init__(
        self,
        process_runner: ProcessRunner,
        artifact_store: ArtifactStore,
        git_executable: Path,
    ) -> None:
        self._process_runner = process_runner
        self._artifact_store = artifact_store
        self._git_executable = Path(git_executable)
        self._held_locks: dict[Path, int] = {}

    async def prepare(self, request: WorkspaceRequest) -> Workspace:
        repository = _canonical_directory(request.repository, "repository")
        factory_home = _ensure_runtime_home(request.factory_home)
        workspace = _workspace_identity(request, repository, factory_home)
        held_fd = self._held_locks.get(workspace.lock_path)
        acquired_here = held_fd is None
        if held_fd is None:
            held_fd = _acquire_lock(workspace.lock_path, workspace)
            self._held_locks[workspace.lock_path] = held_fd
        try:
            await self._assert_repository(repository, workspace)
            if _lexists(workspace.worktree_path):
                _assert_no_symlinks(workspace.worktree_path)
                await self._assert_existing_workspace(workspace)
            else:
                await self._create_workspace(workspace)
            return workspace
        except BaseException:
            if acquired_here:
                _release_lock(held_fd)
                self._held_locks.pop(workspace.lock_path, None)
            raise

    async def inspect(self, workspace: Workspace) -> WorkspaceSnapshot:
        _assert_workspace_paths(workspace)
        if not _lexists(workspace.worktree_path):
            raise WorkspaceIdentityError("workspace path does not exist")
        _assert_no_symlinks(workspace.worktree_path)
        await self._assert_existing_workspace(workspace)
        head = (await self._git(workspace, workspace.worktree_path, ("rev-parse", "HEAD")))[0]
        branch = (
            await self._git(
                workspace,
                workspace.worktree_path,
                ("rev-parse", "--abbrev-ref", "HEAD"),
            )
        )[0]
        status = (
            await self._git(
                workspace,
                workspace.worktree_path,
                ("status", "--porcelain=v1", "--untracked-files=all", "-z", "--"),
            )
        )[0]
        diff_stat = (await self._git(workspace, workspace.worktree_path, ("diff", "--stat", "--")))[
            0
        ]
        changed_files = _changed_files(status)
        return WorkspaceSnapshot(
            workspace=workspace,
            head_commit=_decode_line(head, "HEAD"),
            branch_name=_decode_line(branch, "branch"),
            clean=not changed_files,
            changed_files=changed_files,
            diff_stat=_decode_text(diff_stat),
        )

    async def clean(self, workspace: Workspace, *, confirm: bool = False) -> None:
        if not confirm:
            raise WorkspaceCleanupError("cleanup requires explicit confirmation")
        lock_fd = self._held_locks.get(workspace.lock_path)
        if lock_fd is None:
            raise WorkspaceLockError("cleanup requires the manager-owned writer lock")
        _assert_workspace_paths(workspace)
        if not _lexists(workspace.worktree_path):
            _release_lock(lock_fd)
            self._held_locks.pop(workspace.lock_path, None)
            return
        _assert_no_symlinks(workspace.worktree_path)
        await self._assert_existing_workspace(workspace)
        try:
            await self._git(
                workspace,
                workspace.repository,
                ("worktree", "remove", "--force", "--", str(workspace.worktree_path)),
            )
            if _lexists(workspace.worktree_path):
                raise WorkspaceCleanupError("Git reported success but workspace remains")
        finally:
            if not _lexists(workspace.worktree_path):
                _release_lock(lock_fd)
                self._held_locks.pop(workspace.lock_path, None)

    def close(self) -> None:
        """Release manager-owned locks without removing worktrees."""
        for lock_fd in tuple(self._held_locks.values()):
            _release_lock(lock_fd)
        self._held_locks.clear()

    async def _assert_repository(self, repository: Path, workspace: Workspace) -> None:
        output, _ = await self._git(workspace, repository, ("rev-parse", "--show-toplevel"))
        resolved = _canonical_directory(
            Path(_decode_line(output, "repository root")), "repository root"
        )
        if resolved != repository:
            raise WorkspacePolicyError("repository root does not match requested path")
        output, _ = await self._git(
            workspace,
            repository,
            ("rev-parse", "--verify", "--end-of-options", f"{workspace.base_commit}^{{commit}}"),
        )
        if _decode_line(output, "base commit") != workspace.base_commit:
            raise WorkspaceIdentityError("base commit does not resolve exactly")

    async def _assert_existing_workspace(self, workspace: Workspace) -> None:
        output, _ = await self._git(
            workspace,
            workspace.worktree_path,
            ("rev-parse", "--show-toplevel"),
        )
        top = _canonical_directory(Path(_decode_line(output, "worktree root")), "worktree root")
        if top != workspace.worktree_path:
            raise WorkspaceIdentityError("worktree root does not match persisted identity")
        output, _ = await self._git(
            workspace,
            workspace.worktree_path,
            ("rev-parse", "--abbrev-ref", "HEAD"),
        )
        if _decode_line(output, "branch") != workspace.branch_name:
            raise WorkspaceIdentityError("worktree branch does not match persisted identity")
        output, _ = await self._git(workspace, workspace.worktree_path, ("rev-parse", "HEAD"))
        head = _decode_line(output, "worktree HEAD")
        if head != workspace.base_commit:
            raise WorkspaceIdentityError("worktree HEAD differs from its approved base")

    async def _create_workspace(self, workspace: Workspace) -> None:
        parent = workspace.worktree_path.parent
        _ensure_directory_tree(parent, _DIRECTORY_MODE, owned_root=workspace.factory_home)
        if _lexists(workspace.worktree_path):
            raise WorkspaceIdentityError("worktree path appeared during preparation")
        branch_status = await self._git_result(
            workspace,
            workspace.repository,
            ("show-ref", "--verify", "--quiet", f"refs/heads/{workspace.branch_name}"),
        )
        if branch_status[0] == 0:
            branch_head, _ = await self._git(
                workspace,
                workspace.repository,
                ("rev-parse", "--verify", f"refs/heads/{workspace.branch_name}^{{commit}}"),
            )
            if _decode_line(branch_head, "branch base") != workspace.base_commit:
                raise WorkspaceIdentityError("existing branch does not point at approved base")
            args = ("worktree", "add", "--", str(workspace.worktree_path), workspace.branch_name)
        elif branch_status[0] != 0:
            args = (
                "worktree",
                "add",
                "-b",
                workspace.branch_name,
                "--",
                str(workspace.worktree_path),
                workspace.base_commit,
            )
        else:
            raise WorkspaceCommandError("unable to inspect requested branch")
        await self._git(workspace, workspace.repository, args)
        _assert_no_symlinks(workspace.worktree_path)
        await self._assert_existing_workspace(workspace)

    async def _git(
        self,
        workspace: Workspace,
        cwd: Path,
        args: tuple[str, ...],
    ) -> tuple[bytes, bytes]:
        result = await self._git_result(workspace, cwd, args)
        if result[0] != 0:
            raise WorkspaceCommandError(f"git command failed: {args[0]}")
        return result[1], result[2]

    async def _git_result(
        self,
        workspace: Workspace,
        cwd: Path,
        args: tuple[str, ...],
    ) -> tuple[int, bytes, bytes]:
        attempt = f"att-{uuid.uuid4().hex[:12]}"
        request = ProcessRequest(
            argv=(str(self._git_executable), "-c", _HOOKS_CONFIG, *args),
            executable=self._git_executable,
            cwd=cwd,
            policy=ProcessPolicy(
                allowed_executables=(self._git_executable,),
                allowed_cwd_roots=(cwd,),
            ),
            run_id=workspace.run_id,
            attempt_id=AttemptId(attempt),
            trust_profile=TrustProfile.TRUSTED,
        )
        try:
            result = await self._process_runner.run(request)
            stdout = _read_artifact(self._artifact_store, result.stdout_ref)
            stderr = _read_artifact(self._artifact_store, result.stderr_ref)
        except (ArtifactError, OSError, ValueError) as error:
            raise WorkspaceCommandError("Git command output could not be read") from error
        return result.returncode, stdout, stderr


def _read_artifact(artifact_store: ArtifactStore, reference: object | None) -> bytes:
    if reference is None:
        return b""
    return artifact_store.read(cast(ArtifactRef, reference))


def _workspace_identity(
    request: WorkspaceRequest,
    repository: Path,
    factory_home: Path,
) -> Workspace:
    slug = _repository_slug(repository)
    worktree_path = (
        factory_home / _WORKTREES_DIR / slug / request.run_id.value / request.task_id.value
    )
    lock_path = (
        factory_home / _LOCKS_DIR / slug / request.run_id.value / f"{request.task_id.value}.lock"
    )
    return Workspace(
        repository=repository,
        factory_home=factory_home,
        worktree_path=worktree_path,
        lock_path=lock_path,
        run_id=request.run_id,
        task_id=request.task_id,
        base_commit=request.base_commit,
        branch_name=cast(str, request.branch_name),
    )


def _repository_slug(repository: Path) -> str:
    name = repository.name
    if name and all(character.isalnum() or character in "._-" for character in name):
        return name
    return hashlib.sha256(str(repository).encode("utf-8")).hexdigest()[:16]


def _ensure_runtime_home(path: Path) -> Path:
    if not path.is_absolute():
        raise WorkspacePolicyError("factory_home must be absolute")
    if path == Path(path.anchor):
        raise WorkspacePolicyError("factory_home cannot be a filesystem root")
    _ensure_directory_tree(path, _DIRECTORY_MODE)
    resolved = _canonical_directory(path, "factory_home")
    if resolved == Path(resolved.anchor):
        raise WorkspacePolicyError("factory_home cannot resolve to a filesystem root")
    try:
        if os.lstat(resolved).st_uid != os.getuid():
            raise WorkspacePolicyError("factory_home owner mismatch")
    except OSError as error:
        raise WorkspacePolicyError("unable to inspect factory_home") from error
    os.chmod(resolved, _DIRECTORY_MODE)
    return resolved


def _ensure_directory_tree(path: Path, mode: int, *, owned_root: Path | None = None) -> None:
    if not path.is_absolute():
        raise WorkspacePolicyError("runtime path must be absolute")
    canonical_owned_root = (
        _canonical_directory(owned_root, "owned runtime root") if owned_root is not None else None
    )
    if canonical_owned_root is not None and not _is_within(path, canonical_owned_root):
        raise WorkspacePolicyError("runtime path escapes owned runtime root")
    current = Path(path.anchor)
    missing_seen = False
    for part in path.parts[1:]:
        current /= part
        current_stat, created = _ensure_directory_entry(current, mode)
        missing_seen = missing_seen or created
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise WorkspacePolicyError("runtime path contains a non-directory or symlink")
        managed = missing_seen or current == path
        if canonical_owned_root is not None and _is_within(current, canonical_owned_root):
            managed = True
        if managed:
            if current_stat.st_uid != os.getuid():
                raise WorkspacePolicyError("runtime directory owner mismatch")
            os.chmod(current, mode)


def _ensure_directory_entry(path: Path, mode: int) -> tuple[os.stat_result, bool]:
    try:
        return os.lstat(path), False
    except FileNotFoundError:
        try:
            os.mkdir(path, mode)
            return os.lstat(path), True
        except OSError as error:
            raise WorkspacePolicyError("unable to create secure runtime directory") from error
    except OSError as error:
        raise WorkspacePolicyError("unable to inspect runtime directory") from error


def _canonical_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise WorkspacePolicyError(f"{label} must be absolute")
    _assert_no_symlinks(path)
    try:
        resolved = path.resolve(strict=True)
        path_stat = os.lstat(resolved)
    except OSError as error:
        raise WorkspacePolicyError(f"cannot resolve {label}") from error
    if not stat.S_ISDIR(path_stat.st_mode):
        raise WorkspacePolicyError(f"{label} is not a directory")
    return resolved


def _assert_no_symlinks(path: Path) -> None:
    if not path.is_absolute():
        raise WorkspacePolicyError("workspace path must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current_stat = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise WorkspacePolicyError("cannot inspect workspace path") from error
        if stat.S_ISLNK(current_stat.st_mode):
            raise WorkspacePolicyError("workspace path contains a symlink")


def _assert_workspace_paths(workspace: Workspace) -> None:
    factory_home = _canonical_directory(workspace.factory_home, "factory_home")
    repository = _canonical_directory(workspace.repository, "repository")
    if factory_home != workspace.factory_home:
        raise WorkspaceIdentityError("factory_home path is not canonical")
    worktree_root = factory_home / _WORKTREES_DIR
    repository_slug = _repository_slug(repository)
    expected_worktree = (
        worktree_root / repository_slug / workspace.run_id.value / workspace.task_id.value
    )
    expected_lock = (
        factory_home
        / _LOCKS_DIR
        / repository_slug
        / workspace.run_id.value
        / f"{workspace.task_id.value}.lock"
    )
    _assert_no_symlinks(workspace.worktree_path)
    _assert_no_symlinks(workspace.lock_path)
    if repository != workspace.repository:
        raise WorkspaceIdentityError("repository path is not canonical")
    if workspace.worktree_path != expected_worktree or workspace.lock_path != expected_lock:
        raise WorkspaceIdentityError("workspace paths do not match persisted identity")
    if not _is_within(workspace.worktree_path, worktree_root):
        raise WorkspacePolicyError("worktree path escapes factory worktree root")
    if not _is_within(workspace.lock_path, factory_home / _LOCKS_DIR):
        raise WorkspacePolicyError("lock path escapes factory lock root")


def _acquire_lock(lock_path: Path, workspace: Workspace) -> int:
    _ensure_directory_tree(lock_path.parent, _DIRECTORY_MODE, owned_root=workspace.factory_home)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, _LOCK_MODE)
    except OSError as error:
        raise WorkspaceLockError("unable to open workspace lock") from error
    try:
        os.chmod(lock_path, _LOCK_MODE)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.ftruncate(fd, 0)
        os.write(fd, f"{workspace.run_id.value}\n{workspace.task_id.value}\n".encode("ascii"))
        os.fsync(fd)
        return fd
    except BlockingIOError as error:
        _release_lock(fd)
        raise WorkspaceLockError("workspace writer lock is already held") from error
    except OSError as error:
        _release_lock(fd)
        raise WorkspaceLockError("unable to acquire workspace lock") from error


def _release_lock(fd: int) -> None:
    with contextlib.suppress(OSError):
        fcntl.flock(fd, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(fd)


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _decode_line(data: bytes, label: str) -> str:
    value = data.decode("utf-8", errors="strict").strip()
    if not value:
        raise WorkspaceCommandError(f"Git returned empty {label}")
    return value


def _decode_text(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _changed_files(status: bytes) -> tuple[str, ...]:
    if not status:
        return ()
    entries = status.split(b"\x00")
    paths: list[str] = []
    for entry in entries:
        if not entry:
            continue
        decoded = entry.decode("utf-8", errors="strict")
        if len(decoded) <= _STATUS_PATH_OFFSET:
            raise WorkspaceCommandError("malformed Git status output")
        paths.append(decoded[_STATUS_PATH_OFFSET:])
    return tuple(paths)


WorktreeManager = GitWorktreeManager
