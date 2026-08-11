"""Immutable domain models for the Software SPEC contract.

Every model is frozen and hashable so specs can be compared, serialized and
used as dictionary keys without risk of mutation after parsing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Final

TASK_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^TASK-(\d{3,})$")
AC_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^AC-(\d{3,})$")


@dataclass(frozen=True, slots=True)
class TaskId:
    """Strongly-typed task identifier (``TASK-NNN``)."""

    value: str

    @property
    def ordinal(self) -> int:
        match = TASK_ID_PATTERN.match(self.value)
        if match is None:
            raise ValueError(f"invalid TaskId: {self.value!r}")
        return int(match.group(1))


@dataclass(frozen=True, slots=True)
class AcceptanceCriterion:
    """Single acceptance criterion with stable ID and description."""

    ac_id: str
    description: str


@dataclass(frozen=True, slots=True)
class ValidationCommand:
    """Command expressed as an argument array — never a shell string."""

    args: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """Full specification of one task inside a Software SPEC."""

    task_id: TaskId
    title: str
    depends_on: tuple[TaskId, ...]
    allowed_paths: tuple[str, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    validation_commands: tuple[ValidationCommand, ...]


@dataclass(frozen=True, slots=True)
class SoftwareSpec:
    """Top-level parsed SPEC — immutable and canonical."""

    spec_id: str
    schema_version: int
    title: str
    tasks: tuple[TaskSpec, ...]


@dataclass(frozen=True, slots=True)
class SpecValidationError:
    """Single validation error with stable machine-readable code."""

    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Outcome of ``SpecValidator.validate`` — immutable summary."""

    valid: bool
    errors: tuple[SpecValidationError, ...]
    spec: SoftwareSpec | None = None

    def to_json_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "valid": self.valid,
            "errors": [
                {"code": e.code, "message": e.message, **({"path": e.path} if e.path else {})}
                for e in self.errors
            ],
        }
        if self.spec is not None:
            result["spec"] = _spec_to_json_dict(self.spec)
        return result


def _spec_to_json_dict(spec: SoftwareSpec) -> dict[str, object]:
    return {
        "spec_id": spec.spec_id,
        "schema_version": spec.schema_version,
        "title": spec.title,
        "tasks": [
            {
                "task_id": t.task_id.value,
                "title": t.title,
                "depends_on": [d.value for d in t.depends_on],
                "allowed_paths": list(t.allowed_paths),
                "acceptance_criteria": [
                    {"ac_id": ac.ac_id, "description": ac.description}
                    for ac in t.acceptance_criteria
                ],
                "validation_commands": [{"args": list(cmd.args)} for cmd in t.validation_commands],
            }
            for t in spec.tasks
        ],
    }


def canonical_json(spec: SoftwareSpec) -> str:
    """Produce deterministic, sorted JSON for a parsed SPEC."""
    return json.dumps(_spec_to_json_dict(spec), indent=2, sort_keys=True, ensure_ascii=False)


def is_valid_task_id(value: str) -> bool:
    return TASK_ID_PATTERN.match(value) is not None


def is_valid_ac_id(value: str) -> bool:
    return AC_ID_PATTERN.match(value) is not None
