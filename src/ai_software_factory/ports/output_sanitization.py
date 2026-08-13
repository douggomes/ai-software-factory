"""Streaming output sanitization port."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


class OutputSanitizationError(RuntimeError):
    """Raised when bounded output cannot be sanitized safely."""


@runtime_checkable
class OutputSanitizer(Protocol):
    """Consume untrusted chunks and expose only bounded sanitized bytes."""

    @property
    def truncated(self) -> bool:
        """Whether input or sanitized output exceeded the configured limit."""
        ...

    def feed(self, data: bytes) -> bytes:
        """Consume a chunk; implementations may retain a bounded lookahead."""
        ...

    def finish(self) -> bytes:
        """Return the complete bounded sanitized output exactly once computed."""
        ...


class OutputSanitizerFactory(Protocol):
    """Create an isolated sanitizer for one process stream."""

    def __call__(self, max_bytes: int, secrets: Iterable[bytes]) -> OutputSanitizer:
        """Build a sanitizer with a hard byte limit and explicit secret set."""
        ...
