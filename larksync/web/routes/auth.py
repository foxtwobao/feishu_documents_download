"""Authentication routes for Web UI."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import FeishuOAuthClient, compute_expiry, generate_state
from ..database import get_db
from ..deps import USER_COOKIE_NAME, get_current_user, get_current_user_optional
from ..models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthorizeResponse(BaseModel):
    """Response for authorization URL request."""

    authorization_url: str
    state: str


class UserResponse(BaseModel):
    """User info response."""

    user_id: str
    feishu_user_id: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    email: Optional[str]
    token_expires_at: Optional[datetime]
    is_token_valid: bool

    class Config:
        from_attributes = True


class TokenStatusResponse(BaseModel):
    """Token status response."""

    is_valid: bool
    expires_at: Optional[datetime]
    message: str


@router.get("/authorize")
async def authorize(request: Request) -> AuthorizeResponse:
    """
    Get authorization URL to start OAuth flow.
    
    Frontend should redirect user to this URL.
    """
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client
    
    if not oauth_client.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth is not configured. Please set app_id and app_secret in config.",
        )

    state = generate_state()
    authorization_url = oauth_client.build_authorization_url(state)

    # Store state in session for verification (simple in-memory for now)
    # In production, use Redis or database
    if not hasattr(request.app.state, "oauth_states"):
        request.app.state.oauth_states = {}
    request.app.state.oauth_states[state] = True

    return AuthorizeResponse(authorization_url=authorization_url, state=state)


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(..., description="Authorization code"),
    state: str = Query(..., description="State parameter"),
    db: Session = Depends(get_db),
):
    """
    Handle OAuth callback from Feishu.
    
    Exchanges code for tokens and creates/updates user.
    Redirects to frontend with user info.
    """
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client

    # Verify state (simple check)
    oauth_states = getattr(request.app.state, "oauth_states", {})
    if state not in oauth_states:
        logger.warning(f"Invalid OAuth state: {state}")
        # Still process for now, but log warning

    # Remove used state
    oauth_states.pop(state, None)

    try:
        # Exchange code for tokens
        (
            access_token,
            refresh_token,
            expires_in,
            refresh_token_expires_in,
        ) = await oauth_client.exchange_code(code)

        # Get user info
        user_info = await oauth_client.get_user_info(access_token)
        feishu_user_id = user_info.get("user_id")

        if not feishu_user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user ID from Feishu",
            )

        # Find or create user
        user = db.query(User).filter(User.feishu_user_id == feishu_user_id).first()

        if user:
            # Update existing user
            user.display_name = user_info.get("name") or user_info.get("en_name")
            user.avatar_url = user_info.get("avatar_url")
            user.email = user_info.get("email")
            user.access_token = access_token
            user.refresh_token = refresh_token
            user.token_expires_at = compute_expiry(expires_in)
            user.refresh_token_expires_at = compute_expiry(refresh_token_expires_in)
            user.last_login_at = datetime.now(timezone.utc)
        else:
            # Create new user
            user = User(
                feishu_user_id=feishu_user_id,
                display_name=user_info.get("name") or user_info.get("en_name"),
                avatar_url=user_info.get("avatar_url"),
                email=user_info.get("email"),
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=compute_expiry(expires_in),
                refresh_token_expires_at=compute_expiry(refresh_token_expires_in),
                last_login_at=datetime.now(timezone.utc),
            )
            db.add(user)

        db.commit()
        db.refresh(user)

        logger.info(f"User {feishu_user_id} logged in successfully")

        # Redirect to frontend root with user info (single-port architecture)
        from urllib.parse import quote
        display_name = quote(user.display_name or '', safe='')
        avatar_url = quote(user.avatar_url or '', safe='')
        
        redirect_url = f"/?user_id={feishu_user_id}&display_name={display_name}&avatar_url={avatar_url}"
        
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        
        # Set authentication cookie (works better with reverse proxies than headers)
        response.set_cookie(
            key=USER_COOKIE_NAME,
            value=feishu_user_id,
            httponly=True,  # Prevent XSS attacks
            samesite="lax",  # Allow cookie on redirect from OAuth
            max_age=30 * 24 * 60 * 60,  # 30 days
        )
        
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("OAuth callback error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Authentication failed: {str(e)}",
        )


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)) -> UserResponse:
    """Get current user information."""
    return UserResponse(
        user_id=str(user.id),
        feishu_user_id=user.feishu_user_id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        token_expires_at=user.token_expires_at,
        is_token_valid=user.is_token_valid,
    )


@router.get("/token-status", response_model=TokenStatusResponse)
async def get_token_status(
    user: User = Depends(get_current_user),
) -> TokenStatusResponse:
    """Get current token status."""
    if not user.access_token:
        return TokenStatusResponse(
            is_valid=False,
            expires_at=None,
            message="No access token",
        )

    if not user.token_expires_at:
        return TokenStatusResponse(
            is_valid=True,
            expires_at=None,
            message="Token exists but expiry unknown",
        )

    from ..models import ensure_utc
    now = datetime.now(timezone.utc)
    expires_at = ensure_utc(user.token_expires_at)
    if expires_at < now:
        return TokenStatusResponse(
            is_valid=False,
            expires_at=user.token_expires_at,
            message="Token has expired",
        )

    remaining = expires_at - now
    hours = int(remaining.total_seconds() // 3600)
    minutes = int((remaining.total_seconds() % 3600) // 60)

    return TokenStatusResponse(
        is_valid=True,
        expires_at=user.token_expires_at,
        message=f"Token valid for {hours}h {minutes}m",
    )


@router.post("/logout")
async def logout(
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Log out the current user.
    
    Clears tokens from database and authentication cookie.
    Frontend should also clear local storage.
    """
    if user:
        user.access_token = None
        user.refresh_token = None
        user.token_expires_at = None
        user.refresh_token_expires_at = None
        db.commit()
        logger.info(f"User {user.feishu_user_id} logged out")

    response = JSONResponse(content={"message": "Logged out successfully"})
    
    # Clear authentication cookie
    response.delete_cookie(key=USER_COOKIE_NAME)
    
    return response


@router.post("/refresh")
async def refresh_token(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Manually refresh the access token.
    
    This is usually done automatically by the scheduler.
    """
    if not user.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No refresh token available. Please re-authenticate.",
        )

    oauth_client: FeishuOAuthClient = request.app.state.oauth_client

    try:
        (
            access_token,
            refresh_token,
            expires_in,
            refresh_token_expires_in,
        ) = await oauth_client.refresh_token(user.refresh_token)

        user.access_token = access_token
        user.refresh_token = refresh_token
        user.token_expires_at = compute_expiry(expires_in)
        user.refresh_token_expires_at = compute_expiry(refresh_token_expires_in)
        db.commit()

        logger.info(f"Token refreshed for user {user.feishu_user_id}")

        return {
            "message": "Token refreshed successfully",
            "expires_at": user.token_expires_at.isoformat(),
        }

    except Exception as e:
        logger.error(f"Token refresh failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Token refresh failed: {str(e)}",
        )
