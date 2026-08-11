"""AI Software Factory package shell."""

from importlib import metadata

try:
    __version__ = metadata.version("ai-software-factory")
except metadata.PackageNotFoundError:  # pragma: no cover - editable install always resolves
    __version__ = "0.0.0"

__all__ = ["__version__"]
