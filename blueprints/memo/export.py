from __future__ import annotations

# メモのエクスポート（Markdown / JSON / CSV）
# Memo export (Markdown / JSON / CSV)

import logging

from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import SQLAlchemyError

from services.error_messages import ERROR_LOGIN_REQUIRED
from services.web import (
    jsonify,
    log_and_internal_server_error,
)

from services.repositories.memo_helpers import user_id_from_session

from . import memo_bp
from ._common import _memo_attr

logger = logging.getLogger(__name__)


@memo_bp.get("/api/export", name="memo.api_export")
async def api_export_memos(
    request: Request,
    format: str = "markdown",
    ids: str = "",
):
    """
    メモデータをエクスポート形式 (Markdown, JSON, CSV) でダウンロードするエンドポイント
    Endpoint to export and stream memos as files in Markdown, JSON, or CSV formats.

    Args:
        request (Request): FastAPI リクエストオブジェクト / FastAPI Request.
        format (str): エクスポートするファイル形式 / Output file format ("markdown", "json", "csv").
        ids (str): 対象メモIDのカンマ区切り文字列 / Comma-separated list of memo IDs to filter.

    Returns:
        StreamingResponse: ファイルストリームレスポンス / StreamingResponse representing file attachment.
    """
    # ユーザー認証の確認
    # Verify user authentication.
    user_id = user_id_from_session(request.session)
    if user_id is None:
        return jsonify({"status": "fail", "error": ERROR_LOGIN_REQUIRED}, status_code=401)

    memo_ids: list[int] | None = None
    # 特定のメモID一覧がカンマ区切りで渡された場合、パースする
    # Parse list of specific memo IDs if passed as comma-separated string.
    if ids.strip():
        try:
            memo_ids = [int(x.strip()) for x in ids.split(",") if x.strip()]
        except ValueError:
            return jsonify({"status": "fail", "error": "IDの形式が不正です。"}, status_code=400)

    # サポートされている形式かどうか確認
    # Validate target export format.
    valid_formats = {"markdown", "json", "csv"}
    if format not in valid_formats:
        format = "markdown"

    try:
        # 指定されたメモデータをDBから取得
        # Retrieve target memos for export.
        memos = await _memo_attr("_fetch_memos_for_export")(user_id, memo_ids)

        # フォーマットに応じたファイルデータおよびContent-Typeの設定
        # Format mapping and headers config for file streaming.
        if format == "json":
            content = _memo_attr("_build_json_export")(memos)
            media_type = "application/json"
            filename = "memos.json"
        elif format == "csv":
            content = _memo_attr("_build_csv_export")(memos)
            media_type = "text/csv; charset=utf-8"
            filename = "memos.csv"
        else:
            content = _memo_attr("_build_markdown_export")(memos)
            media_type = "text/markdown; charset=utf-8"
            filename = "memos.md"

        # ストリーミングレスポンスとしてクライアントに返却（文字エンコーディングはUTF-8）
        # Return StreamingResponse with matching content disposition and UTF-8 encoding.
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )
    except SQLAlchemyError:
        # エクスポート失敗時のエラーハンドリング
        # Handle exceptions in formatting or fetching memos.
        return log_and_internal_server_error(logger, "Export failed.", status="fail")

