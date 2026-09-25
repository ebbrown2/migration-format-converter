"""Convert SQL migration files between goose and dbmate annotation formats."""

__version__ = "0.1.0"

from .cli import main  # noqa: E402  (must follow __version__, which cli imports)

__all__ = ["main", "__version__"]
