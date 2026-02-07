"""API routes for LarkSync Web."""

from __future__ import annotations

from .auth import router as auth_router
from .cli_auth import router as cli_auth_router
from .sync_configs import router as sync_configs_router
from .sync_runs import router as sync_runs_router
from .users import router as users_router

__all__ = [
    "auth_router",
    "cli_auth_router",
    "sync_configs_router",
    "sync_runs_router",
    "users_router",
]
