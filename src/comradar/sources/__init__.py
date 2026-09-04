"""Source adapters. Importing this package registers every built-in adapter."""

from . import apis, generic, naver, rss  # noqa: F401  (import for side effects)
from .base import (  # noqa: F401
    Adapter,
    FetchContext,
    SourceError,
    available_sources,
    get_adapter,
    register,
)

__all__ = [
    "Adapter",
    "FetchContext",
    "SourceError",
    "available_sources",
    "get_adapter",
    "register",
]
