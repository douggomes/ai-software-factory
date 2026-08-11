"""Secure asyncio subprocess adapter.

This adapter is deliberately small and fail-closed: it uses exec-style argv,
never inherits the caller environment, validates canonical paths before spawn,
redacts stream data before it can become an artifact, and terminates the
whole process group on timeout or cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import resource
import shutil
import signal as signal_module
import stat
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Final

from ai_software_factory.core.process_models import (
    ArtifactReference,
    ProcessRequest,
    ProcessResult,
    TrustProfile,
)
from ai_software_factory.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    ArtifactRef,
    ArtifactStore,
)
from ai_software_factory.ports.processes import (
    ProcessArtifactError,
    ProcessExecutionError,
    ProcessIsolationError,
    ProcessPolicyError,
    ProcessRunner,
)

_STREAM_CHUNK_BYTES: Final[int] = 32_768
_REDACTION_MARKER: Final[bytes] = b"<REDACTED>"
_ASSIGNMENT_SECRET_PATTERN: Final[re.Pattern[bytes]] = re.compile(
    rb"(?i)\b(password|passwd|secret|token|api[_-]?key)\b(\s*[:=]\s*)[^\s,;]+"
)
_DEFAULT_ARTIFACT_PREFIX: Final[str] = "process"


class _StreamCapture:
    """Read one pipe to completion while keeping only bounded safe bytes."""

    def __init__(self, max_bytes: int, secrets: Iterable[bytes]) -> None:
        self._max_bytes = max_bytes
        self._buffer = bytearray()
        self._truncated = False
        self._secrets = tuple(
            sorted((secret for secret in secrets if secret), key=len, reverse=True)
        )
        self._pending = b""
        self._pending_limit = max((len(secret) for secret in self._secrets), default=1) - 1

    @property
    def truncated(self) -> bool:
        return self._truncated

    @property
    def data(self) -> bytes:
        return bytes(self._buffer)

    async def read(self, stream: asyncio.StreamReader) -> None:
        while True:
            chunk = await stream.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            self._append(self._redact_incremental(chunk, final=False))
        self._append(self._redact_incremental(b"", final=True))

    def _redact_incremental(self, chunk: bytes, *, final: bool) -> bytes:
        data = self._pending + chunk
        redacted = _redact_bytes(data, self._secrets)
        if final or self._pending_limit == 0:
            self._pending = b""
            return redacted
        split_at = max(0, len(redacted) - self._pending_limit)
        self._pending = redacted[split_at:]
        return redacted[:split_at]

    def _append(self, data: bytes) -> None:
        if not data:
            return
        remaining = self._max_bytes - len(self._buffer)
        if remaining <= 0:
            self._truncated = True
            return
        if len(data) > remaining:
            self._buffer.extend(data[:remaining])
            self._truncated = True
            return
        self._buffer.extend(data)


class AsyncioProcessRunner(ProcessRunner):
    """ProcessRunner implementation backed by ``asyncio`` and POSIX groups."""

    def __init__(self, artifact_store: ArtifactStore | None = None) -> None:
        self._artifact_store = artifact_store

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Validate, execute and persist a bounded process result.

        Raises ``ProcessPolicyError`` before spawning when any path or
        environment rule fails, and ``ProcessIsolationError`` for untrusted
        execution without an explicit strong-isolation capability.
        ``asyncio.CancelledError`` is re-raised after the process group is
        terminated and its output readers are drained.
        """
        executable, cwd = _authorize_request(request)
        if request.trust_profile is TrustProfile.UNTRUSTED and not _isolation_available(request):
            raise ProcessIsolationError(
                "untrusted process execution requires approved strong isolation"
            )
        environment = _build_environment(request)
        secrets = _secret_bytes(request.environment, request.redaction_secrets)
        runtime_root = Path(tempfile.mkdtemp(prefix="aif-process-"))
        _secure_runtime_directories(runtime_root)
        environment.update(_runtime_environment(runtime_root))

        process: asyncio.subprocess.Process | None = None
        captures: tuple[_StreamCapture, _StreamCapture] | None = None
        reader_tasks: tuple[asyncio.Task[None], asyncio.Task[None]] | None = None
        started_at = time.monotonic()
        timed_out = False
        try:
            process = await asyncio.create_subprocess_exec(
                *request.argv,
                executable=str(executable),
                cwd=str(cwd),
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
                preexec_fn=_resource_limit_initializer(request),
            )
            if process.stdout is None or process.stderr is None:
                raise ProcessExecutionError("subprocess pipes were not created")
            captures = (
                _StreamCapture(request.max_output_bytes, secrets),
                _StreamCapture(request.max_output_bytes, secrets),
            )
            reader_tasks = (
                asyncio.create_task(captures[0].read(process.stdout)),
                asyncio.create_task(captures[1].read(process.stderr)),
            )
            try:
                await asyncio.wait_for(process.wait(), request.timeout_seconds)
            except TimeoutError:
                timed_out = True
                await _terminate_process_group(process, request.termination_grace_seconds)
            except asyncio.CancelledError:
                await _terminate_process_group(process, request.termination_grace_seconds)
                raise
            finally:
                await asyncio.gather(*reader_tasks, return_exceptions=False)

            exit_code, termination_signal = _termination_status(process.returncode)
            stdout_ref, stderr_ref = self._persist_output(request, captures)
            return ProcessResult(
                exit_code=exit_code,
                signal=termination_signal,
                duration_seconds=time.monotonic() - started_at,
                truncated=captures[0].truncated or captures[1].truncated,
                timed_out=timed_out,
                stdout_ref=stdout_ref,
                stderr_ref=stderr_ref,
            )
        finally:
            if reader_tasks is not None and any(not task.done() for task in reader_tasks):
                for task in reader_tasks:
                    task.cancel()
                await asyncio.gather(*reader_tasks, return_exceptions=True)
            shutil.rmtree(runtime_root)

    def _persist_output(
        self,
        request: ProcessRequest,
        captures: tuple[_StreamCapture, _StreamCapture],
    ) -> tuple[ArtifactReference | None, ArtifactReference | None]:
        if self._artifact_store is None or request.run_id is None:
            return None, None
        artifact_token = (
            request.attempt_id.value if request.attempt_id is not None else uuid.uuid4().hex
        )
        try:
            stdout = self._artifact_store.put(
                ArtifactRef(
                    run_id=request.run_id,
                    relative_path=f"{_DEFAULT_ARTIFACT_PREFIX}/{artifact_token}/stdout.bin",
                    kind=ArtifactKind.OTHER,
                ),
                captures[0].data,
            )
            stderr = self._artifact_store.put(
                ArtifactRef(
                    run_id=request.run_id,
                    relative_path=f"{_DEFAULT_ARTIFACT_PREFIX}/{artifact_token}/stderr.bin",
                    kind=ArtifactKind.OTHER,
                ),
                captures[1].data,
            )
        except (ArtifactError, OSError, ValueError) as error:
            raise ProcessArtifactError("sanitized process output could not be stored") from error
        return stdout.ref, stderr.ref


def _authorize_request(request: ProcessRequest) -> tuple[Path, Path]:
    executable = request.executable or Path(request.argv[0])
    if str(executable) != request.argv[0]:
        raise ProcessPolicyError("argv[0] must exactly match the authorized executable")
    executable_path = _canonical_regular_file(executable, "executable")
    cwd_path = _canonical_directory(request.cwd, "cwd")
    allowed_executables = tuple(
        _canonical_regular_file(path, "allowed executable")
        for path in request.policy.allowed_executables
    )
    if executable_path not in allowed_executables:
        raise ProcessPolicyError(f"executable is outside policy: {executable_path}")
    allowed_roots = tuple(
        _canonical_directory(path, "allowed cwd root") for path in request.policy.allowed_cwd_roots
    )
    if not any(_is_within(cwd_path, root) for root in allowed_roots):
        raise ProcessPolicyError(f"cwd is outside policy: {cwd_path}")
    return executable_path, cwd_path


def _canonical_regular_file(path: Path, label: str) -> Path:
    candidate = _canonical_path(path, label)
    try:
        file_stat = os.lstat(candidate)
    except OSError as error:
        raise ProcessPolicyError(f"cannot inspect {label}") from error
    if not stat.S_ISREG(file_stat.st_mode) or not os.access(candidate, os.X_OK):
        raise ProcessPolicyError(f"{label} is not an executable regular file")
    return candidate


def _canonical_directory(path: Path, label: str) -> Path:
    candidate = _canonical_path(path, label)
    try:
        directory_stat = os.lstat(candidate)
    except OSError as error:
        raise ProcessPolicyError(f"cannot inspect {label}") from error
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ProcessPolicyError(f"{label} is not a directory")
    return candidate


def _canonical_path(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ProcessPolicyError(f"{label} must be absolute")
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            current_stat = os.lstat(current)
        except OSError as error:
            raise ProcessPolicyError(f"cannot inspect {label}") from error
        if stat.S_ISLNK(current_stat.st_mode):
            raise ProcessPolicyError(f"{label} cannot contain symlinks")
    try:
        return path.resolve(strict=True)
    except OSError as error:
        raise ProcessPolicyError(f"cannot resolve {label}") from error


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _isolation_available(request: ProcessRequest) -> bool:
    if request.isolation_available is not None:
        return request.isolation_available
    return request.policy.isolation_available


def _build_environment(request: ProcessRequest) -> dict[str, str]:
    allowed = request.policy.environment_allowlist
    unknown = sorted(set(request.environment) - allowed)
    if unknown:
        raise ProcessPolicyError(f"environment keys outside policy: {', '.join(unknown)}")
    environment = {"PATH": request.policy.controlled_path}
    environment.update(
        {key: request.environment[key] for key in sorted(allowed) if key in request.environment}
    )
    return environment


def _secure_runtime_directories(root: Path) -> None:
    os.chmod(root, 0o700)
    for name in ("home", "tmp"):
        directory = root / name
        directory.mkdir(mode=0o700)
        os.chmod(directory, 0o700)


def _runtime_environment(root: Path) -> Mapping[str, str]:
    home = str(root / "home")
    tmp = str(root / "tmp")
    return {"HOME": home, "TMPDIR": tmp, "TMP": tmp, "TEMP": tmp}


def _secret_bytes(environment: Mapping[str, str], explicit: Iterable[str]) -> tuple[bytes, ...]:
    values = set(environment.values())
    values.update(explicit)
    return tuple(value.encode("utf-8") for value in values if value)


def _redact_bytes(data: bytes, secrets: tuple[bytes, ...]) -> bytes:
    redacted = data
    for secret in secrets:
        redacted = redacted.replace(secret, _REDACTION_MARKER)
    return _ASSIGNMENT_SECRET_PATTERN.sub(rb"\1\2" + _REDACTION_MARKER, redacted)


def _termination_status(returncode: int | None) -> tuple[int | None, int | None]:
    if returncode is None:
        raise ProcessExecutionError("process ended without a return code")
    if returncode < 0:
        return None, -returncode
    return returncode, None


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
    grace_seconds: float,
) -> None:
    if process.returncode is not None:
        return
    _send_process_signal(process, signal_module.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), grace_seconds)
        return
    except TimeoutError:
        _send_process_signal(process, signal_module.SIGKILL)
        await process.wait()


def _send_process_signal(process: asyncio.subprocess.Process, signum: int) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        except OSError as error:
            raise ProcessExecutionError("could not signal process group") from error
    else:
        with contextlib.suppress(ProcessLookupError):
            if signum == signal_module.SIGKILL:
                process.kill()
            else:
                process.terminate()


def _resource_limit_initializer(request: ProcessRequest) -> Callable[[], None] | None:
    if os.name != "posix":
        return None
    if (
        request.max_processes is None
        and request.max_memory_bytes is None
        and request.max_cpu_seconds is None
    ):
        return None

    def apply_limits() -> None:
        if request.max_cpu_seconds is not None:
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (request.max_cpu_seconds, request.max_cpu_seconds),
            )
        if request.max_memory_bytes is not None:
            resource.setrlimit(
                resource.RLIMIT_AS,
                (request.max_memory_bytes, request.max_memory_bytes),
            )
        if request.max_processes is not None and hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(
                resource.RLIMIT_NPROC,
                (request.max_processes, request.max_processes),
            )

    return apply_limits
