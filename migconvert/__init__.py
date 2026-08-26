"""Convert SQL migration files between goose and dbmate annotation formats."""

from .cli import main

__version__ = "0.1.0"

__all__ = ["main", "__version__"]
