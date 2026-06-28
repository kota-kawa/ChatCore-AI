from __future__ import annotations

import sys
from typing import Any


def auth_module() -> Any:
    module = sys.modules.get("blueprints.auth")
    if module is None:  # pragma: no cover - defensive guard for unusual imports
        raise RuntimeError("blueprints.auth is not loaded")
    return module


def dep(name: str) -> Any:
    return getattr(auth_module(), name)
