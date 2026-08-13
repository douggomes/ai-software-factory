"""``aif`` command-line entry point.

Offline, read-only and local commands live here: version, diagnostics
(``doctor``), SPEC validation (``spec validate``), run status and event
export. No command in this module invokes a provider or performs a network
call beyond local filesystem/SQLite access.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ai_software_factory import __version__
from ai_software_factory.adapters.git.worktrees import GitWorktreeManager
from ai_software_factory.adapters.isolation.oci import (
    DockerIsolationBackend,
    OciIsolationPolicy,
    OciIsolationRunner,
    PodmanIsolationBackend,
    SnapshotRootAuthorizer,
)
from ai_software_factory.adapters.persistence.artifact_store import (
    FilesystemArtifactStore,
    SqliteEventLogReader,
)
from ai_software_factory.adapters.persistence.sqlite import SQLiteRunStore
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.application.queries import (
    RunEventsQuery,
    RunStatusQuery,
    format_events_ndjson,
    format_run_status_json,
)
from ai_software_factory.application.spec_parser import SpecParseError, SpecParser
from ai_software_factory.application.spec_validator import SpecValidator
from ai_software_factory.config import ConfigError, IsolationSettings, Settings
from ai_software_factory.core.evaluation_workspace import EvaluationSnapshot
from ai_software_factory.core.ids import RunId, TaskId
from ai_software_factory.core.spec_models import (
    SoftwareSpec,
    ValidationReport,
    canonical_json,
)
from ai_software_factory.core.workspace_models import Workspace, WorkspaceSnapshot
from ai_software_factory.ports.persistence import RunNotFoundError
from ai_software_factory.ports.processes import IsolationBackend, ProcessRunner
from ai_software_factory.ports.workspace import WorkspaceError

#: Executable name probed for each supported worker/reviewer CLI. Presence is
#: checked with ``shutil.which`` only; the executable is never invoked.
PROVIDER_EXECUTABLES: Final[Mapping[str, str]] = {
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
}
_APPROVED_OCI_RUNTIMES: Final[Mapping[str, tuple[Path, ...]]] = {
    "docker": (
        Path("/Applications/Docker.app/Contents/Resources/bin/docker"),
        Path("/opt/homebrew/bin/docker"),
        Path("/usr/local/bin/docker"),
    ),
    "podman": (Path("/opt/homebrew/bin/podman"), Path("/usr/local/bin/podman")),
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
_GIT_HOOKS_CONFIG: Final[str] = "core.hooksPath=/dev/null"
_GIT_INSPECT_TIMEOUT_SECONDS: Final[float] = 5.0
_MAX_WORKSPACE_DISCOVERY_ENTRIES: Final[int] = 256


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
    isolation_probe: Callable[[IsolationSettings], dict[str, str | None]] = field(
        default=lambda settings: {
            "status": "disabled" if settings.backend == "disabled" else "incompatible",
            "backend": None if settings.backend == "disabled" else settings.backend,
            "image": settings.image,
        }
    )


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


def probe_isolation(settings: IsolationSettings) -> dict[str, str | None]:
    """Report isolation configuration without probing, pulling or building a runtime."""
    if settings.backend == "disabled":
        return {"status": "disabled", "backend": None, "image": None}
    runtime = _find_approved_oci_runtime(settings.backend)
    return {
        "status": "available" if runtime is not None else "incompatible",
        "backend": settings.backend,
        "image": settings.image,
    }


def build_isolation_backend(
    settings: IsolationSettings,
    runtime_lookup: Callable[[str], str | None] | None = None,
) -> IsolationBackend | None:
    """Composition-root registration for the configured local OCI backend.

    A missing executable is an explicit configuration failure. The caller that
    later receives this backend still has to acquire a fresh material
    capability, so this function cannot turn an untrusted request into host
    execution.
    """
    if settings.backend == "disabled":
        return None
    lookup = _find_approved_oci_runtime if runtime_lookup is None else runtime_lookup
    runtime = lookup(settings.backend)
    if runtime is None or settings.image is None:
        raise ConfigError("runtime OCI configurado não está disponível")
    policy = OciIsolationPolicy(
        backend=settings.backend,
        image=settings.image,
        runtime=Path(runtime).resolve(strict=True),
    )
    registry: Mapping[str, type[IsolationBackend]] = {
        "docker": DockerIsolationBackend,
        "podman": PodmanIsolationBackend,
    }
    return registry[settings.backend](policy)


def build_validation_process_runner(
    settings: IsolationSettings,
    snapshot: EvaluationSnapshot,
    host_runner: ProcessRunner,
    runtime_lookup: Callable[[str], str | None] | None = None,
) -> ProcessRunner:
    """Compose the OCI adapter around host orchestration for one verified snapshot.

    There is deliberately no host fallback: a disabled or incompatible
    isolation configuration returns a runner that continues to reject every
    untrusted request. The caller can use this composition only after TASK-035
    supplied its verified snapshot capability.
    """
    backend = build_isolation_backend(settings, runtime_lookup)
    if backend is None:
        return host_runner
    return OciIsolationRunner(host_runner, backend, SnapshotRootAuthorizer(snapshot))


def _find_approved_oci_runtime(backend: str) -> str | None:
    """Find only a canonical runtime installed at an approved local location."""
    for candidate in _APPROVED_OCI_RUNTIMES.get(backend, ()):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved == candidate and resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved)
    return None


def default_probes() -> DoctorProbes:
    return DoctorProbes(
        python_version=lambda: sys.version.split()[0],
        sqlite_version=lambda: sqlite3.sqlite_version,
        tool_probe=probe_tool,
        provider_probe=probe_provider,
        isolation_probe=probe_isolation,
    )


def build_doctor_report(
    probes: DoctorProbes,
    settings: IsolationSettings | None = None,
) -> dict[str, object]:
    """Assemble the deterministic diagnostic report from injected probes."""
    isolation = settings if settings is not None else IsolationSettings()
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
        "isolation": probes.isolation_probe(isolation),
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
            AsyncioProcessRunner(
                artifact_store,
                sanitizer_factory=StreamingOutputSanitizer,
            ),
            artifact_store,
            git_executable,
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


def _read_only_git(executable: Path, cwd: Path, args: tuple[str, ...]) -> str:
    completed = subprocess.run(  # noqa: S603 - fixed Git executable and argv, no shell
        [
            str(executable),
            "-c",
            _GIT_HOOKS_CONFIG,
            *args,
        ],
        cwd=cwd,
        env={
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(cwd),
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        timeout=_GIT_INSPECT_TIMEOUT_SECONDS,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise WorkspaceError(f"Git inspection failed: {args[0]}")
    value = completed.stdout.strip()
    if not value:
        raise WorkspaceError(f"Git inspection returned empty output: {args[0]}")
    return value


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

    return parser


def _dispatch(args: argparse.Namespace, factory_home: Path, settings: Settings) -> int | None:
    result: int | None = None
    if args.command == "doctor":
        report = build_doctor_report(default_probes(), settings.isolation)
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
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        settings = Settings.load(None)
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_INVALID
    factory_home = resolve_factory_home()
    result = _dispatch(args, factory_home, settings)
    if result is not None:
        return result
    if args.command == "spec":
        parser.parse_args(["spec", "--help"])
        return 1
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised via the installed console script
    raise SystemExit(main())
