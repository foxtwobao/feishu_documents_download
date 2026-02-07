"""Web UI module for LarkSync multi-user sync system."""

from __future__ import annotations

__all__ = [
    "create_app",
]


def create_app():
    """Create and configure the FastAPI application."""
    from .app import create_app as _create_app
    return _create_app()
