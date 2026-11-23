"""Data source adapters."""

from .base import SourceAdapter, SourceContext
from .registry import autodetect, get_adapter

__all__ = ["SourceAdapter", "SourceContext", "autodetect", "get_adapter"]
