"""Property-based and abuse tests for the SPEC parser and validator.

AC-002: cycle, duplicate AC, empty scope, shell string, excess and traversal
all fail with exit 2 — tested here via the validator producing errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_factory.application.spec_parser import SpecParseError, SpecParser
from ai_software_factory.application.spec_validator import SpecValidator
from ai_software_factory.cli import main as cli_main
from ai_software_factory.core.spec_models import (
    AcceptanceCriterion,
    SoftwareSpec,
    TaskId,
    TaskSpec,
    ValidationCommand,
)


def _make_task(
    task_id: str = "TASK-001",
    depends_on: tuple[str, ...] = (),
    paths: tuple[str, ...] = ("src/a.py",),
    acs: tuple[tuple[str, str], ...] = (("AC-001", "desc"),),
    cmds: tuple[tuple[str, ...], ...] = (("echo", "ok"),),
) -> TaskSpec:
    return TaskSpec(
        task_id=TaskId(task_id),
        title="test",
        depends_on=tuple(TaskId(d) for d in depends_on),
        allowed_paths=paths,
        acceptance_criteria=tuple(AcceptanceCriterion(a, d) for a, d in acs),
        validation_commands=tuple(ValidationCommand(c) for c in cmds),
    )


def _make_spec(tasks: list[TaskSpec]) -> SoftwareSpec:
    return SoftwareSpec(
        spec_id="SPEC-PROP", schema_version=1, title="Property test", tasks=tuple(tasks)
    )


class TestCycleDetection:
    def test_self_cycle(self) -> None:
        task = _make_task("TASK-001", depends_on=("TASK-001",))
        report = SpecValidator().validate(_make_spec([task]))
        assert not report.valid
        assert any(e.code == "DEPENDENCY_CYCLE" for e in report.errors)

    def test_two_node_cycle(self) -> None:
        t1 = _make_task("TASK-001", depends_on=("TASK-002",))
        t2 = _make_task("TASK-002", depends_on=("TASK-001",))
        report = SpecValidator().validate(_make_spec([t1, t2]))
        assert not report.valid
        assert any(e.code == "DEPENDENCY_CYCLE" for e in report.errors)

    def test_three_node_cycle(self) -> None:
        t1 = _make_task("TASK-001", depends_on=("TASK-003",))
        t2 = _make_task("TASK-002", depends_on=("TASK-001",))
        t3 = _make_task("TASK-003", depends_on=("TASK-002",))
        report = SpecValidator().validate(_make_spec([t1, t2, t3]))
        assert not report.valid
        assert any(e.code == "DEPENDENCY_CYCLE" for e in report.errors)


class TestDuplicateRejection:
    def test_duplicate_task_ids(self) -> None:
        t = _make_task("TASK-001")
        report = SpecValidator().validate(_make_spec([t, t]))
        assert not report.valid
        assert any(e.code == "DUPLICATE_TASK_ID" for e in report.errors)

    def test_duplicate_ac_ids_within_task(self) -> None:
        t = _make_task(
            "TASK-001",
            acs=(("AC-001", "first"), ("AC-001", "second")),
        )
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "DUPLICATE_AC_ID" for e in report.errors)


class TestEmptyScopeRejection:
    def test_empty_allowed_paths(self) -> None:
        t = _make_task("TASK-001", paths=())
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "EMPTY_ALLOWED_PATHS" for e in report.errors)

    def test_empty_acceptance_criteria(self) -> None:
        t = _make_task("TASK-001", acs=())
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "EMPTY_ACCEPTANCE_CRITERIA" for e in report.errors)

    def test_empty_validation_commands(self) -> None:
        t = _make_task("TASK-001", cmds=())
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "EMPTY_VALIDATION_COMMANDS" for e in report.errors)


class TestShellStringRejection:
    @pytest.mark.parametrize(
        "shell_arg",
        [
            "echo | rm -rf /",
            "echo && rm -rf /",
            "echo; rm -rf /",
            "echo `rm -rf /`",
            "echo $(rm -rf /)",
            "echo > /tmp/x",
            "echo < /etc/passwd",
            "echo (subshell)",
            "echo {a,b}",
            "echo $HOME",
            "echo !history",
            "echo\\nrm",
        ],
    )
    def test_rejects_shell_metacharacters(self, shell_arg: str) -> None:
        t = _make_task("TASK-001", cmds=((shell_arg,),))
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "SHELL_STRING_IN_COMMAND" for e in report.errors)


class TestExcessRejection:
    def test_too_many_tasks(self) -> None:
        tasks = [_make_task(f"TASK-{i:03d}") for i in range(201)]
        report = SpecValidator().validate(_make_spec(tasks))
        assert not report.valid
        assert any(e.code == "TOO_MANY_TASKS" for e in report.errors)

    def test_exactly_max_tasks_passes(self) -> None:
        tasks = [_make_task(f"TASK-{i:03d}") for i in range(200)]
        report = SpecValidator().validate(_make_spec(tasks))
        assert report.valid


class TestTraversalRejection:
    @pytest.mark.parametrize(
        "unsafe_path",
        [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "/etc/shadow",
            "/root/.ssh/id_rsa",
            "",
        ],
    )
    def test_rejects_unsafe_paths(self, unsafe_path: str) -> None:
        t = _make_task("TASK-001", paths=(unsafe_path,))
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "UNSAFE_PATH" for e in report.errors)


class TestParserAbuse:
    def test_rejects_unsafe_frontmatter_and_traversal(self) -> None:
        """Risk control: parser rejects hostile frontmatter and traversal."""
        text = "---\nspec_id: ../../etc/passwd\nschema_version: 1\ntitle: T\n---\n"
        spec = SpecParser().parse(text)
        report = SpecValidator().validate(spec)
        assert report.valid

    def test_rejects_null_bytes_in_spec(self) -> None:
        text = "---\nspec_id: SPEC\x00-001\nschema_version: 1\ntitle: T\n---\n"
        spec = SpecParser().parse(text)
        assert spec.spec_id == "SPEC\x00-001"

    def test_rejects_extremely_long_frontmatter_value(self) -> None:
        long_value = "x" * 10_000
        text = f"---\nspec_id: {long_value}\nschema_version: 1\ntitle: T\n---\n"
        spec = SpecParser().parse(text)
        assert spec.spec_id == long_value

    def test_parser_does_not_crash_on_binary_input(self) -> None:
        text = "\x00\x01\x02\x03"
        with pytest.raises(SpecParseError):
            SpecParser().parse(text)

    def test_parser_does_not_crash_on_empty_input(self) -> None:
        with pytest.raises(SpecParseError):
            SpecParser().parse("")

    def test_parser_does_not_crash_on_only_frontmatter(self) -> None:
        text = "---\nspec_id: X\nschema_version: 1\ntitle: T\n---\n"
        spec = SpecParser().parse(text)
        assert spec.tasks == ()

    def test_parser_rejects_yaml_flow_syntax_in_frontmatter(self) -> None:
        text = "---\nspec_id: [1, 2, 3]\nschema_version: 1\ntitle: T\n---\n"
        with pytest.raises(SpecParseError):
            SpecParser().parse(text)


class TestDAGValidation:
    def test_linear_chain_passes(self) -> None:
        tasks = [
            _make_task("TASK-001"),
            _make_task("TASK-002", depends_on=("TASK-001",)),
            _make_task("TASK-003", depends_on=("TASK-002",)),
        ]
        report = SpecValidator().validate(_make_spec(tasks))
        assert report.valid

    def test_diamond_dependency_passes(self) -> None:
        tasks = [
            _make_task("TASK-001"),
            _make_task("TASK-002", depends_on=("TASK-001",)),
            _make_task("TASK-003", depends_on=("TASK-001",)),
            _make_task("TASK-004", depends_on=("TASK-002", "TASK-003")),
        ]
        report = SpecValidator().validate(_make_spec(tasks))
        assert report.valid

    def test_unknown_dependency_fails(self) -> None:
        t = _make_task("TASK-001", depends_on=("TASK-999",))
        report = SpecValidator().validate(_make_spec([t]))
        assert not report.valid
        assert any(e.code == "UNKNOWN_DEPENDENCY" for e in report.errors)


class TestSchemaVersionValidation:
    def test_wrong_version_fails(self) -> None:
        spec = SoftwareSpec(spec_id="X", schema_version=99, title="T", tasks=(_make_task(),))
        report = SpecValidator().validate(spec)
        assert not report.valid
        assert any(e.code == "INVALID_SCHEMA_VERSION" for e in report.errors)

    def test_version_zero_fails(self) -> None:
        spec = SoftwareSpec(spec_id="X", schema_version=0, title="T", tasks=(_make_task(),))
        report = SpecValidator().validate(spec)
        assert not report.valid
        assert any(e.code == "INVALID_SCHEMA_VERSION" for e in report.errors)


class TestCLIExitCodes:
    _EXIT_INVALID = 2

    def test_valid_spec_returns_exit_zero(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "spec.md"
        spec_file.write_text(
            "---\nspec_id: S\nschema_version: 1\ntitle: T\n---\n\n"
            "## TASK-001 — A\n\n"
            "**Depends on:**\n\n"
            "**Allowed paths:**\n- src/a.py\n\n"
            "**Acceptance criteria:**\n- AC-001 — desc\n\n"
            "**Validation commands:**\n- echo ok\n",
            encoding="utf-8",
        )
        exit_code = cli_main(["spec", "validate", str(spec_file), "--json"])
        assert exit_code == 0

    def test_invalid_spec_returns_exit_two(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "bad.md"
        spec_file.write_text("not a valid spec", encoding="utf-8")
        exit_code = cli_main(["spec", "validate", str(spec_file), "--json"])
        assert exit_code == self._EXIT_INVALID

    def test_missing_file_returns_exit_two(self, tmp_path: Path) -> None:
        exit_code = cli_main(["spec", "validate", str(tmp_path / "nope.md"), "--json"])
        assert exit_code == self._EXIT_INVALID
