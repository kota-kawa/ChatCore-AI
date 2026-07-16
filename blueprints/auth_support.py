from __future__ import annotations

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


def get_auth_limit_service_dependency(request: Request) -> Any:
    return dep("get_auth_limit_service")(request)


def get_llm_daily_limit_service_dependency(request: Request) -> Any:
    return dep("get_llm_daily_limit_service")(request)
