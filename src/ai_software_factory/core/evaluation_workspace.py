"""Immutable models for safe evaluation snapshots and repository evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final, Protocol

from ai_software_factory.core.ids import RunId
from ai_software_factory.core.workspace_models import Workspace

DEFAULT_MAX_EVALUATION_FILES: Final[int] = 100_000
DEFAULT_MAX_EVALUATION_BYTES: Final[int] = 1_073_741_824
_SHA256_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^snap-[0-9a-f]{12}$")
_CONTROL_CHARACTER_LIMIT: Final[int] = 32
_SECRET_PATTERNS: Final[tuple[tuple[str, re.Pattern[bytes], tuple[str, ...]], ...]] = (
    (
        "private-key",
        re.compile(
            rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
            rb"(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
            re.DOTALL,
        ),
        (),
    ),
    ("aws-access-key", re.compile(rb"\bAKIA[A-Z0-9]{16}\b"), ()),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"), ()),
    ("google-api-key", re.compile(rb"\bAIza[0-9A-Za-z_-]{20,}\b"), ()),
    (
        "jwt",
        re.compile(rb"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        (),
    ),
    (
        "credential-assignment",
        re.compile(
            rb"(?i)(?:[\"']?(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\"']?"
            rb"\s*[:=]\s*)(?:\"(?P<double>(?:\\.|[^\"\\])*)\"|"
            rb"'(?P<single>(?:\\.|[^'\\])*)'|(?P<bare>[^\s,;}]+))"
        ),
        ("double", "single", "bare"),
    ),
    (
        "credential-assignment",
        re.compile(
            rb"(?i)(?:[\"']?(?:password|passwd|secret|token|api[_-]?key|access[_-]?key)[\"']?"
            rb"\s*[:=]\s*)[\"'](?P<partial>(?:\\.|[^\"'\\])*)\Z"
        ),
        ("partial",),
    ),
    (
        "credential-assignment",
        re.compile(
            rb"(?i)(?P<pending>[\"']?(?:password|passwd|secret|token|api[_-]?key|"
            rb"access[_-]?key)[\"']?\s*[:=]\s*)\Z"
        ),
        ("pending",),
    ),
    (
        "partial-token",
        re.compile(rb"\b(?:AKIA|gh[pousr]_|AIza|eyJ)[A-Za-z0-9_.-]*\Z"),
        (),
    ),
)


class EvaluationModelError(ValueError):
    """Raised when an evaluation identity or evidence value is malformed."""


class FileClassification(StrEnum):
    """Git classification assigned to one repository path."""

    TRACKED = "tracked"
    UNTRACKED = "untracked"
    IGNORED = "ignored"


class SnapshotLifecycle(StrEnum):
    """Externally observable lifecycle of an evaluation snapshot."""

    VERIFIED = "verified"


@dataclass(frozen=True, slots=True)
class DetectedSecret:
    """One bounded secret span identified by the canonical domain policy."""

    kind: str
    value: bytes
    start: int
    end: int


def detect_secrets(data: bytes) -> tuple[DetectedSecret, ...]:
    """Return non-overlapping secret spans in deterministic policy order."""
    candidates: list[tuple[int, DetectedSecret]] = []
    for priority, (kind, pattern, value_groups) in enumerate(_SECRET_PATTERNS):
        for match in pattern.finditer(data):
            group: int | str = 0
            for group_name in value_groups:
                if match.group(group_name) is not None:
                    group = group_name
                    break
            start, end = match.span(group)
            if start == end:
                continue
            candidates.append((priority, DetectedSecret(kind, match.group(group), start, end)))
    candidates.sort(key=lambda item: (item[1].start, item[0], -item[1].end))
    detected: list[DetectedSecret] = []
    occupied_until = 0
    for _, candidate in candidates:
        if candidate.start < occupied_until:
            continue
        detected.append(candidate)
        occupied_until = candidate.end
    return tuple(detected)


class ManifestArtifactReference(Protocol):
    """Structural manifest reference returned by the artifact boundary."""

    @property
    def run_id(self) -> RunId:
        """Owning run identity."""
        ...

    @property
    def relative_path(self) -> str:
        """Safe path relative to the run artifact root."""
        ...


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """Non-reversible evidence that a path or payload resembles a credential."""

    kind: str
    path: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.kind or any(
            ord(character) < _CONTROL_CHARACTER_LIMIT for character in self.kind
        ):
            raise EvaluationModelError("secret finding kind is invalid")
        _validate_relative_path(self.path)
        _validate_sha256(self.fingerprint, "secret fingerprint")


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """Content-addressed description of one source path."""

    path: str
    classification: FileClassification
    present: bool
    included: bool
    size_bytes: int
    sha256: str
    binary: bool

    def __post_init__(self) -> None:
        _validate_relative_path(self.path)
        object.__setattr__(self, "classification", FileClassification(self.classification))
        if self.size_bytes < 0:
            raise EvaluationModelError("manifest size must be non-negative")
        _validate_sha256(self.sha256, "manifest entry hash")
        if not self.present and (self.included or self.size_bytes or self.binary):
            raise EvaluationModelError("absent manifest entry has content metadata")


@dataclass(frozen=True, slots=True)
class RepositoryEvidence:
    """Sanitized Git and secret evidence bound to a manifest."""

    tracked_paths: tuple[str, ...]
    untracked_paths: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    changed_paths: tuple[str, ...]
    binary_paths: tuple[str, ...]
    secret_findings: tuple[SecretFinding, ...]
    diff_hash: str

    def __post_init__(self) -> None:
        for field_name in (
            "tracked_paths",
            "untracked_paths",
            "ignored_paths",
            "changed_paths",
            "binary_paths",
        ):
            values = tuple(getattr(self, field_name))
            if values != tuple(sorted(set(values))):
                raise EvaluationModelError(f"{field_name} must be sorted and unique")
            for path in values:
                _validate_relative_path(path)
            object.__setattr__(self, field_name, values)
        findings = tuple(self.secret_findings)
        object.__setattr__(self, "secret_findings", findings)
        _validate_sha256(self.diff_hash, "diff hash")


@dataclass(frozen=True, slots=True)
class EvaluationCaptureRequest:
    """Authorized workspace and hard limits for one private snapshot."""

    workspace: Workspace
    max_files: int = DEFAULT_MAX_EVALUATION_FILES
    max_total_bytes: int = DEFAULT_MAX_EVALUATION_BYTES

    def __post_init__(self) -> None:
        if self.max_files <= 0 or self.max_files > DEFAULT_MAX_EVALUATION_FILES:
            raise EvaluationModelError("evaluation file limit is outside policy")
        if self.max_total_bytes <= 0 or self.max_total_bytes > DEFAULT_MAX_EVALUATION_BYTES:
            raise EvaluationModelError("evaluation byte limit is outside policy")


@dataclass(frozen=True, slots=True)
class EvaluationSnapshot:
    """Immutable snapshot identity and its sanitized evidence."""

    snapshot_id: str
    workspace: Workspace
    root: Path
    head_commit: str
    entries: tuple[ManifestEntry, ...]
    evidence: RepositoryEvidence
    manifest_ref: ManifestArtifactReference
    manifest_hash: str
    identity_hash: str
    lifecycle: SnapshotLifecycle = SnapshotLifecycle.VERIFIED

    def __post_init__(self) -> None:
        if not _SNAPSHOT_ID_PATTERN.fullmatch(self.snapshot_id):
            raise EvaluationModelError("snapshot identity is invalid")
        object.__setattr__(self, "lifecycle", SnapshotLifecycle(self.lifecycle))
        if self.lifecycle is not SnapshotLifecycle.VERIFIED:
            raise EvaluationModelError("only verified snapshots may cross the port")
        root = Path(self.root)
        if not root.is_absolute():
            raise EvaluationModelError("snapshot root must be absolute")
        object.__setattr__(self, "root", root)
        if not re.fullmatch(r"[0-9a-f]{40}", self.head_commit):
            raise EvaluationModelError("snapshot HEAD is invalid")
        entries = tuple(self.entries)
        paths = tuple(entry.path for entry in entries)
        if paths != tuple(sorted(set(paths))):
            raise EvaluationModelError("manifest entries must be sorted and unique")
        object.__setattr__(self, "entries", entries)
        if self.manifest_ref.run_id != self.workspace.run_id:
            raise EvaluationModelError("manifest reference belongs to another run")
        _validate_sha256(self.manifest_hash, "manifest hash")
        _validate_sha256(self.identity_hash, "snapshot identity hash")


def _validate_relative_path(path: str) -> None:
    if not path or "\\" in path or "\x00" in path:
        raise EvaluationModelError("repository path is invalid")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise EvaluationModelError("repository path is unsafe")
    if pure.parts[0] == ".git":
        raise EvaluationModelError("Git metadata cannot enter an evaluation snapshot")


def _validate_sha256(value: str, label: str) -> None:
    if not _SHA256_PATTERN.fullmatch(value):
        raise EvaluationModelError(f"{label} is invalid")
