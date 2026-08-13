"""Integration-level behavior for OCI invocation construction and cleanup."""

from __future__ import annotations

import asyncio
import json
import stat
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from ai_software_factory.adapters.isolation.oci import (
    DockerIsolationBackend,
    OciIsolationPolicy,
    OciIsolationRunner,
    OciProbeResult,
)
from ai_software_factory.config import APPROVED_VALIDATION_IMAGE
from ai_software_factory.core.process_models import ProcessRequest, ProcessResult, TrustProfile
from ai_software_factory.ports.processes import (
    ProcessIsolationError,
    ProcessRunner,
    SnapshotAuthorizer,
)

_IMAGE = APPROVED_VALIDATION_IMAGE
_CLEANUP_REQUEST_COUNT = 2


def _runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "docker"
    runtime.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    runtime.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return runtime


@dataclass
class _Probe:
    async def execute(self, argv: tuple[str, ...]) -> OciProbeResult:
        if "version" in argv:
            return OciProbeResult(0, "27.0.0")
        if argv[1:] == ("context", "show"):
            return OciProbeResult(0, "desktop-linux")
        if argv[1:3] == ("context", "inspect"):
            return OciProbeResult(0, f"unix://{Path.home()}/.docker/run/docker.sock")
        return OciProbeResult(0, _IMAGE)


@dataclass
class _Host(ProcessRunner):
    result: ProcessResult
    requests: list[ProcessRequest] = field(default_factory=lambda: list[ProcessRequest]())

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            return self.result
        return ProcessResult(
            exit_code=0, signal=None, duration_seconds=0, truncated=False, timed_out=False
        )


class _Snapshot(SnapshotAuthorizer):
    def __init__(self, root: Path) -> None:
        self.root = root

    def authorize(self, requested_cwd: Path) -> Path:
        assert requested_cwd == self.root
        return self.root


@dataclass
class _SequenceHost(ProcessRunner):
    results: list[ProcessResult]
    requests: list[ProcessRequest] = field(default_factory=lambda: list[ProcessRequest]())

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.requests.append(request)
        return self.results.pop(0)


@pytest.mark.asyncio
async def test_image_digest_sbom_and_offline_execution(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[2]
    lock = json.loads(
        (repository_root / "containers/validation/image.lock.json").read_text("utf-8")
    )
    sbom = json.loads((repository_root / "containers/validation/sbom.cdx.json").read_text("utf-8"))
    provenance = json.loads(
        (repository_root / "containers/validation/provenance.json").read_text("utf-8")
    )
    dockerfile = (repository_root / "containers/validation/Dockerfile").read_text("utf-8")
    assert lock["image"] == _IMAGE
    assert sbom["bomFormat"] == "CycloneDX"
    assert provenance["image"] == _IMAGE
    assert "FROM docker.io/library/python@sha256:" in dockerfile
    assert "ENTRYPOINT" not in dockerfile

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    host = _Host(
        ProcessResult(
            exit_code=0, signal=None, duration_seconds=0, truncated=False, timed_out=False
        )
    )
    runner = OciIsolationRunner(
        host,
        DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, _runtime(tmp_path)), _Probe()),
        _Snapshot(snapshot),
    )

    result = await runner.run(
        ProcessRequest(argv=("python", "-V"), cwd=snapshot, trust_profile=TrustProfile.UNTRUSTED)
    )

    assert result.succeeded
    invocation = host.requests[0].argv
    assert "--pull=never" in invocation
    assert all("pull" not in argument or argument == "--pull=never" for argument in invocation)
    assert invocation[-2:] == ("python", "-V")


@pytest.mark.asyncio
async def test_output_timeout_and_cancellation_are_bounded(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    timed_out = ProcessResult(
        exit_code=None,
        signal=9,
        duration_seconds=1,
        truncated=True,
        timed_out=True,
    )
    host = _Host(timed_out)
    runner = OciIsolationRunner(
        host,
        DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, _runtime(tmp_path)), _Probe()),
        _Snapshot(snapshot),
    )

    result = await runner.run(
        ProcessRequest(argv=("python",), cwd=snapshot, trust_profile=TrustProfile.UNTRUSTED)
    )

    assert result.timed_out
    assert result.truncated
    expected_runtime_requests = 2
    assert len(host.requests) == expected_runtime_requests
    cleanup_start = host.requests[1].argv.index("rm")
    assert host.requests[1].argv[cleanup_start : cleanup_start + 3] == (
        "rm",
        "--force",
        host.requests[0].argv[host.requests[0].argv.index("--name") + 1],
    )
    assert host.requests[1].trust_profile is TrustProfile.TRUSTED

    waiting = asyncio.Event()

    @dataclass
    class _WaitingHost(ProcessRunner):
        requests: list[ProcessRequest] = field(default_factory=lambda: list[ProcessRequest]())

        async def run(self, request: ProcessRequest) -> ProcessResult:
            self.requests.append(request)
            if "run" in request.argv:
                waiting.set()
                await asyncio.Event().wait()
            return ProcessResult(
                exit_code=0, signal=None, duration_seconds=0, truncated=False, timed_out=False
            )

    waiting_host = _WaitingHost()
    cancelled = OciIsolationRunner(
        waiting_host,
        DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, _runtime(tmp_path)), _Probe()),
        _Snapshot(snapshot),
    )
    task = asyncio.create_task(
        cancelled.run(
            ProcessRequest(argv=("python",), cwd=snapshot, trust_profile=TrustProfile.UNTRUSTED)
        )
    )
    await waiting.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(waiting_host.requests) == _CLEANUP_REQUEST_COUNT
    cleanup_start = waiting_host.requests[1].argv.index("rm")
    assert waiting_host.requests[1].argv[cleanup_start : cleanup_start + 2] == ("rm", "--force")

    cleanup_failure = _SequenceHost(
        [
            timed_out,
            ProcessResult(
                exit_code=1, signal=None, duration_seconds=0, truncated=False, timed_out=False
            ),
        ]
    )
    failed_runner = OciIsolationRunner(
        cleanup_failure,
        DockerIsolationBackend(OciIsolationPolicy("docker", _IMAGE, _runtime(tmp_path)), _Probe()),
        _Snapshot(snapshot),
    )
    with pytest.raises(ProcessIsolationError, match="cleanup"):
        await failed_runner.run(
            ProcessRequest(argv=("python",), cwd=snapshot, trust_profile=TrustProfile.UNTRUSTED)
        )
