"""ArtifactStore port — immutable, integrity-checked payload storage.

Artifacts are large binary/text payloads written once and never overwritten.
The port exposes only domain-oriented references; filesystem details stay in
the adapter. ``StoredArtifact`` is the immutable result of a write, while the
adapter's persisted metadata is the integrity record used on later reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final, Protocol, runtime_checkable

from ai_software_factory.core.ids import RunId

MAX_ARTIFACT_BYTES: Final[int] = 67_108_864
FACTORY_HOME_MODE: Final[int] = 0o700
ARTIFACT_FILE_MODE: Final[int] = 0o600
HASH_ALGORITHM: Final[str] = "sha256"
SHA256_HEX_LENGTH: Final[int] = 64

_RELATIVE_SEGMENT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactError(Exception):
    """Base class for artifact storage failures."""


class ArtifactAlreadyExistsError(ArtifactError):
    """Raised when put would overwrite an existing artifact."""

    def __init__(self, ref: ArtifactRef) -> None:
        self.ref = ref
        super().__init__(f"artifact already exists: {ref.run_id.value}/{ref.relative_path}")


class ArtifactNotFoundError(ArtifactError):
    """Raised when the referenced artifact is missing."""

    def __init__(self, ref: ArtifactRef) -> None:
        self.ref = ref
        super().__init__(f"artifact not found: {ref.run_id.value}/{ref.relative_path}")


class ArtifactIntegrityError(ArtifactError):
    """Raised when path, ownership, mode, size or hash checks fail closed."""


class ArtifactTooLargeError(ArtifactError):
    """Raised when payload exceeds the configured maximum size."""

    def __init__(self, size: int, limit: int = MAX_ARTIFACT_BYTES) -> None:
        self.size = size
        self.limit = limit
        super().__init__(f"artifact size {size} exceeds limit {limit}")


class ArtifactKind(Enum):
    """Coarse classification of stored artifacts."""

    SPEC = auto()
    PLAN = auto()
    CONTEXT_MANIFEST = auto()
    CHECKPOINT = auto()
    VALIDATION = auto()
    REVIEW = auto()
    CONTINUATION = auto()
    OTHER = auto()


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Logical reference to an artifact within a run's storage tree.

    ``relative_path`` is a POSIX-style path relative to the run root. It must
    not be absolute, must not contain ``..`` or empty segments, and each
    segment must be a safe filename token.
    """

    run_id: RunId
    relative_path: str
    kind: ArtifactKind = ArtifactKind.OTHER

    def __post_init__(self) -> None:
        path = self.relative_path
        if not path or path.startswith("/") or "\\" in path:
            raise ValueError(f"invalid artifact relative_path: {path!r}")
        segments = path.split("/")
        if any(segment in {"", ".", ".."} for segment in segments):
            raise ValueError(f"invalid artifact relative_path: {path!r}")
        for segment in segments:
            if not _RELATIVE_SEGMENT_PATTERN.match(segment):
                raise ValueError(f"unsafe artifact path segment: {segment!r}")


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Immutable metadata snapshot produced by a successful ``put``."""

    ref: ArtifactRef
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        if self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if self.size_bytes > MAX_ARTIFACT_BYTES:
            raise ValueError(f"size_bytes exceeds limit: {self.size_bytes}")
        if len(self.sha256) != SHA256_HEX_LENGTH or any(
            c not in "0123456789abcdef" for c in self.sha256
        ):
            raise ValueError(f"invalid sha256 digest: {self.sha256!r}")


@runtime_checkable
class ArtifactStore(Protocol):
    """Protocol for integrity-preserving artifact storage."""

    def put(self, ref: ArtifactRef, data: bytes) -> StoredArtifact:
        """Create-exclusive write with temp file + atomic publish.

        Guarantees:
        - destination is never partially published;
        - overwrite is rejected;
        - content is hashed with SHA-256;
        - file mode is ``0600`` and parents are ``0700``.

        Raises ArtifactAlreadyExistsError, ArtifactTooLargeError,
        ArtifactIntegrityError or ValueError on invalid refs.
        """
        ...

    def read(self, ref: ArtifactRef) -> bytes:
        """Read and re-validate root, ownership, mode, size and hash.

        Raises ArtifactNotFoundError or ArtifactIntegrityError on any
        failed integrity check (symlink, external path, wrong owner/mode,
        size mismatch or hash mismatch).
        """
        ...
