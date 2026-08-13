"""OCI runtime boundary that only mounts verified private snapshots.

The runtime command is trusted orchestration; the command *inside* its OCI
container is untrusted.  This adapter never creates a host fallback, pull, or
build path.  Every invocation receives a fresh capability from a local probe
and a fixed policy assembled independently from repository content.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import signal
import stat
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from ai_software_factory.core.evaluation_workspace import EvaluationSnapshot, ManifestEntry
from ai_software_factory.core.process_models import (
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_TIMEOUT_SECONDS,
    ProcessPolicy,
    ProcessRequest,
    ProcessResult,
    TrustProfile,
)
from ai_software_factory.ports.processes import (
    IsolationBackend,
    IsolationCapability,
    IsolationProbeError,
    ProcessExecutionError,
    ProcessIsolationError,
    ProcessPolicyError,
    ProcessRunner,
    SnapshotAuthorizationError,
    SnapshotAuthorizer,
)

_CAPABILITY_TTL_SECONDS: Final[float] = 30.0
_PROBE_TIMEOUT_SECONDS: Final[float] = 5.0
_PROBE_OUTPUT_BYTES: Final[int] = 4096
_PROBE_READ_CHUNK_BYTES: Final[int] = 1024
_IMAGE_OR_CONTEXT_INSPECT_ARGUMENTS: Final[int] = 5
_PODMAN_CONNECTION_INSPECT_ARGUMENTS: Final[int] = 6
_OCI_MAX_CPU: Final[str] = "2"
_OCI_MAX_MEMORY: Final[str] = "2g"
_OCI_MAX_PIDS: Final[str] = "256"
_OCI_USER: Final[str] = "65532:65532"
_CONTAINER_WORKDIR: Final[str] = "/workspace"
_CONTAINER_PATH: Final[str] = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
_IMAGE_DIGEST_MARKER: Final[str] = "@sha256:"
_SHA256_HEX_LENGTH: Final[int] = 64
_OCI_TMPFS: Final[str] = "/tmp:rw,nosuid,nodev,noexec,size=64m"  # noqa: S108
_SAFE_RUNTIME_CONTEXTS: Final[dict[str, str]] = {
    "docker": "desktop-linux",
    "podman": "podman-machine-default",
}
_DOCKER_DESKTOP_SOCKET: Final[Path] = Path.home() / ".docker" / "run" / "docker.sock"
_PODMAN_MACHINE_ENDPOINT: Final[re.Pattern[str]] = re.compile(
    r"^ssh://core@(?:localhost|127\.0\.0\.1|\[::1\]):[1-9][0-9]{3,4}"
    r"/run/user/[1-9][0-9]*/podman/podman\.sock$"
)


@dataclass(frozen=True, slots=True)
class OciProbeResult:
    """Bounded result of one fixed runtime metadata command."""

    returncode: int
    stdout: str


@runtime_checkable
class OciProbeExecutor(Protocol):
    """Small capability for safe local OCI runtime metadata probes."""

    async def execute(self, argv: tuple[str, ...]) -> OciProbeResult:
        """Run one fixed argv without a shell, network action, pull or build."""
        ...


class AsyncioOciProbeExecutor:
    """Bounded executor for local runtime metadata only."""

    async def execute(self, argv: tuple[str, ...]) -> OciProbeResult:
        _validate_probe_argv(argv)
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                env={"PATH": _CONTAINER_PATH},
                start_new_session=(os.name == "posix"),
            )
        except OSError as error:
            raise IsolationProbeError("OCI runtime is unavailable") from error
        try:
            stdout = await asyncio.wait_for(_read_probe_stdout(process), _PROBE_TIMEOUT_SECONDS)
        except _ProbeOutputLimitError as error:
            await _terminate_probe(process)
            raise IsolationProbeError("OCI runtime probe output exceeds policy") from error
        except TimeoutError as error:
            await _terminate_probe(process)
            raise IsolationProbeError("OCI runtime probe timed out") from error
        except asyncio.CancelledError:
            await _terminate_probe(process)
            raise
        try:
            return OciProbeResult(process.returncode or 0, stdout.decode("utf-8", "strict").strip())
        except UnicodeDecodeError as error:
            raise IsolationProbeError("OCI runtime probe output is invalid") from error


async def _terminate_probe(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    else:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await process.wait()


class _ProbeOutputLimitError(ValueError):
    """Internal signal that a metadata probe exceeded its fixed byte budget."""


async def _read_probe_stdout(process: asyncio.subprocess.Process) -> bytes:
    """Read no more than the probe policy permits, then wait for its process."""
    if process.stdout is None:
        raise IsolationProbeError("OCI runtime probe output is unavailable")
    chunks: list[bytes] = []
    remaining = _PROBE_OUTPUT_BYTES
    while True:
        chunk = await process.stdout.read(min(_PROBE_READ_CHUNK_BYTES, remaining + 1))
        if not chunk:
            break
        if len(chunk) > remaining:
            raise _ProbeOutputLimitError
        chunks.append(chunk)
        remaining -= len(chunk)
    await process.wait()
    return b"".join(chunks)


def _validate_probe_argv(argv: tuple[str, ...]) -> None:
    """Permit only read-only OCI metadata commands assembled by this adapter."""
    if (
        not argv
        or not Path(argv[0]).is_absolute()
        or any(not item or "\x00" in item for item in argv)
    ):
        raise IsolationProbeError("OCI probe command is invalid")
    command = argv[1:]
    if command in {
        ("version", "--format", "{{.Server.Version}}"),
        ("context", "show"),
        ("system", "connection", "default"),
    }:
        return
    if command[:2] == ("image", "inspect") and len(command) == _IMAGE_OR_CONTEXT_INSPECT_ARGUMENTS:
        return
    if (
        command[:2] == ("context", "inspect")
        and len(command) == _IMAGE_OR_CONTEXT_INSPECT_ARGUMENTS
    ):
        return
    if (
        command[:3] == ("system", "connection", "inspect")
        and len(command) == _PODMAN_CONNECTION_INSPECT_ARGUMENTS
    ):
        return
    raise IsolationProbeError("OCI probe command is outside the metadata allowlist")


@dataclass(frozen=True, slots=True)
class OciIsolationPolicy:
    """Closed OCI policy. No field grants callers a host mount or network."""

    backend: str
    image: str
    runtime: Path
    timeout_seconds: float = 900.0
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if self.backend not in _SAFE_RUNTIME_CONTEXTS:
            raise IsolationProbeError("OCI backend is unsupported")
        image = self.image
        name, marker, digest = image.partition(_IMAGE_DIGEST_MARKER)
        if not name or marker != _IMAGE_DIGEST_MARKER or len(digest) != _SHA256_HEX_LENGTH:
            raise IsolationProbeError("OCI image must use an immutable digest")
        if any(character not in "0123456789abcdef" for character in digest):
            raise IsolationProbeError("OCI image digest is invalid")
        if not self.runtime.is_absolute():
            raise IsolationProbeError("OCI runtime path must be absolute")
        if self.timeout_seconds <= 0 or self.timeout_seconds > DEFAULT_TIMEOUT_SECONDS:
            raise IsolationProbeError("OCI timeout is outside policy")
        if not 0 < self.max_output_bytes <= DEFAULT_MAX_OUTPUT_BYTES:
            raise IsolationProbeError("OCI output limit is outside policy")

    @property
    def policy_hash(self) -> str:
        fields = (
            self.backend,
            self.image,
            str(self.runtime),
            str(self.timeout_seconds),
            str(self.max_output_bytes),
        )
        payload = "\0".join(fields).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class _IssuedCapability:
    """Backend-private capability; callers can pass it but cannot forge its token."""

    token: str
    expires_at: float
    policy_hash: str
    runtime: Path
    version: str
    context: str
    endpoint: str
    image: str


@dataclass(slots=True)
class _OciRuntimeBackend(IsolationBackend):
    """Common closed OCI mechanics; concrete adapters translate each runtime."""

    policy: OciIsolationPolicy
    probe_executor: OciProbeExecutor = field(default_factory=AsyncioOciProbeExecutor)
    _issued: dict[str, _IssuedCapability] = field(
        default_factory=lambda: dict[str, _IssuedCapability](),
        init=False,
    )

    async def probe(self) -> IsolationCapability:
        runtime = _canonical_runtime(self.policy.runtime)
        version = await self.probe_executor.execute(
            (str(runtime), "version", "--format", "{{.Server.Version}}")
        )
        if version.returncode != 0 or not version.stdout:
            raise IsolationProbeError("OCI runtime version is incompatible")
        context_command = self._context_argv(runtime)
        context = await self.probe_executor.execute(context_command)
        if context.returncode != 0 or context.stdout != _SAFE_RUNTIME_CONTEXTS[self.policy.backend]:
            raise IsolationProbeError("OCI runtime context is not an approved local machine")
        endpoint = await self.probe_executor.execute(self._endpoint_argv(runtime, context.stdout))
        if endpoint.returncode != 0 or not self._is_local_endpoint(endpoint.stdout):
            raise IsolationProbeError("OCI runtime endpoint is remote or incompatible")
        inspect_format = self._image_inspect_format
        image = await self.probe_executor.execute(
            (str(runtime), "image", "inspect", "--format", inspect_format, self.policy.image)
        )
        if image.returncode != 0 or not _image_matches_digest(image.stdout, self.policy.image):
            raise IsolationProbeError("OCI image is absent or does not match the approved digest")
        capability = _IssuedCapability(
            token=uuid.uuid4().hex,
            expires_at=time.monotonic() + _CAPABILITY_TTL_SECONDS,
            policy_hash=self.policy.policy_hash,
            runtime=runtime,
            version=version.stdout,
            context=context.stdout,
            endpoint=endpoint.stdout,
            image=image.stdout,
        )
        self._issued[capability.token] = capability
        return capability

    @property
    def _image_inspect_format(self) -> str:
        raise NotImplementedError

    def _context_argv(self, runtime: Path) -> tuple[str, ...]:
        raise NotImplementedError

    def _endpoint_argv(self, runtime: Path, context: str) -> tuple[str, ...]:
        raise NotImplementedError

    def _is_local_endpoint(self, endpoint: str) -> bool:
        raise NotImplementedError

    def _runtime_prefix(self, capability: _IssuedCapability) -> tuple[str, ...]:
        raise NotImplementedError

    def authorize(self, capability: IsolationCapability) -> IsolationCapability:
        if not isinstance(capability, _IssuedCapability):
            raise IsolationProbeError("OCI isolation capability is not recognized")
        issued = self._issued.pop(capability.token, None)
        if issued != capability or capability.expires_at < time.monotonic():
            raise IsolationProbeError("OCI isolation capability expired or was replaced")
        if (
            capability.policy_hash != self.policy.policy_hash
            or capability.runtime != _canonical_runtime(self.policy.runtime)
            or not capability.version
            or capability.context != _SAFE_RUNTIME_CONTEXTS[self.policy.backend]
            or capability.image != self.policy.image
            or not self._is_local_endpoint(capability.endpoint)
        ):
            raise IsolationProbeError("OCI isolation policy changed after probe")
        return capability

    def build_run_argv(
        self,
        capability: IsolationCapability,
        snapshot_root: Path,
        container_name: str,
        request: ProcessRequest,
    ) -> tuple[str, ...]:
        capability = self._require_capability(capability)
        _validate_container_argv(request.argv)
        return (
            *self._runtime_prefix(capability),
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--user",
            _OCI_USER,
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit",
            _OCI_MAX_PIDS,
            "--cpus",
            _OCI_MAX_CPU,
            "--memory",
            _OCI_MAX_MEMORY,
            "--name",
            container_name,
            "--mount",
            f"type=bind,src={snapshot_root},dst={_CONTAINER_WORKDIR},readonly",
            "--tmpfs",
            _OCI_TMPFS,
            "--env",
            f"PATH={_CONTAINER_PATH}",
            "--env",
            "HOME=/tmp/home",
            "--env",
            "TMPDIR=/tmp",
            "--workdir",
            _CONTAINER_WORKDIR,
            self.policy.image,
            *request.argv,
        )

    def build_cleanup_argv(
        self, capability: IsolationCapability, container_name: str
    ) -> tuple[str, ...]:
        capability = self._require_capability(capability, allow_expired=True)
        return (*self._runtime_prefix(capability), "rm", "--force", container_name)

    def _require_capability(
        self, capability: IsolationCapability, *, allow_expired: bool = False
    ) -> _IssuedCapability:
        if not isinstance(capability, _IssuedCapability):
            raise IsolationProbeError("OCI isolation capability is not recognized")
        if not allow_expired and capability.expires_at < time.monotonic():
            raise IsolationProbeError("OCI isolation capability expired")
        return capability


@dataclass(slots=True)
class DockerIsolationBackend(_OciRuntimeBackend):
    """Docker Desktop translation for the common OCI isolation contract."""

    @property
    def _image_inspect_format(self) -> str:
        return "{{index .RepoDigests 0}}"

    def _context_argv(self, runtime: Path) -> tuple[str, ...]:
        return (str(runtime), "context", "show")

    def _endpoint_argv(self, runtime: Path, context: str) -> tuple[str, ...]:
        return (
            str(runtime),
            "context",
            "inspect",
            context,
            "--format",
            '{{(index .Endpoints "docker").Host}}',
        )

    def _is_local_endpoint(self, endpoint: str) -> bool:
        if not endpoint.startswith("unix://"):
            return False
        return Path(endpoint.removeprefix("unix://")) == _DOCKER_DESKTOP_SOCKET

    def _runtime_prefix(self, capability: _IssuedCapability) -> tuple[str, ...]:
        return (str(capability.runtime), "--host", capability.endpoint)


@dataclass(slots=True)
class PodmanIsolationBackend(_OciRuntimeBackend):
    """Podman machine translation for the common OCI isolation contract."""

    @property
    def _image_inspect_format(self) -> str:
        return "{{.Digest}}"

    def _context_argv(self, runtime: Path) -> tuple[str, ...]:
        return (str(runtime), "system", "connection", "default")

    def _endpoint_argv(self, runtime: Path, context: str) -> tuple[str, ...]:
        return (
            str(runtime),
            "system",
            "connection",
            "inspect",
            context,
            "--format",
            "{{.URI}}",
        )

    def _is_local_endpoint(self, endpoint: str) -> bool:
        return _PODMAN_MACHINE_ENDPOINT.fullmatch(endpoint) is not None

    def _runtime_prefix(self, capability: _IssuedCapability) -> tuple[str, ...]:
        return (str(capability.runtime), "--url", capability.endpoint)


class SnapshotRootAuthorizer(SnapshotAuthorizer):
    """Authorizes exactly one verified Task-035 private snapshot root."""

    def __init__(self, snapshot: EvaluationSnapshot) -> None:
        self._root = _canonical_snapshot_root(snapshot.root)
        self._identity = _directory_identity(self._root)
        self._snapshot_identity = snapshot.identity_hash
        self._entries = snapshot.entries
        if not self._snapshot_identity or not snapshot.manifest_hash:
            raise SnapshotAuthorizationError("snapshot identity is incomplete")

    def authorize(self, requested_cwd: Path) -> Path:
        candidate = _canonical_snapshot_root(requested_cwd)
        if candidate != self._root or _directory_identity(candidate) != self._identity:
            raise SnapshotAuthorizationError(
                "OCI execution must target the authorized snapshot root"
            )
        _verify_snapshot_entries(candidate, self._entries)
        return candidate


class OciIsolationRunner(ProcessRunner):
    """Runs untrusted argv only through a probed OCI runtime and snapshot mount."""

    def __init__(
        self,
        host_runner: ProcessRunner,
        backend: IsolationBackend,
        snapshot_authorizer: SnapshotAuthorizer,
    ) -> None:
        self._host_runner = host_runner
        self._backend = backend
        self._snapshot_authorizer = snapshot_authorizer

    async def run(self, request: ProcessRequest) -> ProcessResult:
        if request.trust_profile is not TrustProfile.UNTRUSTED:
            raise ProcessIsolationError("OCI runner accepts only untrusted process requests")
        snapshot_root = self._snapshot_authorizer.authorize(request.cwd)
        capability = await self._backend.probe()
        capability = self._backend.authorize(capability)
        if self._snapshot_authorizer.authorize(request.cwd) != snapshot_root:
            raise SnapshotAuthorizationError("snapshot identity changed before OCI execution")
        container_name = f"aif-{uuid.uuid4().hex}"
        run_argv = self._backend.build_run_argv(capability, snapshot_root, container_name, request)
        runtime = Path(run_argv[0])
        runtime_request = ProcessRequest(
            argv=run_argv,
            executable=runtime,
            cwd=snapshot_root,
            policy=ProcessPolicy(
                allowed_executables=(runtime,),
                allowed_cwd_roots=(snapshot_root,),
            ),
            timeout_seconds=min(request.timeout_seconds, DEFAULT_TIMEOUT_SECONDS),
            termination_grace_seconds=request.termination_grace_seconds,
            max_output_bytes=min(request.max_output_bytes, DEFAULT_MAX_OUTPUT_BYTES),
            trust_profile=TrustProfile.TRUSTED,
            redaction_secrets=request.redaction_secrets,
            run_id=request.run_id,
            attempt_id=request.attempt_id,
        )
        try:
            result = await self._host_runner.run(runtime_request)
        except asyncio.CancelledError:
            await asyncio.shield(self._cleanup(capability, snapshot_root, container_name, request))
            raise
        except ProcessExecutionError:
            await self._cleanup(capability, snapshot_root, container_name, request)
            raise
        if result.timed_out or result.truncated:
            await self._cleanup(capability, snapshot_root, container_name, request)
        return result

    async def _cleanup(
        self,
        capability: IsolationCapability,
        snapshot_root: Path,
        container_name: str,
        request: ProcessRequest,
    ) -> None:
        cleanup_argv = self._backend.build_cleanup_argv(capability, container_name)
        runtime = Path(cleanup_argv[0])
        cleanup = ProcessRequest(
            argv=cleanup_argv,
            executable=runtime,
            cwd=snapshot_root,
            policy=ProcessPolicy(
                allowed_executables=(runtime,),
                allowed_cwd_roots=(snapshot_root,),
            ),
            timeout_seconds=min(request.termination_grace_seconds, 5.0),
            termination_grace_seconds=min(request.termination_grace_seconds, 1.0),
            max_output_bytes=1024,
            trust_profile=TrustProfile.TRUSTED,
        )
        try:
            result = await self._host_runner.run(cleanup)
        except ProcessExecutionError as error:
            raise ProcessIsolationError("OCI container cleanup could not be confirmed") from error
        if not result.succeeded or result.timed_out or result.truncated:
            raise ProcessIsolationError("OCI container cleanup could not be confirmed")


def _canonical_runtime(path: Path) -> Path:
    if not path.is_absolute():
        raise IsolationProbeError("OCI runtime path must be absolute")
    try:
        resolved = path.resolve(strict=True)
        path_stat = os.lstat(resolved)
    except OSError as error:
        raise IsolationProbeError("OCI runtime is unavailable") from error
    if not stat.S_ISREG(path_stat.st_mode) or not os.access(resolved, os.X_OK):
        raise IsolationProbeError("OCI runtime executable is invalid")
    return resolved


def _canonical_snapshot_root(path: Path) -> Path:
    if not path.is_absolute():
        raise SnapshotAuthorizationError("snapshot root must be absolute")
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current /= part
            current_stat = os.lstat(current)
            if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
                raise SnapshotAuthorizationError("snapshot root is unsafe")
    except OSError as error:
        raise SnapshotAuthorizationError("snapshot root is unavailable") from error
    return current


def _directory_identity(path: Path) -> tuple[int, int, int, int]:
    try:
        value = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise SnapshotAuthorizationError("snapshot root is unavailable") from error
    return (value.st_dev, value.st_ino, value.st_mtime_ns, value.st_ctime_ns)


def _verify_snapshot_entries(root: Path, entries: Sequence[ManifestEntry]) -> None:
    """Re-hash every included manifest entry before it can be mounted."""
    for entry in entries:
        if not entry.included:
            continue
        relative = Path(entry.path)
        candidate = root / relative
        try:
            value = os.lstat(candidate)
        except OSError as error:
            raise SnapshotAuthorizationError("snapshot content is unavailable") from error
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise SnapshotAuthorizationError("snapshot content is unsafe")
        if value.st_size != entry.size_bytes:
            raise SnapshotAuthorizationError("snapshot content changed")
        try:
            with candidate.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
        except OSError as error:
            raise SnapshotAuthorizationError("snapshot content is unavailable") from error
        if digest != entry.sha256:
            raise SnapshotAuthorizationError("snapshot content changed")


def _image_matches_digest(observed: str, image: str) -> bool:
    digest = image.rsplit(_IMAGE_DIGEST_MARKER, maxsplit=1)[1]
    return observed.endswith(f"{_IMAGE_DIGEST_MARKER}{digest}") or observed == f"sha256:{digest}"


def _validate_container_argv(argv: Sequence[str]) -> None:
    if not argv or "/" in argv[0] or argv[0] in {".", ".."}:
        raise ProcessPolicyError("OCI command must use a simple in-container executable name")
    if any(not item or "\x00" in item for item in argv):
        raise ProcessPolicyError("OCI command contains an unsafe argument")
