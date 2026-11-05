"""共有プロンプトについて、ログインユーザー自身の投稿・いいね一覧の取得、更新、削除を行う API（/prompt_manage/api）。

Authenticated management endpoints for shared prompts.
Lists the user's own and liked prompts, and updates or deletes the user's own prompts (/prompt_manage/api).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request

from services.async_utils import run_blocking
from services.csrf import require_csrf
from services.prompt_attachment_storage import delete_prompt_attachment
from services.prompt_types import serialize_axes
from services.request_models import PromptUpdateRequest
from services.shared_content_service import SharedContentService
from services.web import (
    jsonify,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

# CSRF保護付きの、ログインユーザー自身のプロンプト管理用ルーター。
# Router for the signed-in user's own prompt management, with CSRF protection.
prompt_manage_api_bp = APIRouter(
    prefix="/prompt_manage/api",
    dependencies=[Depends(require_csrf)],
)
logger = logging.getLogger(__name__)


def _service() -> SharedContentService:
    # 共有URLを組み立てない用途（一覧・更新・削除）なので public_base_url は空で生成する。
    # Created with an empty public_base_url because these operations (list/update/delete) never build share URLs.
    return SharedContentService(public_base_url="")


def _serialize_liked_prompt(row: dict[str, Any]) -> dict[str, Any]:
    """いいねしたプロンプトの DB 行を API 出力用の辞書に変換する。

    日時は ISO 文字列にし、スキルの Python スクリプトが空なら resource_python_script か scripts/main.py リソースから補う。

    Convert a liked-prompt DB row into an API dict.

    Datetimes become ISO strings, and an empty skill_python_script is filled from resource_python_script or the scripts/main.py resource.
    """
    prompt_created_at = row.get("prompt_created_at")
    liked_at = row.get("liked_at")
    serialized = {
        "id": row.get("like_id"),
        "like_id": row.get("like_id"),
        "prompt_id": row.get("prompt_id"),
        "title": row.get("title"),
        "category": row.get("category"),
        "content": row.get("content"),
        "description": str(row.get("description") or ""),
        "author": row.get("author"),
        **serialize_axes(row),
        "input_examples": row.get("input_examples"),
        "output_examples": row.get("output_examples"),
        "prompt_created_at": prompt_created_at.isoformat() if hasattr(prompt_created_at, "isoformat") else prompt_created_at,
        "created_at": prompt_created_at.isoformat() if hasattr(prompt_created_at, "isoformat") else prompt_created_at,
        "liked_at": liked_at.isoformat() if hasattr(liked_at, "isoformat") else liked_at,
        "liked": True,
    }
    resources = row.get("resources")
    serialized["resources"] = resources if isinstance(resources, list) else []
    if not serialized.get("skill_python_script") and row.get("resource_python_script"):
        serialized["skill_python_script"] = str(row["resource_python_script"])
    if not serialized.get("skill_python_script"):
        for resource in serialized["resources"]:
            if isinstance(resource, dict) and resource.get("path") == "scripts/main.py":
                if isinstance(resource.get("content"), str):
                    serialized["skill_python_script"] = resource["content"]
                break
    serialized.pop("resource_python_script", None)
    return serialized


async def _fetch_my_prompts(user_id: int) -> list[dict[str, Any]]:
    """自分が投稿したプロンプトの一覧を取得し、軸フィールドとスキルのスクリプトを補って返す。

    Fetch the user's own prompts, adding axis fields and filling in the skill script where it is missing.
    """
    rows = await _service().list_my_prompts(user_id=user_id)
    prompts = []
    for row in rows:
        prompt = {**row, **serialize_axes(row)}
        resources = row.get("resources")
        prompt["resources"] = resources if isinstance(resources, list) else []
        if not prompt.get("skill_python_script") and row.get("resource_python_script"):
            prompt["skill_python_script"] = str(row["resource_python_script"])
        if not prompt.get("skill_python_script"):
            for resource in prompt["resources"]:
                if isinstance(resource, dict) and resource.get("path") == "scripts/main.py":
                    if isinstance(resource.get("content"), str):
                        prompt["skill_python_script"] = resource["content"]
                    break
        prompt.pop("resource_python_script", None)
        prompts.append(prompt)
    return prompts


async def _fetch_liked_prompts(user_id: int) -> list[dict[str, Any]]:
    """いいねしたプロンプトの一覧を、API 出力用の形に変換して返す。

    Fetch the prompts the user has liked, serialized for API output.
    """
    return [_serialize_liked_prompt(row) for row in await _service().list_liked_prompts(user_id=user_id)]


async def _update_prompt_for_user(
    user_id: int,
    prompt_id: int,
    payload: PromptUpdateRequest,
) -> int:
    """プロンプトを更新し、更新件数を返す（0 なら対象なし）。skill 以外の形式ではリソース未指定を空リスト扱いにする。

    Update a prompt and return the number of updated rows (0 means not found). For non-skill formats, unspecified resources are treated
    as an empty list.
    """
    resources = payload.resources
    if resources is None and payload.content_format != "skill":
        resources = []
    updated = await _service().update_prompt(
        user_id=user_id,
        prompt_id=prompt_id,
        title=payload.title,
        category=payload.category,
        content=payload.content,
        description=payload.description,
        content_format=payload.content_format,
        media_type=payload.media_type,
        input_examples=payload.input_examples,
        output_examples=payload.output_examples,
        attributes=payload.attributes,
        resources=resources,
    )
    return int(updated)


async def _delete_prompt_for_user(user_id: int, prompt_id: int) -> int:
    """プロンプトを削除し、削除件数だけを返す（添付ファイル情報は捨てる）。

    Delete a prompt and return only the deleted count, discarding the attachment info.
    """
    _, deleted = await _service().delete_prompt(user_id=user_id, prompt_id=prompt_id)
    return deleted


def _delete_prompt_attachment_files(attachments: list[dict[str, Any]]) -> int:
    """プロンプトの添付ファイルをストレージから削除し、削除できた数を返す（同期処理のため呼び出し側でスレッドに逃がす）。

    Delete prompt attachment files from storage and return how many were removed (blocking, so callers run it off the event loop).
    """
    return sum(delete_prompt_attachment(attachment) for attachment in attachments)


@prompt_manage_api_bp.get("/my_prompts", name="prompt_manage_api.get_my_prompts")
async def get_my_prompts(request: Request):
    """ログインユーザーが投稿したプロンプトの一覧を返す。

    Return the prompts posted by the signed-in user.
    """
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    try:
        return jsonify({"prompts": await _fetch_my_prompts(int(request.session["user_id"]))})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load my prompts.")


@prompt_manage_api_bp.get("/liked_prompts", name="prompt_manage_api.get_liked_prompts")
async def get_liked_prompts(request: Request):
    """ログインユーザーがいいねしたプロンプトの一覧を返す。

    Return the prompts liked by the signed-in user.
    """
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    try:
        return jsonify({"prompts": await _fetch_liked_prompts(int(request.session["user_id"]))})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to load liked prompts.")


@prompt_manage_api_bp.put("/prompts/{prompt_id}", name="prompt_manage_api.update_prompt")
async def update_prompt(prompt_id: int, request: Request):
    """自分のプロンプトを更新する。対象が無い（他人のものを含む）場合は 404 を返す。

    Update one of the user's own prompts; returns 404 when it is not found (including someone else's).
    """
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response
    payload, validation_error = validate_payload_model(
        data,
        PromptUpdateRequest,
        error_message="必要なフィールドが不足しています。",
    )
    if validation_error is not None:
        return validation_error
    try:
        updated = await _update_prompt_for_user(int(request.session["user_id"]), prompt_id, payload)
        if updated == 0:
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        return jsonify({"message": "プロンプトが更新されました。"})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to update prompt.")


@prompt_manage_api_bp.delete("/prompts/{prompt_id}", name="prompt_manage_api.delete_prompt")
async def delete_prompt(prompt_id: int, request: Request):
    """自分のプロンプトを削除する。DB の削除後に添付ファイルを消すが、ファイル削除の失敗は記録するだけで成功応答は変えない。

    Delete one of the user's own prompts. Attachment files are removed after the DB delete; a file-removal failure is only logged and
    does not change the success response.
    """
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    try:
        attachments, deleted = await _service().delete_prompt(
            user_id=int(request.session["user_id"]),
            prompt_id=prompt_id,
        )
        if deleted == 0:
            return jsonify({"error": "対象のプロンプトが見つかりませんでした。"}, status_code=404)
        try:
            await run_blocking(_delete_prompt_attachment_files, attachments)
        except Exception:
            logger.exception("Failed to delete prompt attachment files for prompt %s.", prompt_id)
        return jsonify({"message": "プロンプトが削除されました。"})
    except Exception:
        return log_and_internal_server_error(logger, "Failed to delete prompt.")
