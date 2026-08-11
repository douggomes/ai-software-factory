"""Unit tests for strict Factory configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_software_factory.config import ConfigError, Settings


def test_load_missing_file_returns_safe_defaults(tmp_path: Path) -> None:
    settings = Settings.load(tmp_path / "missing-factory.toml")

    assert settings == Settings(no_incremental_cost=True, live_probes=False)


def test_load_none_path_uses_default_config_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    settings = Settings.load(None)

    assert settings == Settings()


def test_load_accepts_explicit_known_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.write_text("no_incremental_cost = false\nlive_probes = true\n", encoding="utf-8")

    settings = Settings.load(config_path)

    assert settings == Settings(no_incremental_cost=False, live_probes=True)


def test_load_rejects_unknown_field_before_any_effect(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.write_text('unexpected_field = "x"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="unexpected_field"):
        Settings.load(config_path)


def test_load_rejects_wrong_typed_field(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.write_text('no_incremental_cost = "yes"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="no_incremental_cost"):
        Settings.load(config_path)


def test_load_rejects_invalid_toml_syntax(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.write_text("no_incremental_cost = [true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="TOML inválido"):
        Settings.load(config_path)


def test_settings_is_frozen(tmp_path: Path) -> None:
    settings = Settings()

    with pytest.raises(AttributeError):
        settings.no_incremental_cost = False  # type: ignore[misc]


def test_load_defaults_field_absent_from_file(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.write_text("live_probes = true\n", encoding="utf-8")

    settings = Settings.load(config_path)

    assert settings == Settings(no_incremental_cost=True, live_probes=True)


def test_load_raises_config_error_when_path_cannot_be_read(tmp_path: Path) -> None:
    config_path = tmp_path / "factory.toml"
    config_path.mkdir()

    with pytest.raises(ConfigError, match="não foi possível ler"):
        Settings.load(config_path)
