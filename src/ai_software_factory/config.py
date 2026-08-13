"""Strict TOML configuration loading for the AI Software Factory CLI.

Unknown fields and wrong-typed values fail before any effect is produced,
so a hostile or malformed ``factory.toml`` never reaches a probe or a worker.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

DEFAULT_CONFIG_PATH: Final[Path] = Path("factory.toml")
_ALLOWED_FIELDS: Final[frozenset[str]] = frozenset(
    {"no_incremental_cost", "live_probes", "isolation"}
)
_ISOLATION_FIELDS: Final[frozenset[str]] = frozenset({"backend", "image"})
_ISOLATION_BACKENDS: Final[frozenset[str]] = frozenset({"disabled", "docker", "podman"})
_IMAGE_DIGEST_PREFIX: Final[str] = "@sha256:"
_SHA256_HEX_LENGTH: Final[int] = 64
APPROVED_VALIDATION_IMAGE: Final[str] = (
    "ghcr.io/douggomes/ai-software-factory-validation@sha256:"
    "8b3742f7975f917ffd01de4f04a9921dd5401053d41f3f8ab1b4cee75b2da3aa"
)


class ConfigError(ValueError):
    """Raised when a configuration file cannot be read, parsed or trusted."""


@dataclass(frozen=True, slots=True)
class IsolationSettings:
    """Closed configuration for the local OCI validation boundary."""

    backend: str = "disabled"
    image: str | None = None

    def __post_init__(self) -> None:
        if self.backend not in _ISOLATION_BACKENDS:
            raise ConfigError("isolation.backend deve ser disabled, docker ou podman")
        if self.backend == "disabled":
            if self.image is not None:
                raise ConfigError("isolation.image exige um backend habilitado")
            return
        if self.image is None or not _is_digest_image(self.image):
            raise ConfigError("isolation.image deve usar name@sha256:<64-hex>")
        if self.image != APPROVED_VALIDATION_IMAGE:
            raise ConfigError("isolation.image não corresponde à imagem de validação aprovada")


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated Factory configuration. Immutable once loaded."""

    no_incremental_cost: bool = True
    live_probes: bool = False
    isolation: IsolationSettings = IsolationSettings()

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
            isolation=_require_isolation(data, source),
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


def _require_isolation(data: Mapping[str, Any], source: Path) -> IsolationSettings:
    value = data.get("isolation")
    if value is None:
        return IsolationSettings()
    if not isinstance(value, dict):
        raise ConfigError(f"{source}: campo 'isolation' deve ser uma tabela")
    typed = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in typed):
        raise ConfigError(f"{source}: tabela isolation é inválida")
    fields = cast(dict[str, object], typed)
    unknown = sorted(set(fields) - _ISOLATION_FIELDS)
    if unknown:
        raise ConfigError(f"{source}: isolation contém campos desconhecidos: {', '.join(unknown)}")
    backend = fields.get("backend", "disabled")
    image = fields.get("image")
    if not isinstance(backend, str):
        raise ConfigError(f"{source}: isolation.backend deve ser texto")
    if image is not None and not isinstance(image, str):
        raise ConfigError(f"{source}: isolation.image deve ser texto")
    return IsolationSettings(backend=backend, image=image)


def _is_digest_image(value: str) -> bool:
    name, separator, digest = value.partition(_IMAGE_DIGEST_PREFIX)
    has_digest = len(digest) == _SHA256_HEX_LENGTH
    is_hex = all(char in "0123456789abcdef" for char in digest)
    return bool(name and separator and has_digest and is_hex)
