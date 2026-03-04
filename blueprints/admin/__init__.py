from fastapi import APIRouter, Depends

from services.csrf import require_csrf

admin_bp = APIRouter(prefix="/admin", dependencies=[Depends(require_csrf)])

from . import views  # noqa: F401

__all__ = ["admin_bp"]
