# prompt_share.py
from fastapi import APIRouter, Request

from services.web import redirect_to_frontend

# プロンプト共有用ルーターの初期化
# Initialize APIRouter for prompt share.
prompt_share_bp = APIRouter(prefix="/prompt_share")


# プロンプト共有トップ画面へのGETリクエストをハンドリングするエンドポイント
# Handle GET requests for prompt share top view, redirecting to frontend app.
@prompt_share_bp.get("/", name="prompt_share.index")
async def index(request: Request):
    """Next.js 側のプロンプト共有画面へリダイレクト"""
    # フロントエンドへリダイレクト
    # Redirect to frontend.
    return redirect_to_frontend(request)


# 投稿したプロンプト管理画面へのGETリクエストをハンドリングするエンドポイント
# Handle GET requests for published prompt management view, redirecting to frontend.
@prompt_share_bp.get("/manage_prompts", name="prompt_share.manage_prompts")
async def manage_prompts(request: Request):
    """Next.js 側の投稿したプロンプト画面へリダイレクト"""
    # フロントエンドへリダイレクト
    # Redirect to frontend.
    return redirect_to_frontend(request)
