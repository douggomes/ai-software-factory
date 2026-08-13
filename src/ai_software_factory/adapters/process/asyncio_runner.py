"""Secure asyncio subprocess adapter.

This adapter is deliberately small and fail-closed: it uses exec-style argv,
never inherits the caller environment, validates canonical paths before spawn,
redacts stream data before it can become an artifact, and terminates the
whole process group on timeout or cancellation.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
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
from ai_software_factory.ports.output_sanitization import (
    OutputSanitizationError,
    OutputSanitizer,
    OutputSanitizerFactory,
)
from ai_software_factory.ports.processes import (
    ProcessArtifactError,
    ProcessExecutionError,
    ProcessIsolationError,
    ProcessPolicyError,
    ProcessRunner,
)

_STREAM_CHUNK_BYTES: Final[int] = 32_768
_DEFAULT_ARTIFACT_PREFIX: Final[str] = "process"


class _StreamCapture:
    """Read one pipe to completion while keeping only bounded safe bytes."""

    def __init__(self, sanitizer: OutputSanitizer) -> None:
        self._sanitizer = sanitizer
        self._data = b""

    @property
    def truncated(self) -> bool:
        return self._sanitizer.truncated

    @property
    def data(self) -> bytes:
        return self._data

    async def read(self, stream: asyncio.StreamReader) -> None:
        while True:
            chunk = await stream.read(_STREAM_CHUNK_BYTES)
            if not chunk:
                break
            self._sanitizer.feed(chunk)
        self._data = self._sanitizer.finish()


class AsyncioProcessRunner(ProcessRunner):
    """ProcessRunner implementation backed by ``asyncio`` and POSIX groups."""

    def __init__(
        self,
        artifact_store: ArtifactStore | None = None,
        *,
        sanitizer_factory: OutputSanitizerFactory,
    ) -> None:
        self._artifact_store = artifact_store
        self._sanitizer_factory = sanitizer_factory

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Validate, execute and persist a bounded process result.

        Raises ``ProcessPolicyError`` before spawning when any path or
        environment rule fails, and ``ProcessIsolationError`` for every
        untrusted execution because this adapter is restricted to the host.
        ``asyncio.CancelledError`` is re-raised after the process group is
        terminated and its output readers are drained.
        """
        executable, cwd = _authorize_request(request)
        if request.trust_profile is TrustProfile.UNTRUSTED:
            raise ProcessIsolationError(
                "untrusted process execution requires approved strong isolation"
            )
        environment = _build_environment(request)
        secrets = _secret_bytes(request.environment, request.redaction_secrets)
        try:
            captures = (
                _StreamCapture(self._sanitizer_factory(request.max_output_bytes, secrets)),
                _StreamCapture(self._sanitizer_factory(request.max_output_bytes, secrets)),
            )
        except OutputSanitizationError as error:
            raise ProcessArtifactError("process output policy could not be initialized") from error
        runtime_root = Path(tempfile.mkdtemp(prefix="aif-process-"))
        _secure_runtime_directories(runtime_root)
        environment.update(_runtime_environment(runtime_root))

        process: asyncio.subprocess.Process | None = None
        reader_tasks: tuple[asyncio.Task[None], asyncio.Task[None]] | None = None
        started_at = time.monotonic()
        timed_out = False
        cwd_fd = -1
        executable_fd = -1
        try:
            cwd_fd = _open_directory_descriptor(cwd)
            executable_fd = _open_executable_descriptor(executable)
            retained_executable = _materialize_executable(
                executable_fd,
                runtime_root,
                request.policy.max_executable_bytes,
            )
            os.close(executable_fd)
            executable_fd = -1
            process = await asyncio.create_subprocess_exec(
                *request.argv,
                executable=str(retained_executable),
                cwd=None,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name == "posix"),
                preexec_fn=_child_initializer(request, cwd_fd),
                pass_fds=(cwd_fd,),
            )
            os.close(cwd_fd)
            cwd_fd = -1
            if process.stdout is None or process.stderr is None:
                raise ProcessExecutionError("subprocess pipes were not created")
            reader_tasks = (
                asyncio.create_task(captures[0].read(process.stdout)),
                asyncio.create_task(captures[1].read(process.stderr)),
            )
            timed_out = await _wait_for_process_and_output(
                process,
                reader_tasks,
                request.timeout_seconds,
                request.termination_grace_seconds,
            )

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
        except OutputSanitizationError as error:
            if process is not None:
                await _terminate_process_group(process, request.termination_grace_seconds)
            raise ProcessArtifactError("process output could not be sanitized") from error
        finally:
            if cwd_fd >= 0:
                os.close(cwd_fd)
            if executable_fd >= 0:
                os.close(executable_fd)
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
        except (ArtifactError, OSError, OutputSanitizationError, ValueError) as error:
            raise ProcessArtifactError("sanitized process output could not be stored") from error
        return stdout.ref, stderr.ref


async def _wait_for_process_and_output(
    process: asyncio.subprocess.Process,
    reader_tasks: tuple[asyncio.Task[None], asyncio.Task[None]],
    timeout_seconds: float,
    termination_grace_seconds: float,
) -> bool:
    """Terminate promptly on timeout, cancellation or sanitizer/read failure."""
    process_task = asyncio.create_task(process.wait())
    tasks = (process_task, *reader_tasks)
    try:
        done, pending = await asyncio.wait(
            tasks,
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_EXCEPTION,
        )
        failed = tuple(
            task for task in done if not task.cancelled() and task.exception() is not None
        )
        if failed:
            await _terminate_process_group(process, termination_grace_seconds)
            await asyncio.gather(*tasks, return_exceptions=True)
            failed[0].result()
            raise ProcessExecutionError("process output reader failed without an error")
        if pending:
            await _terminate_process_group(process, termination_grace_seconds)
            await asyncio.gather(*tasks, return_exceptions=False)
            return True
        await asyncio.gather(*tasks, return_exceptions=False)
        return False
    except asyncio.CancelledError:
        await _terminate_process_group(process, termination_grace_seconds)
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    finally:
        if not process_task.done():
            process_task.cancel()
            await asyncio.gather(process_task, return_exceptions=True)


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


def _open_directory_descriptor(path: Path) -> int:
    if os.name != "posix":
        raise ProcessPolicyError("secure cwd descriptors require POSIX")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd: int | None = None
    try:
        current_fd = os.open(path.anchor, flags)
        for part in path.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except OSError as error:
        if current_fd is not None:
            with contextlib.suppress(OSError):
                os.close(current_fd)
        raise ProcessPolicyError("cannot retain cwd identity") from error


def _open_executable_descriptor(path: Path) -> int:
    """Retain the exact authorized executable inode for private materialization."""
    if os.name != "posix":
        raise ProcessPolicyError("secure executable descriptors require POSIX")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = -1
    try:
        fd = os.open(path, flags)
        descriptor_stat = os.fstat(fd)
        path_stat = os.lstat(path)
    except OSError as error:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        raise ProcessPolicyError("cannot retain executable identity") from error
    if not stat.S_ISREG(descriptor_stat.st_mode) or (
        descriptor_stat.st_dev,
        descriptor_stat.st_ino,
    ) != (path_stat.st_dev, path_stat.st_ino):
        os.close(fd)
        raise ProcessPolicyError("executable identity changed before spawn")
    return fd


def _materialize_executable(
    source_fd: int,
    runtime_root: Path,
    max_bytes: int,
) -> Path:
    """Copy the retained executable into the private per-process runtime."""
    source_stat = os.fstat(source_fd)
    if source_stat.st_size > max_bytes:
        raise ProcessPolicyError("authorized executable exceeds the copy policy")
    expected_identity = _executable_identity(source_stat)
    expected_digest = _hash_executable(source_fd, source_stat.st_size)
    if _executable_identity(os.fstat(source_fd)) != expected_identity:
        raise ProcessPolicyError("authorized executable changed while hashing")
    destination = runtime_root / "executable"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    destination_fd = -1
    try:
        destination_fd = os.open(destination, flags, 0o500)
        copied_digest = _copy_executable_bytes(source_fd, destination_fd, source_stat.st_size)
        os.fsync(destination_fd)
    except OSError as error:
        raise ProcessPolicyError("authorized executable could not be retained") from error
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
    if (
        copied_digest != expected_digest
        or _executable_identity(os.fstat(source_fd)) != expected_identity
    ):
        raise ProcessPolicyError("authorized executable changed while copying")
    return destination


def _hash_executable(source_fd: int, size: int) -> str:
    os.lseek(source_fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = os.read(source_fd, min(_STREAM_CHUNK_BYTES, remaining))
        if not chunk:
            raise ProcessPolicyError("authorized executable changed while hashing")
        digest.update(chunk)
        remaining -= len(chunk)
    if os.read(source_fd, 1):
        raise ProcessPolicyError("authorized executable changed while hashing")
    return digest.hexdigest()


def _copy_executable_bytes(source_fd: int, destination_fd: int, size: int) -> str:
    os.lseek(source_fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = os.read(source_fd, min(_STREAM_CHUNK_BYTES, remaining))
        if not chunk:
            raise ProcessPolicyError("authorized executable changed while copying")
        digest.update(chunk)
        _write_all(destination_fd, chunk)
        remaining -= len(chunk)
    if os.read(source_fd, 1):
        raise ProcessPolicyError("authorized executable changed while copying")
    return digest.hexdigest()


def _executable_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise ProcessPolicyError("authorized executable could not be retained")
        offset += written


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
    _send_process_signal(process, signal_module.SIGTERM)
    if os.name == "posix":
        await asyncio.sleep(grace_seconds)
        if _process_group_exists(process.pid):
            _send_process_signal(process, signal_module.SIGKILL)
        await process.wait()
        return
    try:
        await asyncio.wait_for(process.wait(), grace_seconds)
    except TimeoutError:
        _send_process_signal(process, signal_module.SIGKILL)
        await process.wait()


def _send_process_signal(process: asyncio.subprocess.Process, signum: int) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            return
        except OSError as error:
            raise ProcessExecutionError("could not signal process group") from error
    else:
        if process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            if signum == signal_module.SIGKILL:
                process.kill()
            else:
                process.terminate()


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _child_initializer(request: ProcessRequest, cwd_fd: int) -> Callable[[], None] | None:
    if os.name != "posix":
        return None

    def apply_limits() -> None:
        os.fchdir(cwd_fd)
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
