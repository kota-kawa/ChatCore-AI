"""認証モジュール間で依存を引く小さな仕組み。

auth_* の各モジュールは blueprints.auth の属性を実行時に引くことで、テストが blueprints.auth 側を差し替えるだけで挙動を置き換えられる。

Small indirection that lets the auth_* modules resolve dependencies from blueprints.auth at call time,
so tests can replace behavior by patching attributes on blueprints.auth only.
"""

from __future__ import annotations

import sys
from typing import Any

from fastapi import Request

from services.async_utils import maybe_await


# 読み込み済みの blueprints.auth モジュールを返す。未読み込みは設定ミスなので例外にする。
# Return the loaded blueprints.auth module; raise when it is not loaded.
def auth_module() -> Any:
    module = sys.modules.get("blueprints.auth")
    if module is None:  # pragma: no cover - defensive guard for unusual imports
        raise RuntimeError("blueprints.auth is not loaded")
    return module


# blueprints.auth から名前で依存を引く。呼び出し時に引くので、差し替えが反映される。
# Look up a dependency by name on blueprints.auth at call time, so patches take effect.
def dep(name: str) -> Any:
    return getattr(auth_module(), name)


async def call_dependency(name: str, *args: Any, **kwargs: Any) -> Any:
    """認証の依存を名前で呼ぶ。DB 処理をスレッドへ逃がさず、同じイベントループで実行する。

    Call an auth dependency without routing database work through a thread.
    """
    return await maybe_await(dep(name)(*args, **kwargs))


# 試行回数制限サービスを blueprints.auth 経由で取得する。
# Fetch the auth limit service through blueprints.auth.
def get_auth_limit_service_dependency(request: Request) -> Any:
    return dep("get_auth_limit_service")(request)


# LLM 日次上限サービスを blueprints.auth 経由で取得する。
# Fetch the LLM daily limit service through blueprints.auth.
def get_llm_daily_limit_service_dependency(request: Request) -> Any:
    return dep("get_llm_daily_limit_service")(request)
