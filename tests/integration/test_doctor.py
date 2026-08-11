"""Integration tests for `aif doctor --json` wired through the real CLI parser."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ai_software_factory import cli


def _fake_tool_probe(executable: str) -> cli.ToolStatus:
    return cli.ToolStatus(available=True, version=f"{executable} 0.0.0-test")


def test_doctor_offline_never_invokes_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """`doctor --json` must detect provider CLIs by presence only.

    A fake `claude` executable is placed on PATH that leaves a marker file
    behind if it is ever executed. The report must show it as "available"
    (found via `which`) while the marker stays absent, proving no worker or
    reviewer CLI is invoked while building the diagnostic.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    invoked_marker = tmp_path / "claude-was-invoked.marker"
    fake_claude = bin_dir / "claude"
    fake_claude.write_text(
        f"#!/bin/sh\ntouch '{invoked_marker}'\necho 'claude 0.0.0-test'\n",
        encoding="utf-8",
    )
    fake_claude.chmod(fake_claude.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir))

    fake_probes = cli.DoctorProbes(
        python_version=lambda: "3.14.6",
        sqlite_version=lambda: "3.46.0",
        tool_probe=_fake_tool_probe,
        provider_probe=cli.probe_provider,  # real which-only implementation
    )
    monkeypatch.setattr(cli, "default_probes", lambda: fake_probes)

    exit_code = cli.main(["doctor", "--json"])

    assert exit_code == 0
    assert not invoked_marker.exists()
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "python": {"version": "3.14.6"},
        "uv": {"available": True, "version": "uv 0.0.0-test"},
        "git": {"available": True, "version": "git 0.0.0-test"},
        "sqlite": {"available": True, "version": "3.46.0"},
        "providers": {
            "claude": "available",
            "codex": "unavailable",
            "opencode": "unavailable",
        },
    }


def test_doctor_reports_missing_tool_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))

    fake_probes = cli.DoctorProbes(
        python_version=lambda: "3.14.6",
        sqlite_version=lambda: "3.46.0",
        tool_probe=cli.probe_tool,  # real which-based implementation
        provider_probe=cli.probe_provider,
    )
    monkeypatch.setattr(cli, "default_probes", lambda: fake_probes)

    exit_code = cli.main(["doctor", "--json"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["uv"] == {"available": False, "version": None}
    assert report["git"] == {"available": False, "version": None}
    assert report["providers"] == {
        "claude": "unavailable",
        "codex": "unavailable",
        "opencode": "unavailable",
    }


def test_doctor_requires_json_flag() -> None:
    with pytest.raises(SystemExit):
        cli.main(["doctor"])


def test_doctor_fails_fast_on_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """QA-001-001 regression: an invalid factory.toml fails before any probe runs."""
    expected_invalid_exit_code = 2
    monkeypatch.chdir(tmp_path)
    (tmp_path / "factory.toml").write_text("campo_inexistente = true\n", encoding="utf-8")
    probed = False

    def _spy_default_probes() -> cli.DoctorProbes:
        nonlocal probed
        probed = True
        return cli.default_probes()

    monkeypatch.setattr(cli, "default_probes", _spy_default_probes)

    exit_code = cli.main(["doctor", "--json"])

    assert exit_code == expected_invalid_exit_code
    assert probed is False
    assert "campo_inexistente" in capsys.readouterr().err


def test_main_without_command_prints_help_and_returns_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli.main([])

    assert exit_code == 1
    assert "usage" in capsys.readouterr().out.lower()


def _make_executable(path: Path, script: str) -> None:
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_probe_tool_reports_available_with_version(tmp_path: Path) -> None:
    fake_tool = tmp_path / "faketool"
    _make_executable(fake_tool, "#!/bin/sh\necho 'faketool 9.9.9'\n")

    status = cli.probe_tool(str(fake_tool))

    assert status == cli.ToolStatus(available=True, version="faketool 9.9.9")


def test_probe_tool_reports_unavailable_on_nonzero_exit(tmp_path: Path) -> None:
    failing_tool = tmp_path / "failingtool"
    _make_executable(failing_tool, "#!/bin/sh\nexit 1\n")

    status = cli.probe_tool(str(failing_tool))

    assert status == cli.ToolStatus(available=False, version=None)


def test_probe_tool_reports_unavailable_when_missing_from_path() -> None:
    status = cli.probe_tool("definitely-not-a-real-executable-xyz")

    assert status == cli.ToolStatus(available=False, version=None)


def test_probe_tool_reports_unavailable_on_timeout(tmp_path: Path) -> None:
    slow_tool = tmp_path / "slowtool"
    _make_executable(slow_tool, "#!/bin/sh\nsleep 5\n")

    status = cli.probe_tool(str(slow_tool), timeout=0.05)

    assert status == cli.ToolStatus(available=False, version=None)


def test_default_probes_exposes_real_environment_readers() -> None:
    probes = cli.default_probes()

    assert probes.python_version()
    assert probes.sqlite_version()
    assert probes.tool_probe is cli.probe_tool
    assert probes.provider_probe is cli.probe_provider
