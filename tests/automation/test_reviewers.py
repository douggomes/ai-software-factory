from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEWERS = ("security-reviewer", "architecture-boundary-reviewer")


def _frontmatter(path: Path) -> dict[str, str]:
    block = path.read_text(encoding="utf-8").split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip()
    return fields


def test_reviewers_are_model_agnostic_and_read_only() -> None:
    for reviewer in REVIEWERS:
        canonical = f".agents/reviewers/{reviewer}.md"
        canonical_text = (ROOT / canonical).read_text(encoding="utf-8")
        assert "never edit" in canonical_text
        assert "SEVERITY:" in canonical_text

        claude_path = ROOT / ".claude/agents" / f"{reviewer}.md"
        claude_fields = _frontmatter(claude_path)
        assert "model" not in claude_fields
        assert claude_fields["permissionMode"] == "plan"
        assert "Bash" not in set(claude_fields["tools"].split(", "))
        assert {"Edit", "Write", "MultiEdit", "Bash"} <= set(
            claude_fields["disallowedTools"].split(", ")
        )
        assert canonical in claude_path.read_text(encoding="utf-8")

        codex = tomllib.loads(
            (ROOT / ".codex/agents" / f"{reviewer}.toml").read_text(encoding="utf-8")
        )
        assert "model" not in codex
        assert "model_reasoning_effort" not in codex
        assert codex["sandbox_mode"] == "read-only"
        assert canonical in codex["developer_instructions"]


def test_reviewers_share_output_contract_without_host_duplication() -> None:
    for reviewer in REVIEWERS:
        canonical = (ROOT / ".agents/reviewers" / f"{reviewer}.md").read_text(encoding="utf-8")
        assert canonical.count("SEVERITY:") == 1
        for adapter in (
            ROOT / ".claude/agents" / f"{reviewer}.md",
            ROOT / ".codex/agents" / f"{reviewer}.toml",
        ):
            assert "REMEDIATION:" not in adapter.read_text(encoding="utf-8")
