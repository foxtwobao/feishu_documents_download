"""FastAPI dependency helpers."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import LarkSyncConfig, load_config
from .database import get_session
from .models import User


class ConfigProvider:
    def __init__(self, path: str | None = None) -> None:
        self._path = path
        self._config: LarkSyncConfig | None = None

    def __call__(self) -> LarkSyncConfig:
        if self._config is None:
            self._config = load_config()
        return self._config


config_dependency = ConfigProvider()


def db_session() -> Session:
    yield from get_session()


UserHeader = Annotated[Optional[str], Header(alias="X-User-ID")]


def get_current_user(
    request: Request,
    user_id_header: UserHeader = None,
    session: Session = Depends(db_session),
) -> User:
    user_id_value = user_id_header or request.query_params.get("user_id")
    if not user_id_value:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing user identifier")
    try:
        user_id = int(user_id_value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user identifier") from None

    user = session.query(User).filter_by(id=user_id).one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user
