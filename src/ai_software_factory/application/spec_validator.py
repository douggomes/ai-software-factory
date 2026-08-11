"""Deterministic SPEC validator — checks IDs, ACs, scopes, commands and DAG.

Pure validation with no I/O. Produces a ``ValidationReport`` with stable
error codes suitable for machine consumption.
"""

from __future__ import annotations

import re
from typing import Final

from ai_software_factory.core.spec_models import (
    SoftwareSpec,
    SpecValidationError,
    ValidationReport,
    is_valid_ac_id,
    is_valid_task_id,
)

MAX_DEPENDENCY_DEPTH: Final[int] = 50
MAX_TASKS: Final[int] = 200
SCHEMA_VERSION: Final[int] = 1
_SHELL_META: Final[re.Pattern[str]] = re.compile(r"[|&;`$<>(){}!\\\n\r]")

_WHITE: Final[int] = 0
_GRAY: Final[int] = 1
_BLACK: Final[int] = 2


class SpecValidator:
    """Stateless, pure validator — no I/O, no global state."""

    def validate(
        self,
        spec: SoftwareSpec,
        task_id: str | None = None,
    ) -> ValidationReport:
        errors: list[SpecValidationError] = []
        errors.extend(_check_schema_version(spec))
        errors.extend(_check_task_count(spec))
        errors.extend(_check_task_ids(spec))
        errors.extend(_check_duplicate_tasks(spec))
        errors.extend(_check_acceptance_criteria(spec))
        errors.extend(_check_allowed_paths(spec))
        errors.extend(_check_validation_commands(spec))
        errors.extend(_check_dependency_references(spec))
        errors.extend(_check_dependency_cycles(spec))
        errors.extend(_check_dependency_depth(spec))
        if task_id is not None:
            errors.extend(_check_task_exists(spec, task_id))

        if errors:
            return ValidationReport(valid=False, errors=tuple(errors))
        return ValidationReport(valid=True, errors=(), spec=spec)


def _check_schema_version(spec: SoftwareSpec) -> list[SpecValidationError]:
    if spec.schema_version != SCHEMA_VERSION:
        return [
            SpecValidationError(
                code="INVALID_SCHEMA_VERSION",
                message=f"schema_version must be {SCHEMA_VERSION}, got {spec.schema_version}",
                path="schema_version",
            )
        ]
    return []


def _check_task_count(spec: SoftwareSpec) -> list[SpecValidationError]:
    if len(spec.tasks) > MAX_TASKS:
        return [
            SpecValidationError(
                code="TOO_MANY_TASKS",
                message=f"SPEC has {len(spec.tasks)} tasks, max is {MAX_TASKS}",
                path="tasks",
            )
        ]
    return []


def _check_task_ids(spec: SoftwareSpec) -> list[SpecValidationError]:
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        if not is_valid_task_id(task.task_id.value):
            errors.append(
                SpecValidationError(
                    code="INVALID_TASK_ID",
                    message=f"invalid task ID format: {task.task_id.value!r}",
                    path=f"tasks.{task.task_id.value}",
                )
            )
    return errors


def _check_duplicate_tasks(spec: SoftwareSpec) -> list[SpecValidationError]:
    seen: set[str] = set()
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        if task.task_id.value in seen:
            errors.append(
                SpecValidationError(
                    code="DUPLICATE_TASK_ID",
                    message=f"duplicate task ID: {task.task_id.value}",
                    path=f"tasks.{task.task_id.value}",
                )
            )
        seen.add(task.task_id.value)
    return errors


def _check_acceptance_criteria(spec: SoftwareSpec) -> list[SpecValidationError]:
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        if not task.acceptance_criteria:
            errors.append(
                SpecValidationError(
                    code="EMPTY_ACCEPTANCE_CRITERIA",
                    message=f"task {task.task_id.value} has no acceptance criteria",
                    path=f"tasks.{task.task_id.value}.acceptance_criteria",
                )
            )
        seen_acs: set[str] = set()
        for ac in task.acceptance_criteria:
            if not is_valid_ac_id(ac.ac_id):
                errors.append(
                    SpecValidationError(
                        code="INVALID_AC_ID",
                        message=f"invalid AC ID format: {ac.ac_id!r}",
                        path=f"tasks.{task.task_id.value}.acceptance_criteria",
                    )
                )
            if ac.ac_id in seen_acs:
                errors.append(
                    SpecValidationError(
                        code="DUPLICATE_AC_ID",
                        message=f"duplicate AC ID in task {task.task_id.value}: {ac.ac_id}",
                        path=f"tasks.{task.task_id.value}.acceptance_criteria",
                    )
                )
            seen_acs.add(ac.ac_id)
    return errors


def _check_allowed_paths(spec: SoftwareSpec) -> list[SpecValidationError]:
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        if not task.allowed_paths:
            errors.append(
                SpecValidationError(
                    code="EMPTY_ALLOWED_PATHS",
                    message=f"task {task.task_id.value} has no allowed paths",
                    path=f"tasks.{task.task_id.value}.allowed_paths",
                )
            )
        for path in task.allowed_paths:
            if not path or path.startswith("/") or ".." in path:
                errors.append(
                    SpecValidationError(
                        code="UNSAFE_PATH",
                        message=f"task {task.task_id.value}: unsafe path {path!r}",
                        path=f"tasks.{task.task_id.value}.allowed_paths",
                    )
                )
    return errors


def _check_validation_commands(spec: SoftwareSpec) -> list[SpecValidationError]:
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        if not task.validation_commands:
            errors.append(
                SpecValidationError(
                    code="EMPTY_VALIDATION_COMMANDS",
                    message=f"task {task.task_id.value} has no validation commands",
                    path=f"tasks.{task.task_id.value}.validation_commands",
                )
            )
        for cmd in task.validation_commands:
            if not cmd.args:
                errors.append(
                    SpecValidationError(
                        code="EMPTY_COMMAND_ARGS",
                        message=f"task {task.task_id.value}: validation command has no args",
                        path=f"tasks.{task.task_id.value}.validation_commands",
                    )
                )
            for arg in cmd.args:
                if _SHELL_META.search(arg):
                    errors.append(
                        SpecValidationError(
                            code="SHELL_STRING_IN_COMMAND",
                            message=(
                                f"task {task.task_id.value}: shell meta in command arg {arg!r}"
                            ),
                            path=f"tasks.{task.task_id.value}.validation_commands",
                        )
                    )
                    break
    return errors


def _check_dependency_references(spec: SoftwareSpec) -> list[SpecValidationError]:
    known = {t.task_id.value for t in spec.tasks}
    errors: list[SpecValidationError] = []
    for task in spec.tasks:
        for dep in task.depends_on:
            if dep.value not in known:
                errors.append(
                    SpecValidationError(
                        code="UNKNOWN_DEPENDENCY",
                        message=(f"task {task.task_id.value} depends on unknown task {dep.value}"),
                        path=f"tasks.{task.task_id.value}.depends_on",
                    )
                )
    return errors


def _check_dependency_cycles(spec: SoftwareSpec) -> list[SpecValidationError]:
    adjacency: dict[str, list[str]] = {
        t.task_id.value: [d.value for d in t.depends_on] for t in spec.tasks
    }
    color: dict[str, int] = dict.fromkeys(adjacency, _WHITE)
    errors: list[SpecValidationError] = []

    def dfs(node: str) -> bool:
        color[node] = _GRAY
        for neighbor in adjacency.get(node, []):
            if neighbor not in color:
                continue
            if color[neighbor] == _GRAY:
                errors.append(
                    SpecValidationError(
                        code="DEPENDENCY_CYCLE",
                        message=f"dependency cycle detected involving {node} and {neighbor}",
                        path=f"tasks.{node}.depends_on",
                    )
                )
                return True
            if color[neighbor] == _WHITE and dfs(neighbor):
                return True
        color[node] = _BLACK
        return False

    for tid in adjacency:
        if color[tid] == _WHITE:
            dfs(tid)
    return errors


def _check_dependency_depth(spec: SoftwareSpec) -> list[SpecValidationError]:
    adjacency: dict[str, list[str]] = {
        t.task_id.value: [d.value for d in t.depends_on] for t in spec.tasks
    }
    errors: list[SpecValidationError] = []
    cache: dict[str, int] = {}

    def depth(node: str, visited: set[str]) -> int:
        if node in cache:
            return cache[node]
        if node in visited:
            return 0
        visited.add(node)
        deps = adjacency.get(node, [])
        if not deps:
            cache[node] = 0
            return 0
        max_dep = 0
        for dep in deps:
            if dep in adjacency:
                max_dep = max(max_dep, depth(dep, visited))
        result = max_dep + 1
        cache[node] = result
        return result

    for tid in adjacency:
        d = depth(tid, set())
        if d > MAX_DEPENDENCY_DEPTH:
            errors.append(
                SpecValidationError(
                    code="DEPENDENCY_DEPTH_EXCEEDED",
                    message=(f"task {tid} dependency depth {d} exceeds max {MAX_DEPENDENCY_DEPTH}"),
                    path=f"tasks.{tid}.depends_on",
                )
            )
    return errors


def _check_task_exists(spec: SoftwareSpec, task_id: str) -> list[SpecValidationError]:
    known = {t.task_id.value for t in spec.tasks}
    if task_id not in known:
        return [
            SpecValidationError(
                code="TASK_NOT_FOUND",
                message=f"requested task {task_id!r} not found in SPEC",
                path="task_id",
            )
        ]
    return []
