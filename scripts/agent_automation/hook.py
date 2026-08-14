#!/usr/bin/env python3
"""Model-agnostic PreToolUse/PostToolUse policy for Claude Code and Codex."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final, cast

MAX_INPUT_BYTES: Final[int] = 1_048_576
QUALITY_TIMEOUT_SECONDS: Final[int] = 60
CONTROL_CHARACTER_LIMIT: Final[int] = 32
# User-owned local controls are globally ignored in this checkout. Direct writes and every
# allowlisted shell argv still reject them; omitting them here preserves pre-task user state.
PREEXISTING_HOST_LOCAL_PATHS: Final[frozenset[str]] = frozenset(
    {".claude/settings.local.json", "CLAUDE.local.md", ".claude/active-task"}
)
_ACTIVE_TASK_MARKER: Final[str] = ".claude/active-task"
_FRONTMATTER = re.compile(r"\A---\n(?P<body>.*?)\n---\n", re.DOTALL)
_ALLOWED_SECTION = re.compile(
    r"^## Arquivos permitidos\n(?P<body>.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL
)
_PATCH_PATH = re.compile(
    r"^\*\*\* (?:(?:Add|Update|Delete) File|Move to): (?P<path>.+)$", re.MULTILINE
)
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_SHELL_CONTROL = re.compile(r"[;&|<>`~\r\n]|\$")
_READ_ONLY_GIT = frozenset(
    {
        "branch",
        "cat-file",
        "check-ignore",
        "describe",
        "diff",
        "log",
        "ls-files",
        "merge-base",
        "remote",
        "rev-parse",
        "show",
        "status",
    }
)
_PYTHON_SCRIPTS = frozenset(
    {
        "scripts/agent_automation/hook.py",
        "scripts/agent_automation/validate_setup.py",
        "scripts/show_manual_validation.py",
        "scripts/validate_tasks.py",
    }
)
_UV_RUN_TOOLS = frozenset(
    {"detect-secrets", "lint-imports", "pip-audit", "pyright", "pytest", "ruff"}
)


class PolicyError(ValueError):
    """A sanitized policy failure safe to return to an agent host."""


@dataclass(frozen=True, slots=True)
class TaskPolicy:
    task_id: str
    allowed_patterns: tuple[str, ...]
    baseline_commit: str = ""
    task_path: str = ""


_NO_TASK_POLICY: Final[TaskPolicy] = TaskPolicy(task_id="", allowed_patterns=())


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    tool_name: str
    tool_input: dict[str, object]


def _repository_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "AGENTS.md").is_file() or not (root / ".git").exists():
        raise PolicyError("repository root could not be verified")
    return root


def _frontmatter_value(text: str, key: str) -> str | None:
    match = _FRONTMATTER.search(text)
    if match is None:
        return None
    prefix = f"{key}:"
    for line in match["body"].splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip().strip('"')
    return None


def _parse_task_policy(root: Path, task_path: Path, text: str) -> TaskPolicy:
    section = _ALLOWED_SECTION.search(text)
    if section is None:
        raise PolicyError("ready task has no allowed-path contract")
    patterns = tuple(re.findall(r"^- `([^`]+)`$", section["body"], re.MULTILINE))
    if not patterns or any(Path(pattern).is_absolute() for pattern in patterns):
        raise PolicyError("ready task has an invalid allowed-path contract")
    task_id = _frontmatter_value(text, "task_id")
    if task_id is None:
        raise PolicyError("ready task identity is missing")
    if task_path.name != f"task{int(task_id.removeprefix('TASK-'))}.md":
        raise PolicyError("ready task identity is inconsistent")
    baseline_commit = _frontmatter_value(text, "baseline_commit")
    if baseline_commit is None or _SHA.fullmatch(baseline_commit) is None:
        raise PolicyError("ready task baseline is invalid")
    return TaskPolicy(
        task_id=task_id,
        allowed_patterns=patterns,
        baseline_commit=baseline_commit,
        task_path=task_path.relative_to(root).as_posix(),
    )


def load_ready_tasks(root: Path) -> tuple[TaskPolicy, ...]:
    planning = root / "docs" / "planejamento"
    ready: list[tuple[Path, str]] = []
    for task_path in sorted(planning.glob("task[0-9]*.md")):
        text = task_path.read_text(encoding="utf-8")
        if _frontmatter_value(text, "status") == "ready":
            ready.append((task_path, text))
    if not ready:
        raise PolicyError("no ready task is available")
    return tuple(_parse_task_policy(root, task_path, text) for task_path, text in ready)


def _select_active_policy(root: Path, policies: tuple[TaskPolicy, ...]) -> TaskPolicy:
    if len(policies) == 1:
        return policies[0]
    seen_patterns: dict[str, str] = {}
    for policy in policies:
        for pattern in policy.allowed_patterns:
            if pattern in seen_patterns:
                raise PolicyError("ready tasks have overlapping allowed paths")
            seen_patterns[pattern] = policy.task_id
    marker = root / _ACTIVE_TASK_MARKER
    if not marker.is_file():
        raise PolicyError("multiple ready tasks require an active-task marker")
    selected_id = marker.read_text(encoding="utf-8").strip()
    matches = [policy for policy in policies if policy.task_id == selected_id]
    if len(matches) != 1:
        raise PolicyError("active-task marker does not match a ready task")
    return matches[0]


def load_ready_policy(root: Path) -> TaskPolicy:
    return _select_active_policy(root, load_ready_tasks(root))


def read_payload(stream: BinaryIO) -> dict[str, object]:
    payload_bytes = stream.read(MAX_INPUT_BYTES + 1)
    if not payload_bytes or len(payload_bytes) > MAX_INPUT_BYTES:
        raise PolicyError("hook payload is empty or exceeds the size limit")
    try:
        payload: object = json.loads(payload_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError("hook payload is not valid JSON") from error
    if not isinstance(payload, dict):
        raise PolicyError("hook payload must be a JSON object")
    payload_object = cast(dict[object, object], payload)
    if not all(isinstance(key, str) for key in payload_object):
        raise PolicyError("hook payload must use string keys")
    return cast(dict[str, object], payload_object)


def _normalize_invocation(payload: dict[str, object], host: str) -> ToolInvocation:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        raise PolicyError("hook payload is missing tool information")
    tool_input_object = cast(dict[object, object], tool_input)
    if not all(isinstance(key, str) for key in tool_input_object):
        raise PolicyError("tool input must use string keys")
    supported = (
        {"Edit", "Write", "MultiEdit", "Bash"}
        if host == "claude"
        else {"apply_patch", "Bash", "exec_command"}
    )
    if tool_name not in supported:
        raise PolicyError("host supplied an unsupported tool")
    if host == "codex" and tool_name == "exec_command":
        tool_input_object["command"] = tool_input_object.get("cmd")
        tool_name = "Bash"
    return ToolInvocation(
        tool_name=tool_name,
        tool_input=cast(dict[str, object], tool_input_object),
    )


def _candidate_path(root: Path, raw_path: str) -> tuple[Path, str]:
    if not raw_path or any(ord(char) < CONTROL_CHARACTER_LIMIT for char in raw_path):
        raise PolicyError("tool path contains invalid characters")
    root = root.resolve()
    raw = Path(raw_path)
    lexical = raw if raw.is_absolute() else root / raw
    try:
        relative = Path(os.path.abspath(lexical)).relative_to(root)
    except ValueError as error:
        raise PolicyError("tool path escapes the repository") from error
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise PolicyError("symlink paths are not writable")
    relative_text = relative.as_posix()
    if relative_text == ".":
        raise PolicyError("repository root is not a writable target")
    return current, relative_text


def _is_hard_forbidden(relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    return any(part.startswith(".env") for part in path.parts) or path.name in {
        "CLAUDE.local.md",
        "auth.json",
        "id_ed25519",
        "id_rsa",
        "settings.local.json",
    }


def _contains_sensitive_reference(value: str) -> bool:
    return any(
        segment.startswith(".env")
        or segment in {"auth.json", "id_ed25519", "id_rsa", "settings.local.json"}
        for segment in re.split(r"[/:=]", value)
    ) or value.endswith("CLAUDE.local.md")


def _require_allowed_path(root: Path, policy: TaskPolicy, raw_path: str) -> tuple[Path, str]:
    candidate, relative = _candidate_path(root, raw_path)
    if _is_hard_forbidden(relative):
        raise PolicyError("sensitive path is always forbidden")
    path = PurePosixPath(relative)
    if not any(path.full_match(pattern) for pattern in policy.allowed_patterns):
        raise PolicyError("tool path is outside the active task scope")
    return candidate, relative


def _require_changed_path(root: Path, policy: TaskPolicy, raw_path: str) -> None:
    """Audit a Git path, allowing only an in-repository canonical adapter symlink."""
    lexical = root.resolve() / raw_path
    if not lexical.is_symlink():
        _require_allowed_path(root, policy, raw_path)
        return
    relative = PurePosixPath(raw_path)
    if _is_hard_forbidden(relative.as_posix()) or not any(
        relative.full_match(pattern) for pattern in policy.allowed_patterns
    ):
        raise PolicyError("symlink adapter is outside the active task scope")
    try:
        target_relative = lexical.resolve(strict=True).relative_to(root.resolve()).as_posix()
    except (OSError, ValueError) as error:
        raise PolicyError("symlink adapter target is invalid") from error
    target = PurePosixPath(target_relative)
    if _is_hard_forbidden(target_relative) or not any(
        target.full_match(pattern) for pattern in policy.allowed_patterns
    ):
        raise PolicyError("symlink adapter target is outside the active task scope")


def _string_input(tool_input: dict[str, object], key: str) -> str:
    value = tool_input.get(key)
    if not isinstance(value, str):
        raise PolicyError("tool input is missing a required string")
    return value


def _direct_paths(invocation: ToolInvocation) -> tuple[str, ...]:
    if invocation.tool_name in {"Edit", "Write", "MultiEdit"}:
        return (_string_input(invocation.tool_input, "file_path"),)
    if invocation.tool_name == "apply_patch":
        patch = invocation.tool_input.get("command", invocation.tool_input.get("patch"))
        if not isinstance(patch, str):
            raise PolicyError("patch input is missing")
        paths = tuple(match["path"] for match in _PATCH_PATH.finditer(patch))
        if not paths:
            raise PolicyError("patch contains no supported file operation")
        return paths
    return ()


def _split_shell(command: str) -> list[str]:
    if not command or len(command) > MAX_INPUT_BYTES or _SHELL_CONTROL.search(command):
        raise PolicyError("shell command is empty, compound, or exceeds the size limit")
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError as error:
        raise PolicyError("shell command has invalid quoting") from error
    if not arguments or os.path.isabs(arguments[0]) or "/" in arguments[0]:
        raise PolicyError("shell executable is not allowlisted")
    for argument in arguments:
        if any(ord(character) < CONTROL_CHARACTER_LIMIT for character in argument):
            raise PolicyError("shell argument contains invalid characters")
        if _contains_sensitive_reference(argument):
            raise PolicyError("shell command references a sensitive path")
    return arguments


def _require_repo_path(root: Path, policy: TaskPolicy, raw_path: str) -> None:
    if raw_path == "-" or raw_path.startswith(":"):
        return
    if raw_path.startswith("-"):
        raise PolicyError("shell path cannot be an option")
    _candidate_path(root, raw_path)
    if _contains_sensitive_reference(raw_path):
        raise PolicyError("shell command references a sensitive path")


def _require_git_add(arguments: list[str], root: Path, policy: TaskPolicy) -> None:
    if "--" not in arguments:
        raise PolicyError("Git add requires an explicit path separator")
    separator = arguments.index("--")
    paths = arguments[separator + 1 :]
    if not paths:
        raise PolicyError("Git add requires explicit paths")
    for raw_path in paths:
        _require_changed_path(root, policy, raw_path)


def _require_git_commit(arguments: list[str], policy: TaskPolicy) -> None:
    if "--amend" in arguments or "-a" in arguments or "--all" in arguments:
        raise PolicyError("automated Git commit cannot amend or auto-stage")
    try:
        message = arguments[arguments.index("-m") + 1]
    except (ValueError, IndexError) as error:
        raise PolicyError("automated Git commit requires an inline message") from error
    if not message.startswith(f"{policy.task_id}:"):
        raise PolicyError("automated Git commit identity is inconsistent")


def _has_option_prefix(arguments: list[str], prefixes: tuple[str, ...]) -> bool:
    return any(
        argument == prefix or argument.startswith(f"{prefix}=")
        for argument in arguments
        for prefix in prefixes
    )


def _require_git_read_paths(arguments: list[str], root: Path, policy: TaskPolicy) -> None:
    separator_present = "--" in arguments
    values = arguments[arguments.index("--") + 1 :] if separator_present else arguments
    for value in values:
        if value.startswith(("/", "../")) or separator_present:
            _require_repo_path(root, policy, value)


def _require_git_read(arguments: list[str], root: Path, policy: TaskPolicy) -> None:
    subcommand = arguments[1]
    subcommand_arguments = arguments[2:]
    forbidden = ("--exec", "--output", "--ext-diff", "--textconv", "--no-index", "-o")
    if _has_option_prefix(subcommand_arguments, forbidden):
        raise PolicyError("Git read command contains an unsafe option")
    _require_git_read_paths(subcommand_arguments, root, policy)
    if subcommand == "branch":
        safe_branch_forms: tuple[list[str], ...] = (
            [],
            ["--show-current"],
            ["--list"],
            ["-a"],
            ["-r"],
        )
        if subcommand_arguments not in safe_branch_forms:
            raise PolicyError("Git branch is restricted to exact read-only modes")
    if subcommand == "remote":
        safe_remote = subcommand_arguments in ([], ["-v"]) or (
            subcommand_arguments[:1] == ["get-url"] and len(subcommand_arguments[1:]) in {1, 2}
        )
        if not safe_remote:
            raise PolicyError("Git remote is restricted to exact read-only modes")
    if subcommand == "cat-file":
        valid_cat_file = len(subcommand_arguments[1:]) == 1 and subcommand_arguments[0] in {
            "-e",
            "-p",
            "-s",
            "-t",
        }
        if not valid_cat_file:
            raise PolicyError("Git cat-file arguments are not allowlisted")


def _require_git(arguments: list[str], root: Path, policy: TaskPolicy) -> None:
    if not arguments[1:]:
        raise PolicyError("Git subcommand is required")
    if arguments[1] in _READ_ONLY_GIT:
        _require_git_read(arguments, root, policy)
        return
    if arguments[1] == "add":
        _require_git_add(arguments, root, policy)
        return
    if arguments[1:4] == ["-c", "core.hooksPath=/dev/null", "commit"]:
        _require_git_commit(arguments, policy)
        return
    if arguments[1] == "commit":
        raise PolicyError("automated Git commit must disable checkout hooks")
    if (
        arguments[1:4] == ["push", "-u", "origin"]
        and len(arguments[4:]) == 1
        and arguments[4].startswith(f"task/{policy.task_id}-")
    ):
        return
    raise PolicyError("Git mutation is not an authorized task operation")


def _require_quality_paths(tool_arguments: list[str], root: Path) -> None:
    forbidden_output_options = (
        "--basetemp",
        "--cache-dir",
        "--config",
        "--cov-report",
        "--junitxml",
        "--junit-xml",
        "--output",
        "--output-file",
        "--rootdir",
    )
    if _has_option_prefix(tool_arguments, forbidden_output_options):
        raise PolicyError("quality gate contains an unsafe output or config option")
    for value in tool_arguments:
        if value.startswith(("/", "~", "$")) or ".." in Path(value).parts:
            raise PolicyError("quality gate path escapes the repository")
        if not value.startswith("-") and ("/" in value or value.endswith(".py")):
            _candidate_path(root, value.split("::", 1)[0])


def _require_uv_tool(tool: str, tool_arguments: list[str], root: Path) -> None:
    _require_quality_paths(tool_arguments, root)
    if tool == "ruff":
        if _has_option_prefix(tool_arguments, ("--fix", "--unsafe-fixes", "--fix-only")):
            raise PolicyError("Ruff auto-fix is forbidden")
        if tool_arguments[:1] == ["format"] and "--check" not in tool_arguments:
            raise PolicyError("Ruff formatter must run in check mode")
    if tool == "pyright" and "--createstub" in tool_arguments:
        raise PolicyError("Pyright stub creation is forbidden")
    if tool == "pip-audit" and _has_option_prefix(tool_arguments, ("--fix",)):
        raise PolicyError("dependency auto-fix is forbidden")
    if tool == "detect-secrets" and (
        tool_arguments[:1] != ["scan"]
        or _has_option_prefix(tool_arguments, ("--baseline", "--filter", "-f", "--plugin", "-p"))
    ):
        raise PolicyError("secret scan arguments are not allowlisted")


def _require_uv(arguments: list[str], root: Path) -> None:
    if arguments[1:] in (["sync", "--locked"], ["lock", "--check"], ["build"]):
        return
    position = 1
    if arguments[position : position + 2] == ["run", "--offline"]:
        position += 2
    elif arguments[position : position + 1] == ["run"]:
        position += 1
    else:
        raise PolicyError("uv operation is not allowlisted")
    if position >= len(arguments) or arguments[position] not in _UV_RUN_TOOLS:
        raise PolicyError("uv tool is not allowlisted")
    _require_uv_tool(arguments[position], arguments[position + 1 :], root)


def _require_python(arguments: list[str]) -> None:
    if not arguments[1:] or arguments[1] not in _PYTHON_SCRIPTS:
        raise PolicyError("Python may run only approved repository validators")
    script_arguments = arguments[2:]
    if arguments[1].endswith("hook.py") and script_arguments != ["--self-test"]:
        raise PolicyError("hook validator arguments are not allowlisted")
    if arguments[1].endswith("validate_setup.py") and script_arguments:
        raise PolicyError("setup validator takes no arguments")
    if arguments[1].endswith("validate_tasks.py") and script_arguments:
        raise PolicyError("task validator takes no arguments")
    invalid_manual_arguments = arguments[1].endswith("show_manual_validation.py") and (
        len(script_arguments) != 1 or re.fullmatch(r"TASK-[0-9]{3}", script_arguments[0]) is None
    )
    if invalid_manual_arguments:
        raise PolicyError("manual validation requires one task id")


def _require_gh(arguments: list[str], policy: TaskPolicy) -> None:
    if arguments[1:] == ["auth", "status"]:
        return
    if arguments[1:3] in (["repo", "view"], ["pr", "list"], ["pr", "view"], ["pr", "checks"]):
        if "--web" in arguments:
            raise PolicyError("GitHub browser launch is forbidden")
        return
    if arguments[1:3] == ["pr", "create"]:
        required = {"--draft", "--base", "--head"}
        forbidden = {"--repo", "--body-file", "--web", "--recover"}
        if not required <= set(arguments) or forbidden.intersection(arguments):
            raise PolicyError("pull request creation lacks required controls")
        if arguments.count("--base") != 1 or arguments.count("--head") != 1:
            raise PolicyError("pull request target flags must be unique")
        try:
            base = arguments[arguments.index("--base") + 1]
            head = arguments[arguments.index("--head") + 1]
        except (ValueError, IndexError) as error:
            raise PolicyError("pull request target is incomplete") from error
        if base == "dev" and head.startswith(f"task/{policy.task_id}-"):
            return
    raise PolicyError("GitHub operation is not an authorized task operation")


def _require_read_paths(
    arguments: list[str], root: Path, policy: TaskPolicy, *, start: int = 1
) -> None:
    for value in arguments[start:]:
        if not value.startswith("-"):
            _require_repo_path(root, policy, value)


def _require_read_command(arguments: list[str], root: Path, policy: TaskPolicy) -> None:
    executable = arguments[0]
    if executable == "pwd" and arguments[1:] == []:
        return
    if executable == "command" and arguments[1:2] == ["-v"] and len(arguments[2:]) == 1:
        return
    if executable in {"ls", "head", "tail", "wc"}:
        _require_read_paths(arguments, root, policy)
        return
    safe_sed_script = arguments[2:3] and re.fullmatch(r"[0-9]+(?:,[0-9]+)?p", arguments[2])
    if executable == "sed" and arguments[1:2] == ["-n"] and safe_sed_script and arguments[3:]:
        _require_read_paths(arguments, root, policy, start=3)
        return
    if executable == "rg":
        if _has_option_prefix(
            arguments[1:], ("--pre", "--pre-glob", "--hostname-bin", "--follow", "-L")
        ):
            raise PolicyError("ripgrep execution hooks are forbidden")
        for value in arguments[1:]:
            if value.startswith(("/", "../")):
                _require_repo_path(root, policy, value)
        return
    if executable == "mkdir":
        if arguments[1:2] != ["-p"] or len(arguments) != 3:
            raise PolicyError("mkdir is restricted to a single -p target")
        _require_allowed_path(root, policy, arguments[2])
        return
    if executable in {"cp", "mv"}:
        if len(arguments) != 3:
            raise PolicyError("cp/mv require exactly one source and one destination")
        _require_allowed_path(root, policy, arguments[1])
        _require_allowed_path(root, policy, arguments[2])
        return
    raise PolicyError("shell command is not in the closed allowlist")


def _require_safe_shell(command: str, root: Path, policy: TaskPolicy) -> None:
    arguments = _split_shell(command)
    executable = arguments[0]
    if executable == "git":
        _require_git(arguments, root, policy)
    elif executable == "uv":
        _require_uv(arguments, root)
    elif executable in {"python", "python3"}:
        _require_python(arguments)
    elif executable == "gh":
        _require_gh(arguments, policy)
    else:
        _require_read_command(arguments, root, policy)


_READ_ONLY_LOCAL: Final[frozenset[str]] = frozenset(
    {"ls", "head", "tail", "wc", "sed", "rg", "pwd", "command"}
)


def _bash_is_read_only(arguments: list[str]) -> bool:
    """Classify a parsed Bash invocation as safe to run without an active ready task.

    Fails closed: anything not explicitly recognized here still goes through the
    full ready-task and scope enforcement in ``main``.
    """
    executable = arguments[0]
    if executable == "git":
        return len(arguments) > 1 and arguments[1] in _READ_ONLY_GIT
    if executable == "gh":
        return arguments[1:] == ["auth", "status"] or arguments[1:3] in (
            ["repo", "view"],
            ["pr", "list"],
            ["pr", "view"],
            ["pr", "checks"],
        )
    if executable in {"uv", "python", "python3"}:
        return True
    return executable in _READ_ONLY_LOCAL


def evaluate_pre(invocation: ToolInvocation, policy: TaskPolicy, root: Path) -> tuple[str, ...]:
    direct_paths = _direct_paths(invocation)
    if direct_paths:
        for raw_path in direct_paths:
            _require_allowed_path(root, policy, raw_path)
        return direct_paths
    if invocation.tool_name == "Bash":
        _require_safe_shell(_string_input(invocation.tool_input, "command"), root, policy)
        return ()
    raise PolicyError("unsupported tool reached the scope hook")


def _git_paths(root: Path, arguments: list[str]) -> set[str]:
    git = shutil.which("git", path=os.environ.get("PATH", ""))
    if git is None:
        raise PolicyError("git is required for scope audit")
    result = subprocess.run(  # noqa: S603 - resolved executable and internal argv only
        [git, "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        timeout=10,
        check=True,
    )
    return {item.decode("utf-8") for item in result.stdout.split(b"\0") if item}


def _git_text(root: Path, arguments: list[str], *, check: bool = True) -> str:
    git = shutil.which("git", path=os.environ.get("PATH", ""))
    if git is None:
        raise PolicyError("git is required for scope audit")
    result = subprocess.run(  # noqa: S603 - resolved executable and internal argv only
        [git, "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if check and result.returncode != 0:
        raise PolicyError("Git baseline audit failed")
    return result.stdout.strip() if result.returncode == 0 else ""


def _git_succeeds(root: Path, arguments: list[str]) -> bool:
    git = shutil.which("git", path=os.environ.get("PATH", ""))
    if git is None:
        raise PolicyError("git is required for scope audit")
    result = subprocess.run(  # noqa: S603 - resolved executable and internal argv only
        [git, "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        timeout=10,
        check=False,
    )
    return result.returncode == 0


def _authorized_activation(root: Path, policy: TaskPolicy) -> tuple[str, set[str]]:
    """Recognize the one governance commit that activates a newly introduced task."""
    if not policy.baseline_commit or not policy.task_path:
        raise PolicyError("task baseline metadata is missing")
    if _git_text(root, ["cat-file", "-t", policy.baseline_commit]) != "commit":
        raise PolicyError("task baseline is not a commit")
    _git_text(root, ["merge-base", "--is-ancestor", policy.baseline_commit, "HEAD"])
    if _git_succeeds(
        root,
        ["cat-file", "-e", f"{policy.baseline_commit}:{policy.task_path}"],
    ):
        return "", set()
    commits = _git_text(
        root,
        [
            "log",
            "--format=%H",
            "--diff-filter=A",
            f"{policy.baseline_commit}..HEAD",
            "--",
            policy.task_path,
        ],
    ).splitlines()
    if len(commits) != 1:
        raise PolicyError("task activation commit is ambiguous")
    activation = commits[0]
    if _git_text(root, ["rev-parse", f"{activation}^"]) != policy.baseline_commit:
        raise PolicyError("task activation is not based directly on the pinned baseline")
    if not _git_text(root, ["show", "-s", "--format=%s", activation]).startswith(
        f"{policy.task_id}:"
    ):
        raise PolicyError("task activation commit identity is invalid")
    paths = _git_paths(
        root,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", activation],
    )
    if policy.task_path not in paths or any(
        not PurePosixPath(path).is_relative_to("docs/planejamento") for path in paths
    ):
        raise PolicyError("task activation changed non-governance paths")
    return activation, paths


def audit_changed_scope(root: Path, policy: TaskPolicy) -> None:
    activation, _activation_paths = _authorized_activation(root, policy)
    implementation_baseline = activation or policy.baseline_commit
    changed = _git_paths(root, ["diff", "--name-only", "-z", implementation_baseline, "--"])
    untracked = _git_paths(root, ["ls-files", "--others", "--exclude-standard", "-z", "--"])
    changed.update(untracked - PREEXISTING_HOST_LOCAL_PATHS)
    for relative_path in changed:
        _require_changed_path(root, policy, relative_path)


def _bounded_quality_process(command: list[str], root: Path, environment: dict[str, str]) -> int:
    process = subprocess.Popen(  # noqa: S603 - resolved executable and fixed quality argv
        command,
        cwd=root,
        env=environment,
        # Gate output can contain the edited source. Retaining zero bytes is the strictest
        # output limit and prevents accidental secret reflection into agent diagnostics.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        process.communicate(timeout=QUALITY_TIMEOUT_SECONDS)
        return process.returncode
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        raise


def _quality_check(root: Path, direct_paths: tuple[str, ...], policy: TaskPolicy) -> None:
    uv = shutil.which("uv", path=os.environ.get("PATH", ""))
    if uv is None:
        raise PolicyError("uv is required for Python post-edit checks")
    checked: set[str] = set()
    for raw_path in direct_paths:
        candidate, relative = _require_allowed_path(root, policy, raw_path)
        if candidate.suffix != ".py" or not candidate.is_file() or relative in checked:
            continue
        checked.add(relative)
        for command in (
            [uv, "run", "--offline", "ruff", "check", relative],
            [uv, "run", "--offline", "ruff", "format", "--check", relative],
        ):
            child_environment = {
                "PATH": os.environ.get("PATH", ""),
                "UV_NO_PROGRESS": "1",
            }
            if temporary_root := os.environ.get("TMPDIR"):
                child_environment["TMPDIR"] = temporary_root
            if _bounded_quality_process(command, root, child_environment) != 0:
                raise PolicyError("Python post-edit quality check failed")


def _self_test(root: Path) -> int:
    policy = TaskPolicy(task_id="TASK-TEST", allowed_patterns=("AGENTS.md",))
    cases: tuple[tuple[str, dict[str, object], bool], ...] = (
        ("claude allow", {"tool_name": "Write", "tool_input": {"file_path": "AGENTS.md"}}, True),
        (
            "codex allow",
            {
                "tool_name": "apply_patch",
                "tool_input": {"command": "*** Update File: AGENTS.md\n"},
            },
            True,
        ),
        ("claude deny secret", {"tool_name": "Write", "tool_input": {"file_path": ".env"}}, False),
        (
            "codex deny escape",
            {"tool_name": "apply_patch", "tool_input": {"command": "*** Add File: ../escape\n"}},
            False,
        ),
        (
            "shared deny shell mutation",
            {"tool_name": "Bash", "tool_input": {"command": "sed -i backup AGENTS.md"}},
            False,
        ),
    )
    for label, payload, expected_allow in cases:
        try:
            host = "codex" if payload["tool_name"] == "apply_patch" else "claude"
            evaluate_pre(_normalize_invocation(payload, host), policy, root)
            allowed = True
        except PolicyError:
            allowed = False
        if allowed != expected_allow:
            print(f"FAIL {label}")
            return 1
        print(f"PASS {label}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("claude", "codex"))
    parser.add_argument("--phase", choices=("pre", "post"))
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        root = _repository_root()
        if args.self_test:
            return _self_test(root)
        if args.host is None or args.phase is None:
            raise PolicyError("host and phase are required")
        invocation = _normalize_invocation(read_payload(sys.stdin.buffer), args.host)
        if invocation.tool_name == "Bash":
            arguments = _split_shell(_string_input(invocation.tool_input, "command"))
            if _bash_is_read_only(arguments):
                _require_safe_shell(
                    _string_input(invocation.tool_input, "command"), root, _NO_TASK_POLICY
                )
                return 0
        policy = load_ready_policy(root)
        direct_paths = evaluate_pre(invocation, policy, root)
        if args.phase == "post":
            audit_changed_scope(root, policy)
            _quality_check(root, direct_paths, policy)
        return 0
    except PolicyError as error:
        print(f"agent-policy: denied: {error}", file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError):
        print("agent-policy: denied: internal policy failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
