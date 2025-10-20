"""API routers."""

from .auth import router as auth_router
from .tasks import router as task_router
from .users import router as user_router

__all__ = ["auth_router", "task_router", "user_router"]
