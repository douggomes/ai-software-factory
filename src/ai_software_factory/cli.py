"""``aif`` command-line entry point.

Only offline, read-only behavior lives here for now: printing the installed
version and running local diagnostics (``doctor``). No command in this module
invokes a provider or performs a network call.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from ai_software_factory import __version__

#: Executable name probed for each supported worker/reviewer CLI. Presence is
#: checked with ``shutil.which`` only; the executable is never invoked.
PROVIDER_EXECUTABLES: Final[Mapping[str, str]] = {
    "claude": "claude",
    "codex": "codex",
    "opencode": "opencode",
}

_VERSION_PROBE_TIMEOUT_SECONDS: Final[float] = 5.0
_VERSION_FLAG: Final[str] = "--version"


@dataclass(frozen=True, slots=True)
class ToolStatus:
    """Read-only probe result for a required command-line tool."""

    available: bool
    version: str | None


@dataclass(frozen=True, slots=True)
class DoctorProbes:
    """Injectable, read-only probes used to build a doctor report.

    Kept as plain callables (not a provider adapter) so tests can substitute
    deterministic doubles without touching the real environment or PATH.
    """

    python_version: Callable[[], str]
    sqlite_version: Callable[[], str]
    tool_probe: Callable[[str], ToolStatus]
    provider_probe: Callable[[str], str]


def probe_tool(
    executable: str,
    *,
    version_flag: str = _VERSION_FLAG,
    timeout: float = _VERSION_PROBE_TIMEOUT_SECONDS,
) -> ToolStatus:
    """Report whether ``executable`` is installed and its reported version.

    Read-only: resolves the executable on PATH and, only if found, runs it
    with a version flag. Never used to probe a worker/provider executable.
    """
    resolved = shutil.which(executable)
    if resolved is None:
        return ToolStatus(available=False, version=None)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, read-only version probe
            [resolved, version_flag],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ToolStatus(available=False, version=None)
    if completed.returncode != 0:
        return ToolStatus(available=False, version=None)
    lines = (completed.stdout or completed.stderr or "").strip().splitlines()
    return ToolStatus(available=True, version=lines[0] if lines else None)


def probe_provider(executable: str) -> str:
    """Report worker/reviewer CLI presence without ever executing it."""
    return "available" if shutil.which(executable) is not None else "unavailable"


def default_probes() -> DoctorProbes:
    return DoctorProbes(
        python_version=lambda: sys.version.split()[0],
        sqlite_version=lambda: sqlite3.sqlite_version,
        tool_probe=probe_tool,
        provider_probe=probe_provider,
    )


def build_doctor_report(probes: DoctorProbes) -> dict[str, object]:
    """Assemble the deterministic diagnostic report from injected probes."""
    uv_status = probes.tool_probe("uv")
    git_status = probes.tool_probe("git")
    return {
        "python": {"version": probes.python_version()},
        "uv": {"available": uv_status.available, "version": uv_status.version},
        "git": {"available": git_status.available, "version": git_status.version},
        "sqlite": {"available": True, "version": probes.sqlite_version()},
        "providers": {
            name: probes.provider_probe(executable)
            for name, executable in sorted(PROVIDER_EXECUTABLES.items())
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aif", description="AI Software Factory CLI")
    parser.add_argument("--version", action="version", version=__version__)
    subcommands = parser.add_subparsers(dest="command")
    doctor = subcommands.add_parser("doctor", help="Run offline environment diagnostics")
    doctor.add_argument(
        "--json", action="store_true", required=True, help="Emit diagnostics as JSON"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        report = build_doctor_report(default_probes())
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised via the installed console script
    raise SystemExit(main())
