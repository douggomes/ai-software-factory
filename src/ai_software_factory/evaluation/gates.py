"""Concrete ``ValidationGate`` implementations.

Structural gates (``ScopeGate``, ``DiffGate``, ``SecretGate``) are pure: they
only inspect facts already captured on ``GateContext``. ``CommandGate`` is the
one gate that performs I/O, executing a single pre-authorized process through
the injected ``ProcessRunner`` port.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from ai_software_factory.core.evaluation_workspace import detect_secrets
from ai_software_factory.core.process_models import (
    DEFAULT_MAX_OUTPUT_BYTES,
    ProcessPolicy,
    ProcessRequest,
    TrustProfile,
)
from ai_software_factory.ports.processes import ProcessExecutionError, ProcessRunner
from ai_software_factory.ports.validation import (
    GateContext,
    GateExecutionError,
    GateFinding,
    GateResult,
    GateStatus,
)

_DOTENV_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"(^|/)\.env(\..+)?$")
_CREDENTIAL_FILE_NAMES: Final[frozenset[str]] = frozenset({"id_rsa", "id_ed25519", "auth.json"})
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 900.0
DEFAULT_COMMAND_MAX_PROCESSES: Final[int] = 64
DEFAULT_COMMAND_MAX_CPU_SECONDS: Final[int] = 900
MAX_SECRET_FINDINGS: Final[int] = 256


def _fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _within_allowed_scope(path: str, allowed_paths: tuple[str, ...]) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return any(candidate.full_match(pattern) for pattern in allowed_paths)


def _scope_finding(path: str) -> GateFinding:
    safe_path = _safe_evidence_path(path)
    return GateFinding(
        code="SCOPE_VIOLATION",
        message=f"changed path is outside the allowed scope: {safe_path}",
        path=safe_path,
    )


def _safe_evidence_path(path: str) -> str:
    encoded = path.encode("utf-8", errors="surrogateescape")
    if detect_secrets(encoded):
        return f"<redacted-path:{_fingerprint(encoded)[:12]}>"
    return path


@dataclass(frozen=True, slots=True)
class ScopeGate:
    """Fails when any changed path falls outside the task's allowed scope."""

    @property
    def name(self) -> str:
        return "scope"

    @property
    def configuration_key(self) -> str:
        return "scope:v1"

    async def evaluate(self, context: GateContext) -> GateResult:
        findings = tuple(
            _scope_finding(path)
            for path in context.changed_files
            if not _within_allowed_scope(path, context.allowed_paths)
        )
        status = GateStatus.FAILED if findings else GateStatus.PASSED
        return GateResult(gate_name=self.name, status=status, findings=findings)


@dataclass(frozen=True, slots=True)
class DiffGate:
    """Fails on an empty diff or a ``git diff --check`` violation."""

    @property
    def name(self) -> str:
        return "diff"

    @property
    def configuration_key(self) -> str:
        return "diff:v1"

    async def evaluate(self, context: GateContext) -> GateResult:
        findings: list[GateFinding] = []
        has_changes = (
            bool(context.repository_evidence.changed_paths)
            if context.repository_evidence is not None
            else bool(context.diff_text.strip())
        )
        diff_check_failed = (
            context.repository_evidence.diff_check_failed
            if context.repository_evidence is not None
            else bool(context.diff_check_output.strip())
        )
        if not has_changes:
            findings.append(GateFinding(code="EMPTY_DIFF", message="no changes to validate"))
        if diff_check_failed:
            findings.append(
                GateFinding(
                    code="DIFF_CHECK_FAILED",
                    message="git diff --check reported whitespace or conflict markers",
                )
            )
        status = GateStatus.FAILED if findings else GateStatus.PASSED
        return GateResult(gate_name=self.name, status=status, findings=tuple(findings))


@dataclass(frozen=True, slots=True)
class SecretGate:
    """Fails when a changed file is unsafe to scan or matches a secret pattern."""

    @property
    def name(self) -> str:
        return "secrets"

    @property
    def configuration_key(self) -> str:
        return "secrets:v1"

    async def evaluate(self, context: GateContext) -> GateResult:
        findings: list[GateFinding] = [*_credential_path_findings(context.changed_files)]
        if context.repository_evidence is not None:
            remaining = MAX_SECRET_FINDINGS - len(findings)
            findings.extend(
                GateFinding(
                    code=f"SECRET_PATTERN_{finding.kind.upper().replace('-', '_')}",
                    message=f"changed file matches a {finding.kind.replace('-', ' ')} pattern",
                    path=_safe_evidence_path(finding.path),
                    fingerprint=finding.fingerprint,
                )
                for finding in context.repository_evidence.secret_findings[:remaining]
            )
            status = GateStatus.FAILED if findings else GateStatus.PASSED
            return GateResult(gate_name=self.name, status=status, findings=tuple(findings))
        for evidence in context.changed_file_evidence:
            if len(findings) >= MAX_SECRET_FINDINGS:
                break
            if evidence.deleted:
                continue
            if evidence.scan_error is not None:
                findings.append(
                    GateFinding(
                        code="SECRET_SCAN_UNAVAILABLE",
                        message="changed path could not be scanned safely",
                        path=_safe_evidence_path(evidence.path),
                        fingerprint=_fingerprint(evidence.path.encode("utf-8")),
                    )
                )
                continue
            remaining = MAX_SECRET_FINDINGS - len(findings)
            findings.extend(
                _secret_pattern_findings(evidence.path, evidence.content, limit=remaining)
            )
        status = GateStatus.FAILED if findings else GateStatus.PASSED
        return GateResult(gate_name=self.name, status=status, findings=tuple(findings))


def _credential_path_findings(changed_files: tuple[str, ...]) -> list[GateFinding]:
    findings: list[GateFinding] = []
    for path in changed_files:
        if len(findings) >= MAX_SECRET_FINDINGS:
            break
        if _DOTENV_NAME_PATTERN.search(path) or Path(path).name in _CREDENTIAL_FILE_NAMES:
            safe_path = _safe_evidence_path(path)
            findings.append(
                GateFinding(
                    code="FORBIDDEN_SECRET_PATH",
                    message=f"change touches a credential-shaped path: {safe_path}",
                    path=safe_path,
                    fingerprint=_fingerprint(path.encode("utf-8")),
                )
            )
    return findings


def _secret_pattern_findings(path: str, content: bytes, *, limit: int) -> list[GateFinding]:
    findings: list[GateFinding] = []
    safe_path = _safe_evidence_path(path)
    for detected in detect_secrets(content):
        if len(findings) >= limit:
            return findings
        code = detected.kind.upper().replace("-", "_")
        findings.append(
            GateFinding(
                code=f"SECRET_PATTERN_{code}",
                message=f"changed file matches a {detected.kind.replace('-', ' ')} pattern",
                path=safe_path,
                fingerprint=_fingerprint(detected.value),
            )
        )
    return findings


@dataclass(frozen=True, slots=True)
class CommandGate:
    """Runs one pre-authorized argv in the worktree via the injected ``ProcessRunner``."""

    gate_name: str
    argv: tuple[str, ...]
    process_runner: ProcessRunner
    process_policy: ProcessPolicy
    timeout_seconds: float = DEFAULT_COMMAND_TIMEOUT_SECONDS
    trust_profile: TrustProfile = TrustProfile.UNTRUSTED

    @property
    def name(self) -> str:
        return self.gate_name

    @property
    def configuration_key(self) -> str:
        logical_argv = (Path(self.argv[0]).name, *self.argv[1:])
        argv_hash = hashlib.sha256("\x00".join(logical_argv).encode("utf-8")).hexdigest()
        return (
            f"command:v1:{self.gate_name}:{self.timeout_seconds}:"
            f"{self.trust_profile.value}:{DEFAULT_MAX_OUTPUT_BYTES}:"
            f"{DEFAULT_COMMAND_MAX_PROCESSES}:{DEFAULT_COMMAND_MAX_CPU_SECONDS}:{argv_hash}"
        )

    async def evaluate(self, context: GateContext) -> GateResult:
        request = ProcessRequest(
            argv=self.argv,
            executable=Path(self.argv[0]),
            cwd=context.worktree_path,
            policy=self.process_policy,
            timeout_seconds=self.timeout_seconds,
            max_output_bytes=DEFAULT_MAX_OUTPUT_BYTES,
            max_processes=DEFAULT_COMMAND_MAX_PROCESSES,
            max_cpu_seconds=DEFAULT_COMMAND_MAX_CPU_SECONDS,
            trust_profile=self.trust_profile,
            run_id=context.run_id,
        )
        try:
            result = await self.process_runner.run(request)
        except (OSError, ProcessExecutionError, subprocess.SubprocessError) as error:
            raise GateExecutionError(f"command gate {self.name!r} could not run") from error
        if result.stdout_ref is None or result.stderr_ref is None:
            raise GateExecutionError(f"command gate {self.name!r} produced no evidence")
        artifact_refs = (result.stdout_ref, result.stderr_ref)
        if any(reference.run_id != context.run_id for reference in artifact_refs):
            raise GateExecutionError(f"command gate {self.name!r} returned cross-run evidence")
        if result.truncated:
            return GateResult(
                gate_name=self.name,
                status=GateStatus.FAILED,
                findings=(
                    GateFinding(
                        code="COMMAND_OUTPUT_TRUNCATED",
                        message="command output exceeded the authorized evidence limit",
                    ),
                ),
                artifact_refs=artifact_refs,
            )
        if result.succeeded:
            return GateResult(
                gate_name=self.name, status=GateStatus.PASSED, artifact_refs=artifact_refs
            )
        timeout_note = " (timed out)" if result.timed_out else ""
        findings = (
            GateFinding(
                code="COMMAND_FAILED",
                message=f"command exited with status {result.returncode}{timeout_note}",
            ),
        )
        return GateResult(
            gate_name=self.name,
            status=GateStatus.FAILED,
            findings=findings,
            artifact_refs=artifact_refs,
        )
