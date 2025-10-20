"""User related endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..models import User
from ..schemas import UserInfoResponse

router = APIRouter()


@router.get("/me", response_model=UserInfoResponse)
def me(user: User = Depends(get_current_user)) -> UserInfoResponse:
    return UserInfoResponse(
        id=user.id,
        feishu_user_id=user.feishu_user_id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )
