"""Immutable value objects for domain identifiers.

These are strongly-typed, non-interchangeable identifiers used throughout
the domain model. Each is frozen and hashable to prevent mutation and allow
use as dictionary keys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_RUN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^run-[a-z0-9]{12}$")
_TASK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^TASK-(\d{3,})$")
_ATTEMPT_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^att-[a-z0-9]{12}$")


@dataclass(frozen=True, slots=True)
class RunId:
    """Unique identifier for a factory run."""

    value: str

    def __post_init__(self) -> None:
        if not _RUN_ID_PATTERN.match(self.value):
            raise ValueError(f"invalid RunId format: {self.value!r}")


@dataclass(frozen=True, slots=True)
class TaskId:
    """Unique identifier for a task within a SPEC (TASK-NNN)."""

    value: str

    def __post_init__(self) -> None:
        if not _TASK_ID_PATTERN.match(self.value):
            raise ValueError(f"invalid TaskId format: {self.value!r}")

    @property
    def ordinal(self) -> int:
        match = _TASK_ID_PATTERN.match(self.value)
        if match is None:
            raise ValueError(f"invalid TaskId: {self.value!r}")
        return int(match.group(1))


@dataclass(frozen=True, slots=True)
class AttemptId:
    """Unique identifier for an execution attempt."""

    value: str

    def __post_init__(self) -> None:
        if not _ATTEMPT_ID_PATTERN.match(self.value):
            raise ValueError(f"invalid AttemptId format: {self.value!r}")
