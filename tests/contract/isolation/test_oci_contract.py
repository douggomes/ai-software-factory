"""Shared behavior required from Docker and Podman OCI backends."""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ai_software_factory.adapters.isolation.oci import (
    DockerIsolationBackend,
    OciIsolationPolicy,
    OciIsolationRunner,
    OciProbeResult,
    PodmanIsolationBackend,
)
from ai_software_factory.config import APPROVED_VALIDATION_IMAGE
from ai_software_factory.core.process_models import ProcessRequest, ProcessResult, TrustProfile
from ai_software_factory.ports.processes import ProcessRunner, SnapshotAuthorizer

_IMAGE = APPROVED_VALIDATION_IMAGE


def _runtime(tmp_path: Path, backend: str) -> Path:
    executable = tmp_path / backend
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return executable


@dataclass
class _Probe:
    backend: str
    image: str
    calls: list[tuple[str, ...]] = field(default_factory=lambda: list[tuple[str, ...]]())

    async def execute(self, argv: tuple[str, ...]) -> OciProbeResult:
        self.calls.append(argv)
        if "version" in argv:
            return OciProbeResult(0, "27.0.0")
        if argv[1:3] == ("image", "inspect"):
            return OciProbeResult(0, self.image)
        command = argv[1:4] if self.backend == "podman" else argv[1:3]
        commands: dict[tuple[str, tuple[str, ...]], str] = {
            ("docker", ("context", "show")): "desktop-linux",
            ("podman", ("system", "connection", "default")): "podman-machine-default",
            ("docker", ("context", "inspect")): f"unix://{Path.home()}/.docker/run/docker.sock",
            (
                "podman",
                ("system", "connection", "inspect"),
            ): "ssh://core@localhost:50123/run/user/501/podman/podman.sock",
        }
        output = commands.get((self.backend, command))
        return OciProbeResult(0, output) if output is not None else OciProbeResult(1, "")


@dataclass
class _RecordingHost(ProcessRunner):
    results: list[ProcessResult] = field(
        default_factory=lambda: [
            ProcessResult(
                exit_code=0, signal=None, duration_seconds=0.01, truncated=False, timed_out=False
            )
        ]
    )
    requests: list[ProcessRequest] = field(default_factory=lambda: list[ProcessRequest]())

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.requests.append(request)
        return self.results.pop(0)


class _FixedSnapshot(SnapshotAuthorizer):
    def __init__(self, root: Path) -> None:
        self._root = root

    def authorize(self, requested_cwd: Path) -> Path:
        assert requested_cwd == self._root
        return self._root


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ("docker", "podman"))
async def test_oci_backends_share_closed_runtime_contract(tmp_path: Path, backend: str) -> None:
    runtime = _runtime(tmp_path, backend)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    probe = _Probe(backend, _IMAGE)
    backend_type = DockerIsolationBackend if backend == "docker" else PodmanIsolationBackend
    runtime_backend = backend_type(
        OciIsolationPolicy(backend=backend, image=_IMAGE, runtime=runtime), probe
    )
    host = _RecordingHost()
    runner: ProcessRunner = OciIsolationRunner(host, runtime_backend, _FixedSnapshot(snapshot))

    result = await runner.run(
        ProcessRequest(
            argv=("python", "-m", "pytest"),
            cwd=snapshot,
            trust_profile=TrustProfile.UNTRUSTED,
        )
    )

    assert result.succeeded
    expected_probe_calls = 4
    assert len(probe.calls) == expected_probe_calls
    assert len(host.requests) == 1
    argv = host.requests[0].argv
    assert "--pull=never" in argv
    assert "--network=none" in argv
    assert "--read-only" in argv
    assert "--cap-drop=ALL" in argv
    assert "--security-opt=no-new-privileges" in argv
    assert "--pids-limit" in argv
    assert "--mount" in argv
    mount = argv[argv.index("--mount") + 1]
    assert mount == f"type=bind,src={snapshot},dst=/workspace,readonly"
    assert "--volume" not in argv
    assert "--privileged" not in argv
    assert "HTTP_PROXY" not in "\0".join(argv)
