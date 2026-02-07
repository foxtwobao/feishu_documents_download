"""FastAPI application entry point for LarkSync Web."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import load_config
from .auth import FeishuOAuthClient
from .database import configure_database, init_database
from .frontend import is_dev_mode, is_production_mode, setup_frontend
from .routes import (
    auth_router,
    cli_auth_router,
    sync_configs_router,
    sync_runs_router,
    users_router,
)
from .scheduler import init_scheduler, shutdown_scheduler
from .state import CLIOAuthSessionStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown."""
    config = app.state.config
    
    # Initialize database
    configure_database(config.web.database_url)
    init_database()
    logger.info("Database initialized")

    # Initialize OAuth client
    app.state.oauth_client = FeishuOAuthClient(config.web.oauth)
    logger.info(f"OAuth client initialized (enabled={app.state.oauth_client.enabled})")

    # Initialize CLI OAuth session store
    app.state.cli_session_store = CLIOAuthSessionStore(ttl_seconds=300)

    # Initialize scheduler
    base_storage_root = Path(config.web.user_storage_base or config.storage.root)
    base_storage_root.mkdir(parents=True, exist_ok=True)
    app.state.base_storage_root = base_storage_root
    
    init_scheduler(config, base_storage_root)
    logger.info("Scheduler initialized")

    yield

    # Shutdown
    shutdown_scheduler()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    # Load configuration
    config = load_config()

    app = FastAPI(
        title="LarkSync Web API",
        description="Multi-user sync system for Feishu documents",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store config in app state
    app.state.config = config

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to specific origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers with /api prefix for clear frontend/backend separation
    API_PREFIX = "/api"
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(cli_auth_router, prefix=API_PREFIX)
    app.include_router(users_router, prefix=API_PREFIX)
    app.include_router(sync_configs_router, prefix=API_PREFIX)
    app.include_router(sync_runs_router, prefix=API_PREFIX)

    # Health check endpoint (also under /api)
    @app.get(f"{API_PREFIX}/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "service": "larksync-web"}

    # Set up frontend serving (dev proxy or production static files)
    # This must be done after routers are included so API routes take precedence
    setup_frontend(app)
    
    # Root endpoint - only used if frontend is not configured
    if not is_dev_mode() and not is_production_mode():
        @app.get("/")
        async def root():
            """Root endpoint with API info (API-only mode)."""
            return {
                "service": "LarkSync Web API",
                "version": "0.1.0",
                "docs": "/docs",
                "health": "/health",
            }

    return app


# For uvicorn: uvicorn larksync.web.app:create_app --factory
