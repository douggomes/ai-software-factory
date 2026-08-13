"""Canonical bounded sanitizer for untrusted subprocess output."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from ai_software_factory.core.evaluation_workspace import detect_secrets
from ai_software_factory.ports.output_sanitization import OutputSanitizationError

_REDACTION_MARKER: Final[bytes] = b"<REDACTED>"
_LOOKAHEAD_BYTES: Final[int] = 4096


class StreamingOutputSanitizer:
    """Bound raw input, then redact structural and explicit secrets before release.

    Chunks are retained only up to ``max_bytes`` plus a small lookahead.  No raw
    byte is returned by ``feed``; this makes cross-chunk patterns impossible to
    leak while keeping memory bounded independently of child output volume.
    """

    def __init__(self, max_bytes: int, secrets: Iterable[bytes] = ()) -> None:
        if max_bytes <= 0:
            raise OutputSanitizationError("output limit must be positive")
        self._max_bytes = max_bytes
        self._secrets = tuple(
            sorted({bytes(secret) for secret in secrets if secret}, key=len, reverse=True)
        )
        longest_secret = max((len(secret) for secret in self._secrets), default=0)
        if longest_secret > max_bytes:
            raise OutputSanitizationError("explicit secret exceeds the output policy")
        self._input_limit = max_bytes + max(_LOOKAHEAD_BYTES, longest_secret)
        self._buffer = bytearray()
        self._truncated = False
        self._finished: bytes | None = None

    @property
    def truncated(self) -> bool:
        return self._truncated

    def feed(self, data: bytes) -> bytes:
        """Consume bytes without releasing unsanitized partial matches."""
        if self._finished is not None:
            raise OutputSanitizationError("cannot feed a finished sanitizer")
        remaining = self._input_limit - len(self._buffer)
        if len(data) > remaining:
            self._buffer.extend(data[: max(0, remaining)])
            self._truncated = True
        else:
            self._buffer.extend(data)
        return b""

    def finish(self) -> bytes:
        """Return bounded redacted bytes; repeated reads are deterministic."""
        if self._finished is None:
            redacted = _redact(bytes(self._buffer), self._secrets)
            if len(redacted) > self._max_bytes:
                redacted = redacted[: self._max_bytes]
                self._truncated = True
            self._finished = redacted
            self._buffer.clear()
        return self._finished


def _redact(data: bytes, secrets: tuple[bytes, ...]) -> bytes:
    redacted = data
    for secret in secrets:
        redacted = redacted.replace(secret, _REDACTION_MARKER)
    for detected in reversed(detect_secrets(redacted)):
        redacted = redacted[: detected.start] + _REDACTION_MARKER + redacted[detected.end :]
    return redacted
