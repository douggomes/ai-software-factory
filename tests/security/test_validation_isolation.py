"""Abuse tests for the OCI-only untrusted validation boundary."""

from __future__ import annotations

import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ai_software_factory.adapters.isolation import oci
from ai_software_factory.adapters.isolation.oci import (
    AsyncioOciProbeExecutor,
    DockerIsolationBackend,
    OciIsolationPolicy,
    OciIsolationRunner,
    OciProbeResult,
)
from ai_software_factory.adapters.process.asyncio_runner import AsyncioProcessRunner
from ai_software_factory.adapters.process.output_sanitizer import StreamingOutputSanitizer
from ai_software_factory.config import APPROVED_VALIDATION_IMAGE
from ai_software_factory.core.process_models import (
    ProcessPolicy,
    ProcessRequest,
    ProcessResult,
    TrustProfile,
)
from ai_software_factory.ports.processes import (
    IsolationProbeError,
    ProcessIsolationError,
    ProcessRunner,
    SnapshotAuthorizationError,
    SnapshotAuthorizer,
)

_IMAGE = APPROVED_VALIDATION_IMAGE


def _runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "docker"
    runtime.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return runtime


@dataclass
class _Probe:
    context: str = "desktop-linux"
    endpoint: str = f"unix://{Path.home()}/.docker/run/docker.sock"
    calls: list[tuple[str, ...]] = field(default_factory=lambda: list[tuple[str, ...]]())

    async def execute(self, argv: tuple[str, ...]) -> OciProbeResult:
        self.calls.append(argv)
        if "version" in argv:
            return OciProbeResult(0, "27.0.0")
        if argv[1:] == ("context", "show"):
            return OciProbeResult(0, self.context)
        if argv[1:3] == ("context", "inspect"):
            return OciProbeResult(0, self.endpoint)
        return OciProbeResult(0, _IMAGE)


@dataclass
class _Host(ProcessRunner):
    calls: list[ProcessRequest] = field(default_factory=lambda: list[ProcessRequest]())

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.calls.append(request)
        return ProcessResult(
            exit_code=0, signal=None, duration_seconds=0, truncated=False, timed_out=False
        )


class _DeniedSnapshot(SnapshotAuthorizer):
    def authorize(self, requested_cwd: Path) -> Path:
        raise SnapshotAuthorizationError("not a verified snapshot")


@pytest.mark.asyncio
async def test_untrusted_never_falls_back_to_host_runner(tmp_path: Path) -> None:
    executable = _runtime(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    host = _Host()
    probe = _Probe()
    runner = OciIsolationRunner(
        host,
        DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, executable), probe),
        _DeniedSnapshot(),
    )

    with pytest.raises(SnapshotAuthorizationError):
        await runner.run(
            ProcessRequest(argv=("python",), cwd=snapshot, trust_profile=TrustProfile.UNTRUSTED)
        )

    assert not probe.calls
    assert not host.calls
    host_runner = AsyncioProcessRunner(sanitizer_factory=StreamingOutputSanitizer)
    with pytest.raises(ProcessIsolationError):
        await host_runner.run(
            ProcessRequest(
                argv=(str(executable),),
                executable=executable,
                cwd=tmp_path,
                policy=ProcessPolicy(
                    allowed_executables=(executable,),
                    allowed_cwd_roots=(tmp_path,),
                ),
                trust_profile=TrustProfile.UNTRUSTED,
            )
        )


@pytest.mark.asyncio
async def test_remote_runtime_and_mutable_or_missing_image_fail_without_spawn(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    host = _Host()
    probe = _Probe(context="remote-daemon")
    backend = DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, runtime), probe)

    with pytest.raises(IsolationProbeError):
        await backend.probe()
    assert not host.calls
    assert all("pull" not in argument for call in probe.calls for argument in call)
    native_probe = _Probe(endpoint="unix:///var/run/docker.sock")
    native_backend = DockerIsolationBackend(
        OciIsolationPolicy("docker", _IMAGE, runtime), native_probe
    )
    with pytest.raises(IsolationProbeError):
        await native_backend.probe()
    with pytest.raises(IsolationProbeError):
        OciIsolationPolicy("docker", "registry.example/aif:latest", runtime)


@pytest.mark.asyncio
async def test_probe_executor_bounds_output_and_rejects_non_metadata_commands(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "docker"
    runtime.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stdout.write('x' * 4097)\n",
        encoding="utf-8",
    )
    runtime.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    executor = AsyncioOciProbeExecutor()

    with pytest.raises(IsolationProbeError):
        await executor.execute((str(runtime), "version", "--format", "{{.Server.Version}}"))
    with pytest.raises(IsolationProbeError):
        await executor.execute((str(runtime), "run", "--privileged"))


@pytest.mark.asyncio
async def test_cleanup_capability_remains_bound_after_run_capability_expires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    backend = DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, runtime), _Probe())
    capability = await backend.probe()

    monkeypatch.setattr(oci.time, "monotonic", lambda: float("inf"))

    cleanup = backend.build_cleanup_argv(capability, "aif-owned-container")
    assert "rm" in cleanup
    assert "--force" in cleanup
