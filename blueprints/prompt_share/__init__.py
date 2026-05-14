# prompt_share.py
from fastapi import APIRouter, Request

from services.web import redirect_to_frontend

prompt_share_bp = APIRouter(prefix="/prompt_share")


@prompt_share_bp.get("/", name="prompt_share.index")
async def index(request: Request):
    """Next.js 側のプロンプト共有画面へリダイレクト"""
    return redirect_to_frontend(request)


@prompt_share_bp.get("/manage_prompts", name="prompt_share.manage_prompts")
async def manage_prompts(request: Request):
    """Next.js 側の投稿したプロンプト画面へリダイレクト"""
    return redirect_to_frontend(request)
