"""``aif`` command-line entry point.

Offline, read-only and local commands live here: version, diagnostics
(``doctor``), SPEC validation (``spec validate``), run status and event
export. No command in this module invokes a provider or performs a network
call beyond local filesystem/SQLite access.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import fcntl
import hashlib
import json
import os
import selectors
import shutil
import signal
import sqlite3
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ai_software_factory import __version__
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.persistence.artifact_store import (
    FilesystemArtifactStore,
    SqliteEventLogReader,
)
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.application.queries import (
    RunEventsQuery,
    RunStatusQuery,
    format_events_ndjson,
    format_run_status_json,
)
from ai_software_factory.application.spec_parser import SpecParseError, SpecParser
from ai_software_factory.application.spec_validator import SpecValidator
from ai_software_factory.config import ConfigError, Settings
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.models import TaskExecution
from ai_software_factory.core.process_models import ProcessPolicy
from ai_software_factory.core.spec_models import (
    SoftwareSpec,
    ValidationReport,
    canonical_json,
)
from ai_software_factory.core.workspace_models import Workspace, WorkspaceSnapshot
from ai_software_factory.evaluation.models import resolve_profile
from ai_software_factory.evaluation.runner import Evaluator
from ai_software_factory.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactNotFoundError,
    ArtifactRef,
)
from ai_software_factory.ports.persistence import RunNotFoundError
from ai_software_factory.ports.validation import (
    ChangedFileEvidence,
    GateContext,
    GateStatus,
    ValidationError,
    ValidationSnapshot,
)
from ai_software_factory.ports.workspace import WorkspaceError

#: Executable name probed for each supported worker/reviewer CLI. Presence is
#: checked with ``shutil.which`` only; the executable is never invoked.
PROVIDER_EXECUTABLES: Final[Mapping[str, str]] = {
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
}

_VERSION_PROBE_TIMEOUT_SECONDS: Final[float] = 5.0
_VERSION_FLAG: Final[str] = "--version"
_EXIT_VALID: Final[int] = 0
_EXIT_INVALID: Final[int] = 2
_EXIT_NOT_FOUND: Final[int] = 1
_FACTORY_HOME_ENV: Final[str] = "AIF_FACTORY_HOME"
_DEFAULT_FACTORY_HOME: Final[Path] = Path.home() / ".aifactory"
_STATE_DB_NAME: Final[str] = "state.db"
_WORKTREE_DIR_NAME: Final[str] = "worktrees"
_LOCK_DIR_NAME: Final[str] = "locks"
_LOCK_FILE_MODE: Final[int] = 0o600
_GIT_HOOKS_CONFIG: Final[str] = "core.hooksPath=/dev/null"
_GIT_INSPECT_TIMEOUT_SECONDS: Final[float] = 5.0
_MAX_WORKSPACE_DISCOVERY_ENTRIES: Final[int] = 256
_MAX_VALIDATION_FILES: Final[int] = 4096
_MAX_VALIDATION_FILE_BYTES: Final[int] = 8_388_608
_MAX_VALIDATION_TOTAL_BYTES: Final[int] = 67_108_864
_MAX_GIT_OUTPUT_BYTES: Final[int] = 8_388_608
_GIT_READ_CHUNK_BYTES: Final[int] = 32_768
_WORKTREE_IDENTITY_PARTS: Final[int] = 3
_EMPTY_SHA256: Final[str] = hashlib.sha256(b"").hexdigest()
_CREDENTIAL_PATHSPECS: Final[tuple[str, ...]] = (
    ".env",
    ".env.*",
    "auth.json",
    "id_rsa",
    "id_ed25519",
    ":(glob)**/.env",
    ":(glob)**/.env.*",
    ":(glob)**/auth.json",
    ":(glob)**/id_rsa",
    ":(glob)**/id_ed25519",
)
#: Well-known relative path for the SPEC artifact persisted for a run. Any
#: caller that creates a ``Run`` (a future ``aif run`` command) is expected
#: to persist the parsed SPEC under this path so ``aif validate`` can derive
#: a task's independent allowed-path scope without trusting worker output.
_SPEC_ARTIFACT_RELATIVE_PATH: Final[str] = "spec.md"


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Read-only probe result for a required command-line tool."""

    available: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class DoctorProbes:
    """Injectable, read-only probes used to build a doctor report.

    Kept as plain callables (not a provider adapter) so tests can substitute
    deterministic doubles without touching the real environment or PATH.
    """

    python_version: Callable[[], str]
    sqlite_version: Callable[[], str]
    tool_probe: Callable[[str], ToolStatus]
    provider_probe: Callable[[str], str]


def probe_tool(
    executable: str,
    *,
    version_flag: str = _VERSION_FLAG,
    timeout: float = _VERSION_PROBE_TIMEOUT_SECONDS,
) -> ToolStatus:
    """Report whether ``executable`` is installed and its reported version.

    Read-only: resolves the executable on PATH and, only if found, runs it
    with a version flag. Never used to probe a worker/provider executable.
    """
    resolved = shutil.which(executable)
    if resolved is None:
        return ToolStatus(available=False, version=None)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, read-only version probe
            [resolved, version_flag],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ToolStatus(available=False, version=None)
    if completed.returncode != 0:
        return ToolStatus(available=False, version=None)
    lines = (completed.stdout or completed.stderr or "").strip().splitlines()
    return ToolStatus(available=True, version=lines[0] if lines else None)


def probe_provider(executable: str) -> str:
    """Report worker/reviewer CLI presence without ever executing it."""
    return "available" if shutil.which(executable) is not None else "unavailable"


def default_probes() -> DoctorProbes:
    return DoctorProbes(
        python_version=lambda: sys.version.split()[0],
        sqlite_version=lambda: sqlite3.sqlite_version,
        tool_probe=probe_tool,
        provider_probe=probe_provider,
    )


def build_doctor_report(probes: DoctorProbes) -> dict[str, object]:
    """Assemble the deterministic diagnostic report from injected probes."""
    uv_status = probes.tool_probe("uv")
    git_status = probes.tool_probe("git")
    return {
        "python": {"version": probes.python_version()},
        "uv": {"available": uv_status.available, "version": uv_status.version},
        "git": {"available": git_status.available, "version": git_status.version},
        "sqlite": {"available": True, "version": probes.sqlite_version()},
        "providers": {
            name: probes.provider_probe(executable)
            for name, executable in sorted(PROVIDER_EXECUTABLES.items())
        },
    }


def resolve_factory_home(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the runtime factory home directory."""
    source = os.environ if env is None else env
    raw = source.get(_FACTORY_HOME_ENV)
    if raw is None or raw.strip() == "":
        return _DEFAULT_FACTORY_HOME.expanduser().resolve()
    return Path(raw).expanduser().resolve()


def resolve_state_db(factory_home: Path | None = None) -> Path:
    home = factory_home if factory_home is not None else resolve_factory_home()
    return home / _STATE_DB_NAME


def _run_spec_validate(
    path: Path,
    task_id: str | None,
    as_json: bool,
) -> int:
    """Validate a SPEC file — pure, no runtime/worktree/provider side effects."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        _emit_read_error(error, path, as_json)
        return _EXIT_INVALID
    parser = SpecParser()
    try:
        spec = parser.parse(text)
    except SpecParseError as error:
        _emit_parse_error(error, as_json)
        return _EXIT_INVALID
    validator = SpecValidator()
    report = validator.validate(spec, task_id=task_id)
    _emit_validation_report(report, task_id, as_json)
    return _EXIT_VALID if report.valid else _EXIT_INVALID


def _emit_read_error(error: OSError, path: Path, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"valid": False, "error": str(error)}, sort_keys=True))
    else:
        print(f"error: cannot read {path}: {error}", file=sys.stderr)


def _emit_parse_error(error: SpecParseError, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                {"valid": False, "errors": [{"code": "PARSE_ERROR", "message": str(error)}]},
                sort_keys=True,
            )
        )
    else:
        print(f"error: {error}", file=sys.stderr)


def _emit_validation_report(
    report: ValidationReport,
    task_id: str | None,
    as_json: bool,
) -> None:
    if as_json:
        _emit_json_report(report, task_id)
    else:
        _emit_text_report(report)


def _emit_json_report(report: ValidationReport, task_id: str | None) -> None:
    output = report.to_json_dict()
    if report.valid and report.spec is not None and task_id is not None:
        filtered_tasks = [t for t in report.spec.tasks if t.task_id.value == task_id]
        filtered_spec = SoftwareSpec(
            spec_id=report.spec.spec_id,
            schema_version=report.spec.schema_version,
            title=report.spec.title,
            tasks=tuple(filtered_tasks),
        )
        output["spec"] = json.loads(canonical_json(filtered_spec))
    print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))


def _emit_text_report(report: ValidationReport) -> None:
    if report.valid and report.spec is not None:
        print(f"SPEC {report.spec.spec_id} is valid ({len(report.spec.tasks)} tasks)")
        return
    print(f"SPEC validation failed with {len(report.errors)} error(s):")
    for err in report.errors:
        location = f" [{err.path}]" if err.path else ""
        print(f"  - {err.code}: {err.message}{location}")


def _parse_run_id(raw: str) -> RunId:
    return RunId(raw)


async def _run_status_async(run_id: RunId, db_path: Path) -> str:
    store = await SQLiteRunStore.create(db_path)
    try:
        view = await RunStatusQuery(store).execute(run_id)
        return format_run_status_json(view)
    finally:
        await store.close()


async def _run_events_async(run_id: RunId, db_path: Path) -> str:
    store = await SQLiteRunStore.create(db_path)
    try:
        reader = await SqliteEventLogReader.connect(db_path)
        try:
            events = await RunEventsQuery(store, reader).execute(run_id)
            return format_events_ndjson(events)
        finally:
            await reader.close()
    finally:
        await store.close()


def _run_status_command(run_id_raw: str, *, as_json: bool, factory_home: Path | None) -> int:
    if not as_json:
        print("error: aif status requires --json", file=sys.stderr)
        return _EXIT_INVALID
    try:
        run_id = _parse_run_id(run_id_raw)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    db_path = resolve_state_db(factory_home)
    if not db_path.exists():
        print(f"error: state database not found at {db_path}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    try:
        payload = asyncio.run(_run_status_async(run_id, db_path))
    except RunNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    sys.stdout.write(payload)
    return _EXIT_VALID


def _run_events_command(run_id_raw: str, *, factory_home: Path | None) -> int:
    try:
        run_id = _parse_run_id(run_id_raw)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    db_path = resolve_state_db(factory_home)
    if not db_path.exists():
        print(f"error: state database not found at {db_path}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    try:
        payload = asyncio.run(_run_events_async(run_id, db_path))
    except RunNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    sys.stdout.write(payload)
    return _EXIT_VALID


def _run_workspace_inspect_command(run_id_raw: str, *, factory_home: Path) -> int:
    manager: GitWorktreeManager | None = None
    try:
        run_id = _parse_run_id(run_id_raw)
        git_executable = _resolve_git_executable()
        candidates = _discover_workspace_paths(factory_home, run_id)
        if not candidates:
            print(f"error: no workspace found for {run_id.value}", file=sys.stderr)
            return _EXIT_NOT_FOUND
        artifact_store = FilesystemArtifactStore(factory_home)
        manager = GitWorktreeManager(
            AsyncioProcessRunner(artifact_store), artifact_store, git_executable
        )
        snapshots = asyncio.run(
            _inspect_workspace_candidates(manager, factory_home, git_executable, run_id, candidates)
        )
    except (OSError, ValueError, WorkspaceError) as error:
        print(f"error: workspace inspection failed: {error}", file=sys.stderr)
        return _EXIT_INVALID
    finally:
        if manager is not None:
            manager.close()
    print(
        json.dumps(
            {
                "run_id": run_id.value,
                "workspaces": [
                    {
                        "base_commit": snapshot.head_commit,
                        "branch": snapshot.branch_name,
                        "changed_files": list(snapshot.changed_files),
                        "clean": snapshot.clean,
                        "diff_stat": snapshot.diff_stat,
                        "lock": str(snapshot.workspace.lock_path),
                        "path": str(snapshot.workspace.worktree_path),
                        "repository": str(snapshot.workspace.repository),
                    }
                    for snapshot in snapshots
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return _EXIT_VALID


async def _inspect_workspace_candidates(
    manager: GitWorktreeManager,
    factory_home: Path,
    git_executable: Path,
    run_id: RunId,
    candidates: tuple[Path, ...],
) -> tuple[WorkspaceSnapshot, ...]:
    snapshots: list[WorkspaceSnapshot] = []
    for worktree_path in candidates:
        repository_raw = _read_only_git(
            git_executable, worktree_path, ("rev-parse", "--git-common-dir")
        )
        common_git_dir = Path(repository_raw)
        if not common_git_dir.is_absolute():
            common_git_dir = worktree_path / common_git_dir
        repository = _canonical_cli_directory(common_git_dir, "Git common directory").parent
        base_commit = _read_only_git(git_executable, worktree_path, ("rev-parse", "HEAD"))
        branch_name = _read_only_git(
            git_executable, worktree_path, ("rev-parse", "--abbrev-ref", "HEAD")
        )
        task_id = _parse_task_id(worktree_path.name)
        relative = worktree_path.relative_to(factory_home / _WORKTREE_DIR_NAME)
        lock_path = factory_home / _LOCK_DIR_NAME / relative.parent / f"{task_id.value}.lock"
        workspace = Workspace(
            repository=repository,
            factory_home=factory_home,
            worktree_path=worktree_path,
            lock_path=lock_path,
            run_id=run_id,
            task_id=task_id,
            base_commit=base_commit,
            branch_name=branch_name,
        )
        snapshots.append(await manager.inspect(workspace))
    return tuple(snapshots)


def _resolve_git_executable() -> Path:
    executable = shutil.which("git")
    if executable is None:
        raise WorkspaceError("git executable is unavailable")
    return Path(executable).resolve(strict=True)


def _resolve_uv_executable() -> Path:
    executable = shutil.which("uv")
    if executable is None:
        raise WorkspaceError("uv executable is unavailable")
    return Path(executable).resolve(strict=True)


class ValidationTaskSelectionError(ValueError):
    """Raised when ``aif validate`` cannot unambiguously select a task execution."""


@dataclass(frozen=True, slots=True)
class _TaskValidationConfig:
    allowed_paths: tuple[str, ...]
    validation_commands: tuple[tuple[str, ...], ...]


def _select_task_execution(task_executions: tuple[TaskExecution, ...]) -> TaskExecution:
    if len(task_executions) != 1:
        raise ValidationTaskSelectionError(
            f"aif validate requires exactly one task execution, found {len(task_executions)}"
        )
    return task_executions[0]


def _load_task_validation_config(
    artifact_store: FilesystemArtifactStore, run_id: RunId, task_id: TaskId
) -> _TaskValidationConfig:
    ref = ArtifactRef(
        run_id=run_id,
        relative_path=_SPEC_ARTIFACT_RELATIVE_PATH,
        kind=ArtifactKind.SPEC,
    )
    try:
        raw = artifact_store.read(ref)
    except ArtifactNotFoundError as error:
        raise ValidationTaskSelectionError(
            f"no SPEC artifact persisted for {run_id.value}"
        ) from error
    try:
        spec = SpecParser().parse(raw.decode("utf-8"))
    except (UnicodeDecodeError, SpecParseError) as error:
        raise ValidationTaskSelectionError("persisted SPEC artifact is invalid") from error
    report = SpecValidator().validate(spec, task_id=task_id.value)
    if not report.valid:
        raise ValidationTaskSelectionError("persisted SPEC artifact failed validation")
    for task in spec.tasks:
        if task.task_id.value == task_id.value:
            return _TaskValidationConfig(
                allowed_paths=task.allowed_paths,
                validation_commands=tuple(command.args for command in task.validation_commands),
            )
    raise ValidationTaskSelectionError(f"SPEC does not define task {task_id.value}")


def _capture_diff(
    git_executable: Path, worktree_path: Path, base_commit: str
) -> tuple[tuple[str, ...], tuple[ChangedFileEvidence, ...], str, str]:
    name_only = _git_diff_output(
        git_executable,
        worktree_path,
        (
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--name-only",
            "-z",
            base_commit,
            "--",
        ),
    )
    untracked = _git_output(
        git_executable,
        worktree_path,
        ("ls-files", "--others", "--exclude-standard", "-z", "--"),
        label="untracked paths",
    )
    ignored = _git_output(
        git_executable,
        worktree_path,
        (
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *_CREDENTIAL_PATHSPECS,
        ),
        label="ignored paths",
    )
    tracked_paths = tuple(path for path in name_only.split("\x00") if path)
    untracked_paths = tuple(path for path in untracked.split("\x00") if path)
    ignored_credential_paths = tuple(
        path for path in ignored.split("\x00") if path and _is_credential_path(path)
    )
    changed_files = tuple(
        dict.fromkeys((*tracked_paths, *untracked_paths, *ignored_credential_paths))
    )
    if len(changed_files) > _MAX_VALIDATION_FILES:
        raise WorkspaceError("validation changed-file limit exceeded")
    evidence = _capture_changed_files(worktree_path, changed_files)
    diff_text = _git_diff_output(
        git_executable,
        worktree_path,
        ("diff", "--no-ext-diff", "--no-textconv", "--binary", base_commit, "--"),
    )
    untracked_manifest = "".join(
        f"untracked {item.path} {item.content_hash}\n"
        for item in evidence
        if item.path in untracked_paths or item.path in ignored_credential_paths
    )
    diff_text = f"{diff_text}{untracked_manifest}"
    diff_check_output = _git_diff_output(
        git_executable,
        worktree_path,
        ("diff", "--no-ext-diff", "--no-textconv", "--check", base_commit, "--"),
        diff_check=True,
    )
    untracked_check = _untracked_diff_check(evidence, frozenset(untracked_paths))
    diff_check_output = "\n".join(part for part in (diff_check_output, untracked_check) if part)
    return changed_files, evidence, diff_text, diff_check_output


def _capture_changed_files(
    worktree_path: Path, changed_files: tuple[str, ...]
) -> tuple[ChangedFileEvidence, ...]:
    evidence: list[ChangedFileEvidence] = []
    total_bytes = 0
    for path in changed_files:
        item = _capture_changed_file(worktree_path, path)
        total_bytes += len(item.content)
        if total_bytes > _MAX_VALIDATION_TOTAL_BYTES:
            raise WorkspaceError("validation total changed-content limit exceeded")
        evidence.append(item)
    return tuple(evidence)


def _is_credential_path(path: str) -> bool:
    name = Path(path).name
    return (
        name == ".env"
        or name.startswith(".env.")
        or name
        in {
            "auth.json",
            "id_rsa",
            "id_ed25519",
        }
    )


def _untracked_diff_check(
    evidence: tuple[ChangedFileEvidence, ...], untracked_paths: frozenset[str]
) -> str:
    findings: list[str] = []
    for item in evidence:
        if item.path not in untracked_paths or item.scan_error is not None:
            continue
        if any(line.endswith((b" ", b"\t")) for line in item.content.splitlines()):
            findings.append(f"{item.path}: trailing whitespace")
        if any(
            line.startswith((b"<<<<<<<", b"=======", b">>>>>>>"))
            for line in item.content.splitlines()
        ):
            findings.append(f"{item.path}: conflict marker")
    return "\n".join(findings)


def _capture_changed_file(worktree_path: Path, relative_path: str) -> ChangedFileEvidence:
    if _is_credential_path(relative_path):
        return ChangedFileEvidence(
            path=relative_path,
            content=b"",
            content_hash=hashlib.sha256(relative_path.encode("utf-8")).hexdigest(),
            scan_error="credential-shaped path is never read",
        )
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return ChangedFileEvidence(
            path=relative_path,
            content=b"",
            content_hash=_EMPTY_SHA256,
            scan_error="unsafe path",
        )
    try:
        fd = _open_changed_file(worktree_path, candidate)
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise WorkspaceError("changed path is not a regular file")
        if file_stat.st_size > _MAX_VALIDATION_FILE_BYTES:
            raise WorkspaceError("changed file exceeds validation scan limit")
        try:
            data = _read_changed_file(fd)
        finally:
            os.close(fd)
    except FileNotFoundError:
        return ChangedFileEvidence(
            path=relative_path,
            content=b"",
            content_hash=_EMPTY_SHA256,
            deleted=True,
        )
    except (OSError, WorkspaceError) as error:
        return ChangedFileEvidence(
            path=relative_path,
            content=b"",
            content_hash=_EMPTY_SHA256,
            scan_error=str(error),
        )
    return ChangedFileEvidence(
        path=relative_path,
        content=data,
        content_hash=hashlib.sha256(data).hexdigest(),
    )


def _open_changed_file(worktree_path: Path, relative_path: Path) -> int:
    current_fd = _open_directory_path(worktree_path)
    try:
        for part in relative_path.parts[:-1]:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return os.open(
            relative_path.parts[-1],
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current_fd,
        )
    finally:
        os.close(current_fd)


def _directory_open_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_directory_path(path: Path) -> int:
    if not path.is_absolute():
        raise WorkspaceError("directory path must be absolute")
    current_fd = os.open(path.anchor, _directory_open_flags())
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _open_relative_file(root: Path, relative_path: Path, flags: int) -> int:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise WorkspaceError("relative file path is unsafe")
    current_fd = _open_directory_path(root)
    try:
        for part in relative_path.parts[:-1]:
            next_fd = os.open(part, _directory_open_flags(), dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return os.open(
            relative_path.parts[-1],
            flags | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=current_fd,
        )
    finally:
        os.close(current_fd)


def _read_changed_file(fd: int) -> bytes:
    output = bytearray()
    while True:
        remaining = _MAX_VALIDATION_FILE_BYTES + 1 - len(output)
        chunk = os.read(fd, min(_GIT_READ_CHUNK_BYTES, remaining))
        if not chunk:
            return bytes(output)
        output.extend(chunk)
        if len(output) > _MAX_VALIDATION_FILE_BYTES:
            raise WorkspaceError("changed file exceeds validation scan limit")


@dataclass(frozen=True, slots=True)
class _ValidateEnvironment:
    """Resolved, host-specific inputs the composition root supplies to validate."""

    db_path: Path
    factory_home: Path
    git_executable: Path
    uv_executable: Path


async def _run_validate_async(
    run_id: RunId, profile_name: str, environment: _ValidateEnvironment
) -> ValidationSnapshot:
    store = await SQLiteRunStore.create(environment.db_path)
    try:
        run_snapshot = await store.load_run(run_id)
        task_execution = _select_task_execution(run_snapshot.task_executions)
        artifact_store = FilesystemArtifactStore(environment.factory_home)
        task_config = _load_task_validation_config(artifact_store, run_id, task_execution.task_id)
        worktree_path = _validated_worktree_path(
            environment.factory_home,
            run_id,
            task_execution,
            environment.git_executable,
        )
        process_runner = AsyncioProcessRunner(artifact_store)
        process_policy = ProcessPolicy(
            allowed_executables=(environment.uv_executable,),
            allowed_cwd_roots=(worktree_path,),
        )

        def capture_context() -> GateContext:
            changed_files, evidence, diff_text, diff_check_output = _capture_diff(
                environment.git_executable, worktree_path, task_execution.base_commit
            )
            return GateContext(
                run_id=run_id,
                task_id=task_execution.task_id,
                worktree_path=worktree_path,
                base_commit=task_execution.base_commit,
                allowed_paths=task_config.allowed_paths,
                changed_files=changed_files,
                changed_file_evidence=evidence,
                diff_text=diff_text,
                diff_check_output=diff_check_output,
            )

        with _validation_lock(
            environment.factory_home, worktree_path, run_id, task_execution.task_id
        ):
            context = capture_context()
            profile = resolve_profile(
                profile_name,
                uv_executable=environment.uv_executable,
                process_runner=process_runner,
                process_policy=process_policy,
                validation_commands=task_config.validation_commands,
            )
            evaluator = Evaluator(context, artifact_store, context_refresh=capture_context)
            return await evaluator.run(profile)
    finally:
        await store.close()


def _validated_worktree_path(
    factory_home: Path,
    run_id: RunId,
    task_execution: TaskExecution,
    git_executable: Path,
) -> Path:
    worktree_path = _canonical_cli_directory(
        Path(task_execution.worktree_path), "validation worktree"
    )
    root = _canonical_cli_directory(factory_home, "factory home") / _WORKTREE_DIR_NAME
    try:
        relative = worktree_path.relative_to(root)
    except ValueError as error:
        raise WorkspaceError("validation worktree escapes factory home") from error
    if (
        len(relative.parts) != _WORKTREE_IDENTITY_PARTS
        or relative.parts[1] != run_id.value
        or relative.parts[2] != task_execution.task_id.value
    ):
        raise WorkspaceError("validation worktree identity does not match run/task")
    top_level = _git_output(
        git_executable,
        worktree_path,
        ("rev-parse", "--show-toplevel"),
        label="validation worktree root",
    )
    if Path(top_level).resolve(strict=True) != worktree_path:
        raise WorkspaceError("validation worktree Git root does not match persisted path")
    base = _git_output(
        git_executable,
        worktree_path,
        ("rev-parse", "--verify", "--end-of-options", f"{task_execution.base_commit}^{{commit}}"),
        label="validation base commit",
    )
    if base != task_execution.base_commit:
        raise WorkspaceError("validation base commit does not resolve exactly")
    ancestry = _run_controlled_git(
        git_executable,
        worktree_path,
        ("merge-base", "--is-ancestor", task_execution.base_commit, "HEAD"),
    )
    if ancestry.returncode != 0:
        raise WorkspaceError("validation worktree HEAD does not descend from base commit")
    return worktree_path


@contextlib.contextmanager
def _validation_lock(
    factory_home: Path,
    worktree_path: Path,
    run_id: RunId,
    task_id: TaskId,
) -> Generator[None]:
    canonical_home = _canonical_cli_directory(factory_home, "factory home")
    relative = worktree_path.relative_to(canonical_home / _WORKTREE_DIR_NAME)
    lock_path = (
        canonical_home / _LOCK_DIR_NAME / relative.parts[0] / run_id.value / f"{task_id.value}.lock"
    )
    _canonical_cli_directory(lock_path.parent, "validation lock directory")
    try:
        fd = _open_relative_file(
            canonical_home,
            lock_path.relative_to(canonical_home),
            os.O_RDWR,
        )
    except OSError as error:
        raise WorkspaceError("validation lock is unavailable") from error
    try:
        lock_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.getuid()
            or stat.S_IMODE(lock_stat.st_mode) != _LOCK_FILE_MODE
            or lock_stat.st_nlink != 1
        ):
            raise WorkspaceError("validation lock identity is unsafe")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise WorkspaceError("validation worktree still has an active writer") from error
        os.lseek(fd, 0, os.SEEK_SET)
        identity = os.read(fd, 256).decode("ascii", errors="strict")
        if identity != f"{run_id.value}\n{task_id.value}\n":
            raise WorkspaceError("validation lock identity does not match run/task")
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _snapshot_summary(snapshot: ValidationSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": snapshot.snapshot_id.value,
        "status": snapshot.status.name,
        "diff_hash": snapshot.diff_hash,
        "gates": [
            {"name": result.gate_name, "status": result.status.name}
            for result in snapshot.gate_results
        ],
    }


def _run_validate_command(run_id_raw: str, profile_name: str, *, factory_home: Path) -> int:
    try:
        run_id = _parse_run_id(run_id_raw)
        db_path = resolve_state_db(factory_home)
        if not db_path.exists():
            print(f"error: state database not found at {db_path}", file=sys.stderr)
            return _EXIT_NOT_FOUND
        environment = _ValidateEnvironment(
            db_path=db_path,
            factory_home=factory_home,
            git_executable=_resolve_git_executable(),
            uv_executable=_resolve_uv_executable(),
        )
        snapshot = asyncio.run(_run_validate_async(run_id, profile_name, environment))
    except RunNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_NOT_FOUND
    except (ArtifactError, ValidationError, ValueError, WorkspaceError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    print(json.dumps(_snapshot_summary(snapshot), indent=2, sort_keys=True))
    return _EXIT_VALID if snapshot.status is GateStatus.PASSED else _EXIT_INVALID


def _discover_workspace_paths(factory_home: Path, run_id: RunId) -> tuple[Path, ...]:
    root = _canonical_cli_directory(factory_home, "factory home") / _WORKTREE_DIR_NAME
    if not root.exists():
        return ()
    _assert_real_directory(root, "worktree root")
    candidates: list[Path] = []
    for repository_dir in _bounded_real_directories(root, "repository directory"):
        run_dir = repository_dir / run_id.value
        if not run_dir.exists():
            continue
        _assert_real_directory(run_dir, "run directory")
        candidates.extend(_bounded_real_directories(run_dir, "task workspace"))
    return tuple(sorted(candidates))


def _bounded_real_directories(path: Path, label: str) -> tuple[Path, ...]:
    entries = tuple(sorted(path.iterdir(), key=lambda item: item.name))
    if len(entries) > _MAX_WORKSPACE_DISCOVERY_ENTRIES:
        raise WorkspaceError(f"too many entries while reading {label}")
    directories: list[Path] = []
    for entry in entries:
        _assert_real_directory(entry, label)
        directories.append(entry)
    return tuple(directories)


def _assert_real_directory(path: Path, label: str) -> None:
    try:
        path_stat = os.lstat(path)
    except OSError as error:
        raise WorkspaceError(f"cannot inspect {label}") from error
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise WorkspaceError(f"{label} contains an unsafe entry")


def _canonical_cli_directory(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise WorkspaceError(f"{label} must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            if stat.S_ISLNK(os.lstat(current).st_mode):
                raise WorkspaceError(f"{label} contains a symlink")
        except OSError as error:
            raise WorkspaceError(f"cannot inspect {label}") from error
    try:
        resolved = path.resolve(strict=True)
        if not stat.S_ISDIR(os.lstat(resolved).st_mode):
            raise WorkspaceError(f"{label} is not a directory")
    except OSError as error:
        raise WorkspaceError(f"cannot resolve {label}") from error
    return resolved


def _parse_task_id(raw: str) -> TaskId:
    return TaskId(raw)


def _run_controlled_git(
    executable: Path, cwd: Path, args: tuple[str, ...]
) -> subprocess.CompletedProcess[str]:
    argv = [str(executable), "-c", _GIT_HOOKS_CONFIG, *args]
    process = subprocess.Popen(  # noqa: S603 - fixed Git executable and argv, no shell
        argv,
        cwd=cwd,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_PAGER": "cat",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=False,
        start_new_session=True,
    )
    if process.stdout is None:
        _terminate_git_process(process)
        raise WorkspaceError("Git inspection pipe was not created")
    output = bytearray()
    deadline = time.monotonic() + _GIT_INSPECT_TIMEOUT_SECONDS
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_git_process(process)
                raise WorkspaceError("Git inspection timed out")
            events = selector.select(min(remaining, 0.1))
            if not events:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(process.stdout.fileno(), _GIT_READ_CHUNK_BYTES)
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > _MAX_GIT_OUTPUT_BYTES:
                _terminate_git_process(process)
                raise WorkspaceError("Git inspection output limit exceeded")
        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
    except subprocess.TimeoutExpired as error:
        _terminate_git_process(process)
        raise WorkspaceError("Git inspection timed out") from error
    finally:
        selector.close()
        process.stdout.close()
    return subprocess.CompletedProcess(
        argv,
        returncode,
        output.decode("utf-8", errors="replace"),
        "",
    )


def _terminate_git_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        if process.poll() is None:
            process.kill()
    if process.poll() is not None:
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()


def _read_only_git(executable: Path, cwd: Path, args: tuple[str, ...]) -> str:
    completed = _run_controlled_git(executable, cwd, args)
    if completed.returncode != 0:
        raise WorkspaceError(f"Git inspection failed: {args[0]}")
    value = completed.stdout.strip()
    if not value:
        raise WorkspaceError(f"Git inspection returned empty output: {args[0]}")
    return value


def _git_diff_output(
    executable: Path,
    cwd: Path,
    args: tuple[str, ...],
    *,
    diff_check: bool = False,
) -> str:
    """Read-only ``git diff`` variant that tolerates empty or non-zero output.

    ``git diff --check`` legitimately exits non-zero when it reports a
    whitespace or conflict-marker error, and an empty diff is a valid (if
    suspicious) outcome the caller decides how to treat — unlike
    ``_read_only_git``, which is reserved for identity probes that must
    always succeed with non-empty output.
    """
    completed = _run_controlled_git(executable, cwd, args)
    if diff_check and completed.returncode == 1:
        return completed.stdout or "git diff --check reported a violation"
    if completed.returncode != 0:
        raise WorkspaceError(f"Git inspection failed: {args[0]}")
    return completed.stdout


def _git_output(
    executable: Path,
    cwd: Path,
    args: tuple[str, ...],
    *,
    label: str,
) -> str:
    completed = _run_controlled_git(executable, cwd, args)
    if completed.returncode != 0:
        raise WorkspaceError(f"Git inspection failed: {label}")
    return completed.stdout.rstrip("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aif", description="AI Software Factory CLI")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command")

    doctor = subcommands.add_parser("doctor", help="Run offline environment diagnostics")
    doctor.add_argument(
        "--json", action="store_true", required=True, help="Emit diagnostics as JSON"
    )

    spec = subcommands.add_parser("spec", help="SPEC file operations")
    spec_sub = spec.add_subparsers(dest="spec_command")
    validate = spec_sub.add_parser("validate", help="Validate a SPEC file")
    validate.add_argument("path", type=Path, help="Path to the SPEC Markdown file")
    validate.add_argument("--task", type=str, default=None, help="Select a single task by ID")
    validate.add_argument("--json", action="store_true", default=False, help="Emit result as JSON")

    status = subcommands.add_parser("status", help="Show persisted run status (read-only)")
    status.add_argument("run_id", type=str, help="Run identifier (run-xxxxxxxxxxxx)")
    status.add_argument(
        "--json",
        action="store_true",
        required=True,
        help="Emit status as canonical JSON",
    )

    events = subcommands.add_parser(
        "events",
        help="Export run events as deterministic NDJSON (derived from ledger)",
    )
    events.add_argument("run_id", type=str, help="Run identifier (run-xxxxxxxxxxxx)")

    workspace = subcommands.add_parser("workspace", help="Inspect isolated task workspaces")
    workspace_sub = workspace.add_subparsers(dest="workspace_command")
    inspect = workspace_sub.add_parser("inspect", help="Inspect workspaces for one run")
    inspect.add_argument("run_id", type=str, help="Run identifier (run-xxxxxxxxxxxx)")

    validate = subcommands.add_parser(
        "validate", help="Run deterministic validation gates and persist a snapshot"
    )
    validate.add_argument("run_id", type=str, help="Run identifier (run-xxxxxxxxxxxx)")
    validate.add_argument(
        "--profile", type=str, required=True, help="Registered validation profile name"
    )

    return parser


def _dispatch(args: argparse.Namespace, factory_home: Path) -> int | None:
    result: int | None = None
    if args.command == "doctor":
        report = build_doctor_report(default_probes())
        print(json.dumps(report, indent=2, sort_keys=True))
        result = 0
    elif args.command == "spec":
        if args.spec_command == "validate":
            result = _run_spec_validate(args.path, args.task, args.json)
    elif args.command == "status":
        result = _run_status_command(args.run_id, as_json=args.json, factory_home=factory_home)
    elif args.command == "events":
        result = _run_events_command(args.run_id, factory_home=factory_home)
    elif args.command == "workspace":
        if args.workspace_command == "inspect":
            result = _run_workspace_inspect_command(args.run_id, factory_home=factory_home)
    elif args.command == "validate":
        result = _run_validate_command(args.run_id, args.profile, factory_home=factory_home)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        Settings.load(None)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    factory_home = resolve_factory_home()
    result = _dispatch(args, factory_home)
    if result is not None:
        return result
    if args.command == "spec":
        parser.parse_args(["spec", "--help"])
        return 1
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised via the installed console script
    raise SystemExit(main())
