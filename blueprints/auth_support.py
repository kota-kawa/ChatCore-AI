from __future__ import annotations

import inspect
import sys
from typing import Any

from fastapi import Request


def auth_module() -> Any:
    module = sys.modules.get("blueprints.auth")
    if module is None:  # pragma: no cover - defensive guard for unusual imports
        raise RuntimeError("blueprints.auth is not loaded")
    return module


def dep(name: str) -> Any:
    return getattr(auth_module(), name)


async def await_result(value: Any) -> Any:
    """Await async dependencies while keeping unit-test doubles lightweight."""
    if inspect.isawaitable(value):
        return await value
    return value


async def call_dependency(name: str, *args: Any, **kwargs: Any) -> Any:
    """Call an auth dependency without routing database work through a thread."""
    return await await_result(dep(name)(*args, **kwargs))


def get_auth_limit_service_dependency(request: Request) -> Any:
    return dep("get_auth_limit_service")(request)


def get_llm_daily_limit_service_dependency(request: Request) -> Any:
    return dep("get_llm_daily_limit_service")(request)
