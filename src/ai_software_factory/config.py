"""Strict TOML configuration loading for the AI Software Factory CLI.

Unknown fields and wrong-typed values fail before any effect is produced,
so a hostile or malformed ``factory.toml`` never reaches a probe or a worker.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

DEFAULT_CONFIG_PATH: Final[Path] = Path("factory.toml")
_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset({"no_incremental_cost", "live_probes"})


class ConfigError(ValueError):
    """Raised when a configuration file cannot be read, parsed or trusted."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated Factory configuration. Immutable once loaded."""

    no_incremental_cost: bool = True
    live_probes: bool = False

    @classmethod
    def load(cls, path: Path | None) -> Settings:
        """Load settings from ``path`` (default ``./factory.toml``).

        A missing file yields safe defaults. An existing file must parse as
        TOML and contain only known, correctly typed fields, or ``ConfigError``
        is raised before any setting takes effect.
        """
        target = path if path is not None else DEFAULT_CONFIG_PATH
        if not target.exists():
            return cls()
        data = _read_toml(target)
        return cls._from_mapping(data, target)

    @classmethod
    def _from_mapping(cls, data: Mapping[str, Any], source: Path) -> Settings:
        unknown = sorted(set(data) - _ALLOWED_FIELDS)
        if unknown:
            raise ConfigError(f"{source}: campos desconhecidos: {', '.join(unknown)}")
        return cls(
            no_incremental_cost=_require_bool(data, "no_incremental_cost", source, default=True),
            live_probes=_require_bool(data, "live_probes", source, default=False),
        )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError(f"não foi possível ler {path}: {error}") from error
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"TOML inválido em {path}: {error}") from error


def _require_bool(data: Mapping[str, Any], key: str, source: Path, *, default: bool) -> bool:
    if key not in data:
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f"{source}: campo '{key}' deve ser booleano, recebido {type(value).__name__}"
        )
    return value
