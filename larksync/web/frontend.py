"""Frontend integration for single-port architecture.

This module provides:
- Development mode: Reverse proxy to Next.js dev server
- Production mode: Serve Next.js static build files
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# Environment variable for development mode
FRONTEND_DEV_URL = os.environ.get("FRONTEND_DEV_URL")

# Path to Next.js build output (relative to this file's location)
WEBUI_CLIENT_DIR = Path(__file__).parent.parent.parent / "webui-client"
NEXT_BUILD_DIR = WEBUI_CLIENT_DIR / ".next"
NEXT_STATIC_DIR = NEXT_BUILD_DIR / "static"
NEXT_STANDALONE_DIR = NEXT_BUILD_DIR / "standalone"


def is_dev_mode() -> bool:
    """Check if running in development mode."""
    return bool(FRONTEND_DEV_URL)


def is_production_mode() -> bool:
    """Check if Next.js build is available for production serving."""
    return not is_dev_mode() and NEXT_STATIC_DIR.exists()


def setup_frontend(app: FastAPI) -> None:
    """
    Configure frontend serving based on environment.
    
    - If FRONTEND_DEV_URL is set: proxy requests to Next.js dev server
    - If Next.js build exists: serve static files
    - Otherwise: do nothing (API-only mode)
    """
    if is_dev_mode():
        _setup_dev_proxy(app)
        logger.info(f"Frontend dev proxy enabled -> {FRONTEND_DEV_URL}")
    elif is_production_mode():
        _setup_production_static(app)
        logger.info(f"Frontend static files enabled from {NEXT_BUILD_DIR}")
    else:
        logger.info("Frontend not configured (API-only mode)")


def _setup_dev_proxy(app: FastAPI) -> None:
    """Set up reverse proxy to Next.js development server."""
    
    # Simple routing rule:
    # - /api/* -> FastAPI backend
    # - /docs, /openapi.json, /redoc -> FastAPI (OpenAPI docs)
    # - Everything else -> Next.js frontend
    
    BACKEND_PREFIXES = ("/api/", "/docs", "/openapi.json", "/redoc")
    
    @app.middleware("http")
    async def proxy_frontend_requests(request: Request, call_next):
        """Proxy non-API requests to Next.js dev server."""
        path = request.url.path
        
        # Backend API and docs go to FastAPI
        if path.startswith(BACKEND_PREFIXES):
            return await call_next(request)
        
        # Everything else goes to Next.js frontend
        return await _proxy_request(request, path)
    
    async def _proxy_request(request: Request, path: str) -> Response:
        """Forward request to Next.js dev server."""
        target_url = f"{FRONTEND_DEV_URL}{path}"
        if request.url.query:
            target_url += f"?{request.url.query}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                # Forward the request
                headers = dict(request.headers)
                headers.pop("host", None)
                
                body = await request.body()
                
                response = await client.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body if body else None,
                    follow_redirects=False,
                )
                
                # Build response headers
                excluded_headers = {"transfer-encoding", "content-encoding", "content-length"}
                response_headers = {
                    k: v for k, v in response.headers.items()
                    if k.lower() not in excluded_headers
                }
                
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type=response.headers.get("content-type"),
                )
            except httpx.RequestError as e:
                logger.error(f"Frontend proxy error: {e}")
                return HTMLResponse(
                    content=f"<h1>Frontend Unavailable</h1><p>Could not connect to {FRONTEND_DEV_URL}</p>",
                    status_code=502,
                )


def _setup_production_static(app: FastAPI) -> None:
    """Set up static file serving for production Next.js build."""
    
    # Mount Next.js static assets
    if NEXT_STATIC_DIR.exists():
        app.mount(
            "/_next/static",
            StaticFiles(directory=str(NEXT_STATIC_DIR)),
            name="next-static",
        )
        logger.debug(f"Mounted /_next/static -> {NEXT_STATIC_DIR}")
    
    # Mount public directory if exists
    public_dir = WEBUI_CLIENT_DIR / "public"
    if public_dir.exists():
        app.mount(
            "/public",
            StaticFiles(directory=str(public_dir)),
            name="public",
        )
        logger.debug(f"Mounted /public -> {public_dir}")
    
    # For production SSR, we need to run Next.js standalone server
    # or serve pre-rendered HTML. For now, serve a simple fallback.
    # In full production, consider using Next.js standalone output.
    
    # Read the pre-rendered index if available
    index_html_path = NEXT_BUILD_DIR / "server" / "app" / "index.html"
    fallback_html = None
    if not index_html_path.exists():
        # Try standalone output
        standalone_html = NEXT_STANDALONE_DIR / "webui-client" / ".next" / "server" / "app" / "index.html"
        if standalone_html.exists():
            index_html_path = standalone_html
    
    if index_html_path.exists():
        fallback_html = index_html_path.read_text()
    
    # Override root endpoint to serve frontend
    @app.get("/", response_class=HTMLResponse)
    async def serve_frontend_root():
        """Serve frontend root page."""
        if fallback_html:
            return HTMLResponse(content=fallback_html)
        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>LarkSync</title>
                <style>
                    body { font-family: system-ui; padding: 2rem; text-align: center; }
                    a { color: #0070f3; }
                </style>
            </head>
            <body>
                <h1>LarkSync Web</h1>
                <p>Frontend build not found. Please build the frontend first:</p>
                <pre>cd webui-client && npm run build</pre>
                <p><a href="/docs">API Documentation</a></p>
            </body>
            </html>
            """,
            status_code=200,
        )
