# prompt_share.py
from fastapi import APIRouter, Request

from services.web import redirect_to_frontend

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


# 投稿したプロンプト管理画面へのGETリクエストをハンドリングするエンドポイント
# Endpoint handling the GET request for the managed prompts page.
@prompt_share_bp.get("/manage_prompts", name="prompt_share.manage_prompts")
async def manage_prompts(request: Request):
    """
    Next.js 側の投稿したプロンプト画面へリダイレクト
    Redirect to the managed prompts page on the Next.js frontend.
    """
    # フロントエンドへリダイレクト
    # Redirect to frontend.
    return redirect_to_frontend(request)

