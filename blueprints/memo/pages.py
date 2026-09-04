from __future__ import annotations

# Next.js のメモ画面へリダイレクトするレガシーページルート
# Legacy page route that redirects to the Next.js memo screen

from fastapi import Request

from services.web import redirect_to_frontend

from . import memo_bp


@memo_bp.api_route("", methods=["GET", "POST"], name="memo.create_memo")
async def create_memo(request: Request):
    """
    フロントエンドへのリダイレクト用デフォルトエントリーポイント
    Fallback/default route to redirect memo queries directly to the frontend app.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request object.

    Returns:
        Response: リダイレクトレスポンス / Redirect response.
    """
    # GETリクエストなら302、POSTリクエストなら303でリダイレクト
    # Redirect with 302 for GET or 303 for POST.
    status_code = 302 if request.method == "GET" else 303
    return redirect_to_frontend(request, status_code=status_code)

