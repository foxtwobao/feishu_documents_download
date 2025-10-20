"""Factory to create FastAPI application."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import LarkSyncConfig
from .auth import FeishuOAuthClient
from .database import configure_database, init_database
from .dependencies import config_dependency
from .routes import auth_router, task_router, user_router
from .state import OAuthStateStore
from .tasks import TaskManager

logger = logging.getLogger(__name__)


def create_app(config: LarkSyncConfig | None = None) -> FastAPI:
    config = config or config_dependency()

    app = FastAPI(title="LarkSync Web UI", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    db_path = Path("output/webui.db")
    configure_database(db_path)
    init_database()

    oauth_client = FeishuOAuthClient(config.web.oauth)
    task_manager = TaskManager(config, oauth_client=oauth_client)
    task_manager.start()

    app.state.config = config
    app.state.oauth_client = oauth_client
    app.state.task_manager = task_manager
    app.state.oauth_state_store = OAuthStateStore()

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(user_router, prefix="/users", tags=["users"])
    app.include_router(task_router, prefix="/tasks", tags=["tasks"])

    @app.get("/health", tags=["system"])
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    return app
