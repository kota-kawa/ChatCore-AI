# prompt_share.py
from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from services.web import frontend_url, redirect_to_frontend

# プロンプト共有用ルーターの初期化
# Initialize APIRouter for prompt share.
prompt_share_bp = APIRouter(prefix="/prompt_share")


# プロンプト共有トップ画面へのGETリクエストをハンドリングするエンドポイント
# Endpoint handling the GET request for the prompt share top page.
@prompt_share_bp.get("/", name="prompt_share.index")
async def index(request: Request):
    """
    Next.js 側のプロンプト共有画面へリダイレクト
    Redirect to the prompt share page on the Next.js frontend.
    """
    # フロントエンドへリダイレクト
    # Redirect to frontend.
    return redirect_to_frontend(request)


# 投稿したプロンプトの管理は設定画面に一本化したため、旧 URL は設定の該当セクションへ恒久転送する
# Managing posted prompts now lives only in settings, so the legacy URL permanently forwards there.
@prompt_share_bp.get("/manage_prompts", name="prompt_share.manage_prompts")
async def manage_prompts(request: Request):
    """
    旧「投稿したプロンプト」画面の URL を設定画面の「投稿したプロンプト」へ転送する
    Forward the legacy posted-prompts URL to the settings "posted prompts" section.
    """
    return RedirectResponse(frontend_url("/settings", query="section=prompts"), status_code=308)

