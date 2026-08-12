#!/usr/bin/env python3
"""Validate portable agent automation without starting either agent host."""

from __future__ import annotations

import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import cast


class SetupError(ValueError):
    """Raised when a host adapter diverges from the canonical configuration."""


def _root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "AGENTS.md").is_file():
        raise SetupError("repository root could not be verified")
    return root


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise SetupError("frontmatter is missing")
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"')
    return fields


def _json(path: Path) -> dict[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SetupError("JSON adapter must be an object")
    return cast(dict[str, object], payload)


def _validate_instructions(root: Path) -> None:
    if (root / "CLAUDE.md").read_text(encoding="utf-8").strip() != "@AGENTS.md":
        raise SetupError("Claude instructions must import AGENTS.md")
    if "Automação agnóstica de agente" not in (root / "AGENTS.md").read_text(encoding="utf-8"):
        raise SetupError("canonical automation rules are missing")


def _validate_skill(root: Path, skill_name: str) -> None:
    canonical = root / ".agents" / "skills" / skill_name / "SKILL.md"
    fields = _frontmatter(canonical)
    if set(fields) != {"name", "description"} or fields["name"] != skill_name:
        raise SetupError("canonical skill frontmatter is not portable")
    if "TODO" in canonical.read_text(encoding="utf-8"):
        raise SetupError("canonical skill still contains scaffold placeholders")
    claude = root / ".claude" / "skills" / skill_name
    if skill_name == "run-task":
        if not claude.is_symlink() or claude.resolve() != canonical.parent.resolve():
            raise SetupError("Claude run-task must resolve to the canonical skill")
        return
    adapter = claude / "SKILL.md"
    adapter_text = adapter.read_text(encoding="utf-8")
    if ".agents/skills/new-task/SKILL.md" not in adapter_text:
        raise SetupError("Claude new-task adapter does not reference the canonical skill")
    if _frontmatter(adapter).get("disable-model-invocation") != "true":
        raise SetupError("Claude new-task must disable implicit invocation")
    openai_metadata = (canonical.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if "allow_implicit_invocation: false" not in openai_metadata:
        raise SetupError("Codex new-task must disable implicit invocation")


def _hook_adapters(config: dict[str, object]) -> tuple[tuple[str, str], ...]:
    hooks_value = config.get("hooks")
    if not isinstance(hooks_value, dict):
        raise SetupError("hooks object is missing")
    hooks = cast(dict[str, object], hooks_value)
    adapters: list[tuple[str, str]] = []
    for event in ("PreToolUse", "PostToolUse"):
        groups_value = hooks.get(event)
        if not isinstance(groups_value, list):
            raise SetupError("each required hook event must have one matcher group")
        groups = cast(list[object], groups_value)
        if len(groups) != 1 or not isinstance(groups[0], dict):
            raise SetupError("each required hook event must have one matcher group")
        group = cast(dict[str, object], groups[0])
        matcher = group.get("matcher")
        if not isinstance(matcher, str):
            raise SetupError("hook matcher is missing")
        handlers_value = group.get("hooks")
        handlers = cast(list[object], handlers_value) if isinstance(handlers_value, list) else []
        valid_handlers = len(handlers) == 1 and isinstance(handlers[0], dict)
        if not valid_handlers:
            raise SetupError("each hook matcher must have one command handler")
        handler = cast(dict[str, object], handlers[0])
        command = handler.get("command")
        if not isinstance(command, str):
            raise SetupError("hook command is missing")
        adapters.append((matcher, command))
    return tuple(adapters)


def _validate_hooks(root: Path, host: str) -> None:
    path = root / (".claude/settings.json" if host == "claude" else ".codex/hooks.json")
    adapters = _hook_adapters(_json(path))
    expected_phases = ("--phase pre", "--phase post")
    expected_matcher = (
        "^(Edit|Write|MultiEdit|Bash)$"
        if host == "claude"
        else "^(apply_patch|Edit|Write|Bash|exec_command)$"
    )
    for (matcher, command), phase in zip(adapters, expected_phases, strict=True):
        if matcher != expected_matcher:
            raise SetupError("host hook does not cover its complete mutation-tool set")
        if "scripts/agent_automation/hook.py" not in command or f"--host {host}" not in command:
            raise SetupError("host hook bypasses the canonical policy engine")
        if phase not in command or "--fix" in command:
            raise SetupError("host hook has unsafe phase or auto-fix behavior")


def _validate_reviewer(root: Path, reviewer: str) -> None:
    canonical_relative = f".agents/reviewers/{reviewer}.md"
    canonical = root / canonical_relative
    canonical_text = canonical.read_text(encoding="utf-8")
    if "never edit" not in canonical_text or "SEVERITY:" not in canonical_text:
        raise SetupError("canonical reviewer lacks authority or output contract")

    claude = root / ".claude" / "agents" / f"{reviewer}.md"
    claude_fields = _frontmatter(claude)
    if "model" in claude_fields or claude_fields.get("permissionMode") != "plan":
        raise SetupError("Claude reviewer overrides model or write policy")
    claude_tools = {tool.strip() for tool in claude_fields.get("tools", "").split(",")}
    denied_tools = {tool.strip() for tool in claude_fields.get("disallowedTools", "").split(",")}
    if "Bash" in claude_tools or not {"Edit", "Write", "MultiEdit", "Bash"} <= denied_tools:
        raise SetupError("Claude reviewer lacks read-only diff inspection controls")
    if canonical_relative not in claude.read_text(encoding="utf-8"):
        raise SetupError("Claude reviewer bypasses the canonical checklist")

    codex = tomllib.loads(
        (root / ".codex" / "agents" / f"{reviewer}.toml").read_text(encoding="utf-8")
    )
    if "model" in codex or "model_reasoning_effort" in codex:
        raise SetupError("Codex reviewer must inherit the session model")
    if codex.get("sandbox_mode") != "read-only":
        raise SetupError("Codex reviewer is not read-only")
    instructions = codex.get("developer_instructions")
    if not isinstance(instructions, str) or canonical_relative not in instructions:
        raise SetupError("Codex reviewer bypasses the canonical checklist")


def main() -> int:
    try:
        root = _root()
        checks: tuple[tuple[str, Callable[[], None]], ...] = (
            (
                "instructions: Claude imports AGENTS; Codex uses it natively",
                lambda: _validate_instructions(root),
            ),
            (
                "skill run-task: shared canonical workflow",
                lambda: _validate_skill(root, "run-task"),
            ),
            (
                "skill new-task: shared workflow, explicit invocation",
                lambda: _validate_skill(root, "new-task"),
            ),
            ("hooks Claude: canonical pre/post engine", lambda: _validate_hooks(root, "claude")),
            ("hooks Codex: canonical pre/post engine", lambda: _validate_hooks(root, "codex")),
            (
                "reviewer security: canonical and read-only in both hosts",
                lambda: _validate_reviewer(root, "security-reviewer"),
            ),
            (
                "reviewer architecture: canonical and read-only in both hosts",
                lambda: _validate_reviewer(root, "architecture-boundary-reviewer"),
            ),
        )
        for label, check in checks:
            check()
            print(f"PASS {label}")
        return 0
    except (OSError, SetupError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        print(f"FAIL portable agent setup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
