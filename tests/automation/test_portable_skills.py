from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SETUP_CHECKS = 7
POLICY_DENIED = 2


def _frontmatter_keys(path: Path) -> set[str]:
    block = path.read_text(encoding="utf-8").split("---\n", 2)[1]
    return {line.split(":", 1)[0] for line in block.splitlines() if ":" in line}


def test_both_hosts_reference_canonical_skills() -> None:
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"

    canonical_run = ROOT / ".agents/skills/run-task/SKILL.md"
    claude_run = ROOT / ".claude/skills/run-task"
    assert claude_run.is_symlink()
    assert claude_run.resolve() == canonical_run.parent.resolve()
    assert _frontmatter_keys(canonical_run) == {"name", "description"}
    run_text = canonical_run.read_text(encoding="utf-8")
    assert "git commit" not in run_text
    assert "ruff" not in run_text
    assert "gh pr" not in run_text

    canonical_new = ROOT / ".agents/skills/new-task/SKILL.md"
    claude_new = ROOT / ".claude/skills/new-task/SKILL.md"
    assert _frontmatter_keys(canonical_new) == {"name", "description"}
    assert ".agents/skills/new-task/SKILL.md" in claude_new.read_text(encoding="utf-8")
    assert "disable-model-invocation: true" in claude_new.read_text(encoding="utf-8")
    assert "allow_implicit_invocation: false" in (
        ROOT / ".agents/skills/new-task/agents/openai.yaml"
    ).read_text(encoding="utf-8")


def test_host_adapters_cannot_override_canonical_policy() -> None:
    result = subprocess.run(  # noqa: S603 - fixed local validator command
        [sys.executable, "scripts/agent_automation/validate_setup.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("PASS") == EXPECTED_SETUP_CHECKS
    for path in (
        ROOT / ".claude/settings.json",
        ROOT / ".codex/hooks.json",
        ROOT / ".claude/agents/security-reviewer.md",
        ROOT / ".codex/agents/security-reviewer.toml",
    ):
        assert "TODO" not in path.read_text(encoding="utf-8")


def test_new_task_dry_run_stays_planned_and_unpinned() -> None:
    numbers = [
        int(match.group(1))
        for path in (ROOT / "docs/planejamento").glob("task[0-9]*.md")
        if (match := re.fullmatch(r"task([0-9]+)\.md", path.name)) is not None
    ]
    next_number = max(numbers) + 1
    latest_id = f"TASK-{max(numbers):03d}"
    result = subprocess.run(  # noqa: S603 - fixed local scaffolder command
        [
            sys.executable,
            ".agents/skills/new-task/scripts/scaffold_task.py",
            "--task-id",
            f"TASK-{next_number:03d}",
            "--title",
            "Dry-run contract",
            "--release",
            "V0.1",
            "--risk-level",
            "high",
            "--depends-on",
            latest_id,
            "--dry-run",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "status: planned" in result.stdout
    assert 'baseline_commit: "TO_BE_PINNED"' in result.stdout
    assert "risk_level: high" in result.stdout
    assert "status: ready" not in result.stdout


def test_new_task_rejects_symlinked_planning_directory(tmp_path: Path) -> None:
    fake_root = tmp_path / "repository"
    script_dir = fake_root / ".agents/skills/new-task/scripts"
    script_dir.mkdir(parents=True)
    shutil.copyfile(
        ROOT / ".agents/skills/new-task/scripts/scaffold_task.py",
        script_dir / "scaffold_task.py",
    )
    (fake_root / "AGENTS.md").write_text("test\n", encoding="utf-8")
    (fake_root / "docs").mkdir()
    external = tmp_path / "external-planning"
    external.mkdir()
    shutil.copyfile(
        ROOT / "docs/planejamento/task-template.md",
        external / "task-template.md",
    )
    (fake_root / "docs/planejamento").symlink_to(external, target_is_directory=True)

    result = subprocess.run(  # noqa: S603 - isolated copy of the fixed repository script
        [
            sys.executable,
            str(script_dir / "scaffold_task.py"),
            "--task-id",
            "TASK-001",
            "--title",
            "Rejected external target",
            "--release",
            "V0.1",
            "--risk-level",
            "high",
        ],
        cwd=fake_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == POLICY_DENIED
    assert "real repository directory" in result.stderr
    assert not (external / "task1.md").exists()
