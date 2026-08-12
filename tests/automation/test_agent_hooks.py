from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DENIED = 2
sys.path.insert(0, str(ROOT))

from scripts.agent_automation.hook import (  # noqa: E402
    MAX_INPUT_BYTES,
    PolicyError,
    TaskPolicy,
    ToolInvocation,
    audit_changed_scope,
    evaluate_pre,
    read_payload,
)


def test_scope_hook_denies_escape_secret_and_mutating_shell(tmp_path: Path) -> None:
    policy = TaskPolicy("TASK-TEST", ("AGENTS.md", "src/**"))
    allowed = (
        ToolInvocation("Write", {"file_path": "AGENTS.md"}),
        ToolInvocation("apply_patch", {"command": "*** Update File: AGENTS.md\n*** End Patch"}),
    )
    for invocation in allowed:
        assert evaluate_pre(invocation, policy, tmp_path)

    denied = (
        ToolInvocation("Write", {"file_path": "../escape"}),
        ToolInvocation("Write", {"file_path": ".env.production"}),
        ToolInvocation(
            "apply_patch", {"command": "*** Update File: AGENTS.md\n*** Move to: ../escape"}
        ),
        ToolInvocation("Bash", {"command": "sed -i backup AGENTS.md"}),
        ToolInvocation("Bash", {"command": "uv run ruff check --fix src"}),
        ToolInvocation("Bash", {"command": "git reset --hard HEAD"}),
        ToolInvocation("Bash", {"command": "python3 -c \"open('../outside', 'w')\""}),
        ToolInvocation("Bash", {"command": "/bin/rm AGENTS.md"}),
        ToolInvocation("Bash", {"command": "git config core.hooksPath .githooks"}),
        ToolInvocation("Bash", {"command": "git branch -D dev"}),
        ToolInvocation("Bash", {"command": "git branch --list -D dev"}),
        ToolInvocation("Bash", {"command": "git remote set-url origin invalid"}),
        ToolInvocation("Bash", {"command": "git remote -v set-url origin invalid"}),
        ToolInvocation("Bash", {"command": "git diff --no-index AGENTS.md /etc/passwd"}),
        ToolInvocation("Bash", {"command": "rtk read .env"}),
        ToolInvocation("Bash", {"command": "rtk read /tmp/auth.json"}),
        ToolInvocation("Bash", {"command": "head $HOME/.config/gh/hosts.yml"}),
        ToolInvocation("Bash", {"command": "head ~/.config/gh/hosts.yml"}),
        ToolInvocation("Bash", {"command": "uv run python scripts/custom_writer.py"}),
        ToolInvocation("Bash", {"command": "uv run ruff check --fix=true src"}),
        ToolInvocation("Bash", {"command": "uv run ruff check --output-file=/tmp/out src"}),
        ToolInvocation("Bash", {"command": "uv run pyright --createstub unsafe"}),
        ToolInvocation("Bash", {"command": "uv run pip-audit --fix"}),
        ToolInvocation("Bash", {"command": "uv run pip-audit --output=/tmp/out"}),
        ToolInvocation("Bash", {"command": "uv run pytest /tmp/attacker_test.py"}),
        ToolInvocation("Bash", {"command": "uv run pytest a/../../tmp/attacker.py"}),
        ToolInvocation("Bash", {"command": "uv run pytest --junitxml=/tmp/out.xml"}),
        ToolInvocation("Bash", {"command": "uv run pytest --junit-xml=/tmp/out.xml"}),
        ToolInvocation("Bash", {"command": "uv run pytest --basetemp=/tmp/victim"}),
        ToolInvocation("Bash", {"command": "rg --pre python pattern"}),
        ToolInvocation("Bash", {"command": "rg --follow token alias"}),
        ToolInvocation("Bash", {"command": "sed -n '1e touch unsafe' AGENTS.md"}),
        ToolInvocation(
            "Bash",
            {
                "command": "gh pr create --draft --base dev --head task/TASK-TEST-x "
                "--repo victim/repo"
            },
        ),
        ToolInvocation(
            "Bash",
            {"command": "gh pr create --draft --base dev --base main --head task/TASK-TEST-x"},
        ),
        ToolInvocation(
            "Bash",
            {
                "command": "gh pr create --draft --base dev --head task/TASK-TEST-x "
                "--body-file /etc/passwd"
            },
        ),
        ToolInvocation("Write", {"file_path": ".claude/settings.local.json"}),
        ToolInvocation("Write", {"file_path": "CLAUDE.local.md"}),
    )
    for invocation in denied:
        with pytest.raises(PolicyError):
            evaluate_pre(invocation, policy, tmp_path)


def test_scope_hook_rejects_symlink_even_when_target_is_inside_scope(tmp_path: Path) -> None:
    target = tmp_path / "src"
    target.mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)
    policy = TaskPolicy("TASK-TEST", ("**",))

    with pytest.raises(PolicyError, match="symlink"):
        evaluate_pre(ToolInvocation("Write", {"file_path": "alias/module.py"}), policy, tmp_path)


def test_scope_hook_requires_checkout_hooks_disabled_for_commit(tmp_path: Path) -> None:
    policy = TaskPolicy("TASK-TEST", ("**",))
    with pytest.raises(PolicyError, match="disable checkout hooks"):
        evaluate_pre(ToolInvocation("Bash", {"command": "git commit -m change"}), policy, tmp_path)

    assert (
        evaluate_pre(
            ToolInvocation(
                "Bash",
                {"command": "git -c core.hooksPath=/dev/null commit -m 'TASK-TEST: change'"},
            ),
            policy,
            tmp_path,
        )
        == ()
    )


def test_hook_payload_size_is_bounded() -> None:
    with pytest.raises(PolicyError, match="size limit"):
        read_payload(io.BytesIO(b"{" + b"x" * MAX_INPUT_BYTES + b"}"))


def test_real_claude_and_codex_payloads_are_equivalent_and_fail_closed() -> None:
    script = ROOT / "scripts/agent_automation/hook.py"
    cases = (
        ("claude", {"tool_name": "Write", "tool_input": {"file_path": "AGENTS.md"}}, 0),
        (
            "codex",
            {
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Update File: AGENTS.md\n"},
            },
            0,
        ),
        (
            "codex",
            {"tool_name": "exec_command", "tool_input": {"cmd": "git status --short"}},
            0,
        ),
        ("claude", {"tool_name": "Bash", "tool_input": {"command": "/bin/rm AGENTS.md"}}, 2),
        (
            "codex",
            {
                "tool_name": "exec_command",
                "tool_input": {"cmd": 'python3 -c \'open("x", "w")\''},
            },
            2,
        ),
    )
    for host, payload, expected in cases:
        result = subprocess.run(  # noqa: S603 - fixed repository hook command
            [sys.executable, str(script), "--host", host, "--phase", "pre"],
            cwd=ROOT,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == expected
        if expected == DENIED:
            assert result.stderr.startswith("agent-policy: denied:")
            tool_input = payload["tool_input"]
            assert isinstance(tool_input, dict)
            command = tool_input.get("command", tool_input.get("cmd"))
            assert isinstance(command, str)
            assert command not in result.stderr


def test_scope_audit_keeps_committed_changes_visible_from_baseline(tmp_path: Path) -> None:
    def git(*arguments: str) -> str:
        git_executable = shutil.which("git")
        assert git_executable is not None
        result = subprocess.run(  # noqa: S603 - fixed Git executable in isolated test repo
            [git_executable, "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip()

    (tmp_path / "docs/planejamento").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("test\n", encoding="utf-8")
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("add", "--", "AGENTS.md")
    git("commit", "-q", "-m", "baseline")
    baseline = git("rev-parse", "HEAD")
    task_path = "docs/planejamento/task1.md"
    (tmp_path / task_path).write_text("status: ready\n", encoding="utf-8")
    git("add", "--", task_path)
    git("commit", "-q", "-m", "TASK-001: define portable agent automation contract")
    (tmp_path / "forbidden.txt").write_text("must remain visible\n", encoding="utf-8")
    git("add", "--", "forbidden.txt")
    git("commit", "-q", "-m", "hide forbidden path at HEAD")

    policy = TaskPolicy("TASK-001", ("AGENTS.md",), baseline, task_path)
    with pytest.raises(PolicyError, match="outside the active task scope"):
        audit_changed_scope(tmp_path, policy)


def test_scope_audit_rejects_activation_path_changed_after_activation(tmp_path: Path) -> None:
    git_executable = shutil.which("git")
    assert git_executable is not None

    def git(*arguments: str) -> str:
        result = subprocess.run(  # noqa: S603 - isolated Git repository
            [git_executable, "-c", "core.hooksPath=/dev/null", *arguments],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout.strip()

    planning = tmp_path / "docs/planejamento"
    planning.mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("test\n", encoding="utf-8")
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("add", "--", "AGENTS.md")
    git("commit", "-q", "-m", "baseline")
    baseline = git("rev-parse", "HEAD")
    task_path = "docs/planejamento/task1.md"
    (tmp_path / task_path).write_text("status: ready\n", encoding="utf-8")
    git("add", "--", task_path)
    git("commit", "-q", "-m", "TASK-001: activate contract")
    (tmp_path / task_path).write_text("status: changed\n", encoding="utf-8")

    policy = TaskPolicy("TASK-001", ("AGENTS.md",), baseline, task_path)
    with pytest.raises(PolicyError, match="outside the active task scope"):
        audit_changed_scope(tmp_path, policy)
