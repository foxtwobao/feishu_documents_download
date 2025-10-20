"""Authentication routes for the Web UI."""

from __future__ import annotations

import logging
from typing import Dict
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..auth import FeishuOAuthClient, compute_expiry
from ..dependencies import db_session, get_current_user
from ..models import User
from ..schemas import OAuthCallbackRequest, OAuthRedirectResponse, OAuthTokenResponse
from ..state import OAuthStateStore

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/authorize", response_model=OAuthRedirectResponse)
async def start_authorization(request: Request) -> OAuthRedirectResponse:
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client
    state_store: OAuthStateStore = request.app.state.oauth_state_store
    if not oauth_client.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth 未配置")
    state = state_store.issue()
    authorization_url = oauth_client.build_authorization_url(state)
    return OAuthRedirectResponse(authorization_url=authorization_url, state=state)


async def _complete_authorization(request: Request, session: Session, code: str, state: str) -> User:
    oauth_client: FeishuOAuthClient = request.app.state.oauth_client
    state_store: OAuthStateStore = request.app.state.oauth_state_store
    if not oauth_client.enabled:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="OAuth 未配置")
    if not state_store.consume(state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="state 校验失败")

    access_token, refresh_token, expires_in = await oauth_client.exchange_code(code)
    profile = await oauth_client.fetch_user_info(access_token)
    feishu_user_id = profile.get("user_id")
    if not feishu_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未能获取用户信息")

    user = session.query(User).filter_by(feishu_user_id=feishu_user_id).one_or_none()
    if user is None:
        user = User(feishu_user_id=feishu_user_id)

    user.display_name = profile.get("name") or profile.get("en_name") or user.display_name
    avatar_url = (
        profile.get("avatar_url")
        or profile.get("avatar_big")
        or profile.get("avatar_middle")
        or profile.get("avatar_small")
        or profile.get("avatar_thumb")
    )
    user.avatar_url = avatar_url or user.avatar_url
    user.access_token = access_token
    user.refresh_token = refresh_token
    user.token_expires_at = compute_expiry(expires_in)
    session.add(user)
    session.flush()
    return user


def _build_frontend_redirect(request: Request, **params: str) -> str:
    base = request.app.state.config.web.oauth.base_url or str(request.base_url)
    base = base.rstrip("/")
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return f"{base}/auth/callback?{query}" if query else f"{base}/auth/callback"


@router.get("/callback")
async def complete_authorization_redirect(
    code: str,
    state: str,
    request: Request,
    session: Session = Depends(db_session),
):
    try:
        user = await _complete_authorization(request, session, code, state)
    except HTTPException as exc:
        target = _build_frontend_redirect(
            request,
            status="error",
            message=str(exc.detail or exc.status_code),
        )
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    except Exception as exc:  # pragma: no cover - network / API failure path
        logger.exception("Feishu OAuth callback failed: %s", exc)
        target = _build_frontend_redirect(request, status="error", message="internal_error")
        return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)

    params: Dict[str, str] = {
        "status": "success",
        "user_id": str(user.id),
    }
    if user.display_name:
        params["display_name"] = user.display_name
    if user.avatar_url:
        params["avatar_url"] = user.avatar_url
    target = _build_frontend_redirect(request, **params)
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/callback", response_model=OAuthTokenResponse)
async def complete_authorization_api(
    payload: OAuthCallbackRequest,
    request: Request,
    session: Session = Depends(db_session),
) -> OAuthTokenResponse:
    user = await _complete_authorization(request, session, payload.code, payload.state)
    return OAuthTokenResponse(
        success=True,
        message="授权成功",
        user_id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )


@router.post("/logout", response_model=OAuthTokenResponse)
async def logout(user: User = Depends(get_current_user), session: Session = Depends(db_session)) -> OAuthTokenResponse:
    user.access_token = None
    user.refresh_token = None
    user.token_expires_at = None
    session.add(user)
    return OAuthTokenResponse(
        success=True,
        message="已退出登录",
        user_id=user.id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )
