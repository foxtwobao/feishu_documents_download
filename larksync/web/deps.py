"""FastAPI dependency injection helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import User

# Cookie name for user authentication
USER_COOKIE_NAME = "larksync_user_id"


def get_current_user_id(
    x_user_id: Optional[str] = Header(None),
    cookie_user_id: Optional[str] = Cookie(None, alias=USER_COOKIE_NAME),
) -> Optional[str]:
    """
    Extract user ID from Cookie (preferred) or Header (fallback).
    
    Cookie is preferred because it works better with reverse proxies.
    Header is kept for backwards compatibility and API testing.
    """
    # Prefer Cookie, fallback to Header
    return cookie_user_id or x_user_id


def _is_user_allowed(request: Request, user: User) -> bool:
    config = request.app.state.config
    raw = config.web.allow_download_user_ids
    if not raw:
        return False
    if raw.strip() == "*":
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return user.feishu_user_id in allowed


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_id),
) -> User:
    """
    Get the current authenticated user.
    
    Raises:
        HTTPException: If user is not authenticated or not found
    """
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please log in.",
        )

    # Try to find user by feishu_user_id
    user = db.query(User).filter(User.feishu_user_id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please log in again.",
        )

    if not _is_user_allowed(request, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User is not allowed to use this system",
        )
    return user


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(get_current_user_id),
) -> Optional[User]:
    """
    Get the current user if authenticated, otherwise return None.
    """
    if not user_id:
        return None

    user = db.query(User).filter(User.feishu_user_id == user_id).first()
    if not user:
        return None
    if not _is_user_allowed(request, user):
        return None
    return user


def require_valid_token(user: User = Depends(get_current_user)) -> User:
    """
    Ensure the user has a valid access token.
    
    Raises:
        HTTPException: If token is missing or expired
    """
    if not user.access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is missing. Please re-authenticate.",
        )

    from .models import ensure_utc
    expires_at = ensure_utc(user.token_expires_at)
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token has expired. Please re-authenticate.",
        )

    return user
