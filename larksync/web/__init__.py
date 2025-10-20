"""Web application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from .app import create_app

__all__ = ["create_app", "FastAPI"]
