"""CLI OAuth shared callback routes."""

from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from ..auth import FeishuOAuthClient, generate_state
from ..state import CLIOAuthSessionStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cli/oauth", tags=["cli-auth"])


class CreateSessionResponse(BaseModel):
    """Response for creating a CLI OAuth session."""

    session_id: str
    authorization_url: str
    expires_in: int
    poll_interval_seconds: int


class SessionStatusResponse(BaseModel):
    """Response for session status."""

    status: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    refresh_token_expires_in: Optional[int] = None
    error: Optional[str] = None


@router.post("/session", response_model=CreateSessionResponse)
async def create_session(request: Request) -> CreateSessionResponse:
    """
    Create a new CLI OAuth session.
    
    The CLI calls this to start the OAuth flow. It receives a session ID
    and authorization URL. The CLI then opens the browser with the auth URL
    and polls the session status endpoint.
    """
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client
    session_store: CLIOAuthSessionStore = request.app.state.cli_session_store

    if not oauth_client.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth is not configured",
        )

    # Generate session ID and state
    session_id = secrets.token_urlsafe(16)
    state = generate_state()

    # Create session
    session_store.create_session(session_id, state)

    # Build authorization URL
    authorization_url = oauth_client.build_authorization_url(state)

    return CreateSessionResponse(
        session_id=session_id,
        authorization_url=authorization_url,
        expires_in=session_store.ttl_seconds,
        poll_interval_seconds=2,
    )


@router.get("/session/{session_id}", response_model=SessionStatusResponse)
async def get_session_status(
    request: Request,
    session_id: str,
) -> SessionStatusResponse:
    """
    Get the status of a CLI OAuth session.
    
    The CLI polls this endpoint to check if authorization is complete.
    """
    session_store: CLIOAuthSessionStore = request.app.state.cli_session_store
    session = session_store.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found or expired",
        )

    return SessionStatusResponse(
        status=session.status,
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        refresh_token_expires_in=session.refresh_token_expires_in,
        error=session.error,
    )


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(None, description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    error: Optional[str] = Query(None, description="Error code"),
    error_description: Optional[str] = Query(None, description="Error description"),
):
    """
    Handle OAuth callback for CLI sessions.
    
    This is called by Feishu after user authorizes. It exchanges the code
    for tokens and stores them in the session for the CLI to retrieve.
    """
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client
    session_store: CLIOAuthSessionStore = request.app.state.cli_session_store

    # Find session by state
    session = session_store.get_session_by_state(state)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired state parameter",
        )

    # Handle error from Feishu
    if error:
        session_store.update_session(
            session.session_id,
            error=error_description or error,
        )
        return _render_callback_page(
            success=False,
            message=error_description or error,
        )

    if not code:
        session_store.update_session(
            session.session_id,
            error="No authorization code received",
        )
        return _render_callback_page(
            success=False,
            message="No authorization code received",
        )

    try:
        # Exchange code for tokens
        (
            access_token,
            refresh_token,
            expires_in,
            refresh_token_expires_in,
        ) = await oauth_client.exchange_code(code)

        # Update session with tokens
        session_store.update_session(
            session.session_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            refresh_token_expires_in=refresh_token_expires_in,
        )

        logger.info(f"CLI OAuth session {session.session_id} authorized successfully")

        return _render_callback_page(
            success=True,
            message="Authorization successful! You can close this window and return to the terminal.",
        )

    except Exception as e:
        logger.error(f"CLI OAuth callback error: {e}")
        session_store.update_session(
            session.session_id,
            error=str(e),
        )
        return _render_callback_page(
            success=False,
            message=f"Authorization failed: {str(e)}",
        )


def _render_callback_page(success: bool, message: str) -> str:
    """Render a simple HTML page for the callback result."""
    from fastapi.responses import HTMLResponse

    status_icon = "✅" if success else "❌"
    status_text = "授权成功" if success else "授权失败"
    bg_color = "#e8f5e9" if success else "#ffebee"
    text_color = "#2e7d32" if success else "#c62828"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{status_text}</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background-color: {bg_color};
            }}
            .container {{
                text-align: center;
                padding: 40px;
                background: white;
                border-radius: 12px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
                max-width: 400px;
            }}
            .icon {{
                font-size: 64px;
                margin-bottom: 20px;
            }}
            h1 {{
                color: {text_color};
                margin: 0 0 16px 0;
                font-size: 24px;
            }}
            p {{
                color: #666;
                margin: 0;
                line-height: 1.6;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">{status_icon}</div>
            <h1>{status_text}</h1>
            <p>{message}</p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
