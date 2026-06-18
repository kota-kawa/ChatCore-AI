# prompt_share/prompt_share_api.py
import logging
import os
import re
from uuid import uuid4
from typing import Any

from fastapi import APIRouter, Depends, Request
from werkzeug.utils import secure_filename

from services.async_utils import run_blocking
from services.auth_limits import consume_rate_limit, get_request_client_ip
from services.csrf import require_csrf
from services.db import get_db_connection
from services.request_models import (
    PromptCommentCreateRequest,
    PromptCommentReportRequest,
    PromptLikeRequest,
    PromptTaskCreateRequest,
    SharedPromptCreateRequest,
)
from services.web import (
    BASE_DIR,
    jsonify,
    jsonify_rate_limited,
    log_and_internal_server_error,
    require_json_dict,
    validate_payload_model,
)

# CSRF保護を設定したプロンプト共有用APIRouterの初期化
# Initialize FastAPI APIRouter for prompt sharing with CSRF protection.
prompt_share_api_bp = APIRouter(prefix="/prompt_share/api", dependencies=[Depends(require_csrf)])
logger = logging.getLogger(__name__)

# プロンプトタイプの定数定義
# Constants defining prompt types.
PROMPT_TYPE_TEXT = "text"
PROMPT_TYPE_IMAGE = "image"
PROMPT_TYPE_SKILL = "skill"

# プロンプトの画像アップロード先ディレクトリの設定
# Directory path for prompt image uploads.
PROMPT_IMAGE_UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "frontend",
    "public",
    "static",
    "uploads",
    "prompt_share",
)

# アップロードした画像を参照するためのURL接頭辞
# URL prefix for accessing uploaded prompt images.
PROMPT_IMAGE_URL_PREFIX = "/static/uploads/prompt_share"

# プロンプト画像アップロードの最大ファイルサイズ（5MB）
# Maximum file size allowed for prompt image uploads (5MB).
PROMPT_IMAGE_MAX_BYTES = 5 * 1024 * 1024

# アップロード可能な画像ファイルの拡張子
# Permitted image file extensions.
PROMPT_IMAGE_ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

# コメント投稿制限用の設定値
# Comment rate limit and cooldown settings.
PROMPT_COMMENT_RATE_WINDOW_SECONDS = 300
PROMPT_COMMENT_PER_IP_LIMIT = 20
PROMPT_COMMENT_PER_USER_LIMIT = 12
PROMPT_COMMENT_COOLDOWN_SECONDS = 10
PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS = 60
PROMPT_COMMENT_LIST_LIMIT = 200
PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD = 3
PROMPT_COMMENT_MAX_URLS = 3

# コメント内のURL検知用正規表現パターン
# Regular expression pattern to detect URLs inside comments.
PROMPT_COMMENT_LINK_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)


# レコード辞書またはタプルからIDフィールド値を安全に抽出する関数
# Safely extract the ID field from a record dictionary, tuple, or None.
def _extract_id(row: dict[str, Any] | tuple[Any, ...] | None) -> Any:
    """
    クエリ結果オブジェクト（dict、tuple、またはNone）から一意のIDフィールド値を安全に取得する。
    Safely extract the primary ID value from a query result database row.
    """
    # 入力が空の場合はNoneを返します
    # Return None if the input is None.
    if row is None:
        return None
    # 辞書の場合はキー指定で、タプルの場合はインデックスでIDを取得します
    # Retrieve ID by key for dictionaries or by index for tuples.
    if isinstance(row, dict):
        return row.get("id")
    return row[0]


# 入力されたプロンプトタイプを定義済みの3つ(text, image, skill)のいずれかに標準化する関数
# Standardize the input prompt type to one of the defined categories (text, image, skill).
def _normalize_prompt_type(value: Any) -> str:
    """
    入力されたプロンプトタイプ文字列をトリム・小文字化し、定義済みの標準タイプ（text/image/skill）へマッピングする。
    Normalize the input prompt type string and resolve aliases to standard categories.
    """
    normalized = str(value or "").strip().lower()
    # "skill"系の各エイリアスに対応
    # Support various "skill" alias variations.
    if normalized in {PROMPT_TYPE_SKILL, "skill_prompt", "claude_skill", "codex_skill"}:
        return PROMPT_TYPE_SKILL
    # "image"系の各エイリアスに対応
    # Support various "image" alias variations.
    if normalized in {PROMPT_TYPE_IMAGE, "image_prompt", "image-generation", "image_generation"}:
        return PROMPT_TYPE_IMAGE
    return PROMPT_TYPE_TEXT


# プロンプトのDBレコードをJSONレスポンス用にシリアライズ・整形する関数
# Serialize and format a prompt DB record row for the JSON response payload.
def _serialize_prompt_row(row: dict[str, Any]) -> dict[str, Any]:
    """
    DBのプロンプトレコードを辞書から取り出し、作成日時のISO文字列化やオプショナルなフィールドの初期値補正を行う。
    Convert database prompt attributes into a clean API response dictionary structure.
    """
    prompt = dict(row)
    created_at = prompt.get("created_at")
    # 作成日時が datetime の場合、ISO フォーマット文字列に変換
    # Format created_at to ISO string if it is a datetime object.
    if created_at is not None and hasattr(created_at, "isoformat"):
        prompt["created_at"] = created_at.isoformat()
    # プロンプトタイプの正規化
    # Normalize the prompt type field.
    prompt["prompt_type"] = _normalize_prompt_type(prompt.get("prompt_type"))
    prompt["reference_image_url"] = prompt.get("reference_image_url") or None
    prompt["skill_markdown"] = prompt.get("skill_markdown") or ""
    prompt["skill_python_script"] = prompt.get("skill_python_script") or ""
    prompt["comment_count"] = int(prompt.get("comment_count") or 0)
    return prompt


# コメントのDBレコード行をシリアライズし、削除権限フラグ等を付与する関数
# Serialize a comment DB row and append contextual flags (ownership, delete permission).
def _serialize_prompt_comment_row(row: dict[str, Any], actor_user_id: int | None) -> dict[str, Any]:
    """
    DBのコメントレコードを整形し、現在アクセスしているユーザー(actor_user_id)に応じた削除権限フラグ等を設定する。
    Format a database comment record and calculate ownership and permission flags relative to the active actor.
    """
    created_at = row.get("created_at")
    user_id = row.get("user_id")
    prompt_owner_id = row.get("prompt_owner_id")
    actor_is_admin = bool(row.get("actor_is_admin"))
    mine = actor_user_id is not None and user_id == actor_user_id
    # 管理者、本人、またはプロンプト投稿者自身である場合に削除可能とする
    # Allowed to delete if admin, comment author, or prompt author.
    can_delete = bool(
        actor_is_admin
        or mine
        or (actor_user_id is not None and prompt_owner_id == actor_user_id)
    )
    return {
        "id": row.get("id"),
        "prompt_id": row.get("prompt_id"),
        "user_id": user_id,
        "author_name": row.get("author_name") or "ユーザー",
        "content": row.get("content") or "",
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "mine": mine,
        "can_delete": can_delete,
    }


# コメント本文に大量のURLリンク（閾値超え）が含まれているか判定する関数
# Determine if comment content contains more link patterns than the allowed threshold.
def _contains_too_many_links(content: str) -> bool:
    """
    コメント本文に含まれるリンク（http/https/www等）の数が許容限度数を超えているか判定する。
    Check if the number of URLs or link syntax strings in the comment text exceeds the allowed max limit.
    """
    return len(PROMPT_COMMENT_LINK_PATTERN.findall(content or "")) > PROMPT_COMMENT_MAX_URLS


# コメント投稿に対するレート制限を判定・消費する関数
# Evaluate and consume rate limits/cooldowns for comment submissions.
def _consume_prompt_comment_create_limits(
    request: Request,
    user_id: int,
) -> tuple[bool, str | None, int | None]:
    """
    接続IPアドレスおよびユーザーIDをベースに、一定時間内のコメント投稿制限（IP制限、ユーザー制限、連投クールダウン）を判定する。
    Check and update comment rate limiting for both user ID and client IP to prevent spamming.
    """
    client_ip = get_request_client_ip(request)

    # IP単位での短期レート制限をチェック
    # Check rate limit per client IP address.
    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:ip",
        client_ip,
        limit=PROMPT_COMMENT_PER_IP_LIMIT,
        window_seconds=PROMPT_COMMENT_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメント投稿の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    # ユーザーID単位でのレート制限をチェック
    # Check rate limit per user ID.
    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:user",
        str(user_id),
        limit=PROMPT_COMMENT_PER_USER_LIMIT,
        window_seconds=PROMPT_COMMENT_RATE_WINDOW_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメント投稿の試行回数が多すぎます。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    # 連続投稿防止クールダウンをチェック
    # Enforce continuous post submission cooldown.
    allowed, _, retry_after = consume_rate_limit(
        "prompt_comment:create:cooldown",
        str(user_id),
        limit=1,
        window_seconds=PROMPT_COMMENT_COOLDOWN_SECONDS,
    )
    if not allowed:
        return (
            False,
            (
                "コメントは短時間に連続投稿できません。"
                f"{retry_after}秒ほど待ってから再試行してください。"
            ),
            retry_after,
        )

    return True, None, None


# プロンプトに関連付けられた参照画像ファイルをストレージから物理削除する関数
# Permanently delete the stored reference image file from filesystem.
def _delete_prompt_reference_image(image_url: str | None) -> None:
    """
    指定された画像URLに該当する物理ファイルをローカルストレージ（アップロードディレクトリ）から削除する。
    Delete the actual image file on the filesystem that corresponds to the given reference image URL.
    """
    if not image_url or not image_url.startswith(f"{PROMPT_IMAGE_URL_PREFIX}/"):
        return
    filename = image_url.rsplit("/", 1)[-1].strip()
    if not filename:
        return
    filepath = os.path.join(PROMPT_IMAGE_UPLOAD_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


# アップロードされた参照画像を保存し、保存されたURLを返却する関数
# Save uploaded reference image and return its public URL path.
def _save_prompt_reference_image(upload_file: Any, user_id: int) -> str:
    """
    アップロードされたファイルを検証（拡張子、MIMEタイプ、ファイルサイズ）し、問題なければ一意のファイル名で保存する。
    Validate and save the uploaded reference image, enforcing limits on size and file format.
    """
    filename = secure_filename(getattr(upload_file, "filename", "") or "")
    if not filename:
        raise ValueError("画像ファイル名が不正です。")

    extension = os.path.splitext(filename)[1].lower()
    if extension not in PROMPT_IMAGE_ALLOWED_EXTENSIONS:
        raise ValueError("画像は PNG / JPG / WebP / GIF のいずれかを指定してください。")

    content_type = str(getattr(upload_file, "content_type", "") or "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ValueError("画像ファイルのみアップロードできます。")

    # 保存ディレクトリを自動生成
    # Automatically create directory structure if not exists.
    os.makedirs(PROMPT_IMAGE_UPLOAD_DIR, exist_ok=True)
    stored_filename = f"user_{user_id}_{uuid4().hex}{extension}"
    filepath = os.path.join(PROMPT_IMAGE_UPLOAD_DIR, stored_filename)
    file_obj = upload_file.file
    total_size = 0

    try:
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)

        # ファイルをチャンクごとに分割して保存し、サイズ閾値超えを判定
        # Write chunks to disk and check file size.
        with open(filepath, "wb") as out_f:
            while True:
                chunk = file_obj.read(1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > PROMPT_IMAGE_MAX_BYTES:
                    raise ValueError("画像サイズは5MB以下にしてください。")
                out_f.write(chunk)
    except Exception:
        # 途中での失敗時には作成途中の物理ファイルを削除
        # Delete broken file on failure.
        if os.path.exists(filepath):
            os.remove(filepath)
        raise
    finally:
        if hasattr(file_obj, "seek"):
            try:
                file_obj.seek(0)
            except Exception:
                pass

    return f"{PROMPT_IMAGE_URL_PREFIX}/{stored_filename}"


# 共有中プロンプトの一覧を、コメント数といいね状態を含めてDBから取得する関数
# Fetch public shared prompts including comment counts and contextual like state.
def _get_prompts_with_flags(user_id: int | None) -> list[dict[str, Any]]:
    """
    公開中プロンプトの一覧を、コメント総数、および現在ログイン中ユーザーのLike状態と結合して取得する。
    Fetch all public, non-deleted prompts joined with like state for the optional user ID.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # 公開プロンプトとユーザーごとのLike状態をJOINで取得
        # Execute query to select public prompts with flags joined with the specific user ID.
        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.content,
                COALESCE(u.username, p.author, 'ユーザー') AS author,
                p.input_examples,
                p.output_examples,
                p.ai_model,
                p.prompt_type,
                p.reference_image_url,
                p.skill_markdown,
                p.skill_python_script,
                p.created_at,
                COALESCE(pc.comment_count, 0) AS comment_count,
                CASE WHEN pl.id IS NOT NULL THEN TRUE ELSE FALSE END AS liked
            FROM prompts AS p
            LEFT JOIN users AS u
              ON u.id = p.user_id
            LEFT JOIN (
                SELECT prompt_id, COUNT(*) AS comment_count
                FROM prompt_comments
                WHERE deleted_at IS NULL
                  AND hidden_by_reports_at IS NULL
                GROUP BY prompt_id
            ) AS pc
              ON pc.prompt_id = p.id
            LEFT JOIN prompt_likes AS pl
              ON pl.user_id = %s
             AND pl.prompt_id = p.id
            WHERE p.is_public = TRUE
              AND p.deleted_at IS NULL
            ORDER BY p.created_at DESC
            """,
            (user_id,),
        )
        prompts = []
        # 結果の整形・真偽値キャストを実行
        # Normalize and serialize each result row.
        for row in cursor.fetchall():
            prompt = _serialize_prompt_row(dict(row))
            prompt["liked"] = bool(prompt.get("liked"))
            prompt["comment_count"] = int(prompt.get("comment_count") or 0)
            prompts.append(prompt)
        return prompts
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 指定された公開プロンプトIDの詳細情報を取得する関数
# Fetch public shared prompt detail info by ID.
def _get_public_prompt_by_id(prompt_id: int) -> dict[str, Any] | None:
    """
    指定されたIDに一致する公開かつ未削除のプロンプト情報を、有効コメント数とともにDBから取得する。
    Retrieve details of a single public prompt matching the specified ID from the database.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # サブクエリで有効コメント数を含めてプロンプト詳細を1行取得
        # Query details and count comments.
        cursor.execute(
            """
            SELECT
                p.id,
                p.title,
                p.category,
                p.content,
                COALESCE(u.username, p.author, 'ユーザー') AS author,
                p.input_examples,
                p.output_examples,
                p.ai_model,
                p.prompt_type,
                p.reference_image_url,
                p.skill_markdown,
                p.skill_python_script,
                (
                    SELECT COUNT(*)
                    FROM prompt_comments AS pc
                    WHERE pc.prompt_id = p.id
                      AND pc.deleted_at IS NULL
                      AND pc.hidden_by_reports_at IS NULL
                ) AS comment_count,
                p.created_at
            FROM prompts AS p
            LEFT JOIN users AS u
              ON u.id = p.user_id
            WHERE p.id = %s
              AND p.is_public = TRUE
              AND p.deleted_at IS NULL
            LIMIT 1
            """,
            (prompt_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None
        return _serialize_prompt_row(dict(row))
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 新規プロンプト共有レコードをDBに登録・保存する関数
# Insert a new public shared prompt record into the database.
def _create_prompt_for_user(
    user_id: int,
    title: str,
    category: str,
    content: str,
    prompt_type: str,
    input_examples: str,
    output_examples: str,
    ai_model: str,
    reference_image_url: str | None,
    skill_markdown: str,
    skill_python_script: str,
) -> Any:
    """
    投稿ユーザー情報と指定された属性値を用いて、新規プロンプトデータをデータベースに挿入する。
    Create and store a new public shared prompt record in the database for the active user.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # 投稿者名は入力値ではなく投稿ユーザーの username を保存する。
        # 表示時は users.username を JOIN して取得するため、username の変更にも追従する。
        query = """
            INSERT INTO prompts (
                title,
                category,
                content,
                author,
                prompt_type,
                reference_image_url,
                skill_markdown,
                skill_python_script,
                input_examples,
                output_examples,
                ai_model,
                user_id,
                is_public,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s,
                (SELECT COALESCE(username, 'ユーザー') FROM users WHERE id = %s),
                %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW()
            )
            RETURNING id
        """
        cursor.execute(
            query,
            (
                title,
                category,
                content,
                user_id,
                _normalize_prompt_type(prompt_type),
                reference_image_url,
                skill_markdown,
                skill_python_script,
                input_examples,
                output_examples,
                ai_model or None,
                user_id,
            ),
        )
        conn.commit()
        # 新規作成されたレコードのIDを抽出して返却
        # Extract and return the ID of the inserted prompt record.
        return _extract_id(cursor.fetchone())
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# プロンプトタイプに応じたタスク用テンプレートテキストを構築する関数
# Construct a task prompt template string according to prompt types (special handling for skill type).
def _compose_task_prompt_template(prompt: dict[str, Any]) -> str:
    """
    プロンプトのタイプ（通常テキストか、スキル開発用か）に応じて、タスク登録用のテンプレート文字列を組み立てる。
    Generate a template string based on whether the prompt is standard text or a code/skill integration.
    """
    prompt_type = _normalize_prompt_type(prompt.get("prompt_type"))
    # 通常プロンプトまたは画像生成の場合はコンテンツをそのまま返す
    # Return content as is if not a skill prompt.
    if prompt_type != PROMPT_TYPE_SKILL:
        return prompt.get("content") or ""

    # スキルプロンプトの場合はマークダウン解説とPythonスクリプトを連結
    # If it's a skill, combine markdown text and Python scripts.
    parts = []
    skill_markdown = prompt.get("skill_markdown") or ""
    skill_python_script = prompt.get("skill_python_script") or ""
    if skill_markdown:
        parts.append(skill_markdown)
    if skill_python_script:
        parts.append("```python\n" + skill_python_script + "\n```")
    return "\n\n".join(parts) or (prompt.get("content") or "")


# 公開プロンプトをユーザー自身の個人用タスクテンプレートとして追加・複製保存する関数
# Duplicate a public shared prompt as a user's private task template.
def _add_prompt_as_task_for_user(
    user_id: int,
    prompt_id: int,
) -> tuple[dict[str, Any], int]:
    """
    公開中のプロンプトの複製を取得し、指定ユーザー自身のタスクテンプレート(task_with_examples)として新規登録・インポートする。
    Copy attributes from a public prompt and register it as a user's private task template.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # 対象公開プロンプト情報のロード
        # Load prompt columns.
        cursor.execute(
            """
            SELECT title,
                   content,
                   input_examples,
                   output_examples,
                   prompt_type,
                   skill_markdown,
                   skill_python_script
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        title = prompt.get("title") or ""
        # テンプレート文字列の構築
        # Build the final prompt template.
        prompt_template = _compose_task_prompt_template(dict(prompt))
        if not prompt_template:
            return {"error": "タスクとして追加できる本文がありません。"}, 400

        # すでに同一タイトルかつ削除されていないタスクが登録済みかチェック
        # Check if the task template has already been added under this title.
        cursor.execute(
            """
            SELECT id
              FROM task_with_examples
             WHERE user_id = %s
               AND name = %s
               AND deleted_at IS NULL
            """,
            (user_id, title),
        )
        existing = cursor.fetchone()
        if existing:
            return {"message": "すでにタスクとして追加されています。", "saved_id": existing["id"]}, 200

        # タスクテンプレートテーブルへレコード挿入
        # Perform SQL insert into task_with_examples.
        cursor.execute(
            """
            INSERT INTO task_with_examples
                (user_id, name, prompt_template, input_examples, output_examples)
            VALUES (%s,      %s,   %s,               %s,             %s)
            RETURNING id
            """,
            (
                user_id,
                title,
                prompt_template,
                prompt.get("input_examples") or "",
                prompt.get("output_examples") or "",
            ),
        )
        conn.commit()
        saved_id = _extract_id(cursor.fetchone())
        return {"message": "タスクとして追加しました。", "saved_id": saved_id}, 201
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# プロンプトに対してユーザーから「いいね」を登録する関数
# Add a "like" to a public prompt for a user.
def _add_prompt_like_for_user(
    user_id: int,
    prompt_id: int,
) -> tuple[dict[str, Any], int]:
    """
    指定されたプロンプトが公開かつ未削除であることを検証し、いいねテーブルにレコードを挿入する。
    Create a new row in prompt_likes for the active user if the target prompt is valid.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # プロンプトの存在と公開状態を確認
        # Verify prompt exists and is public.
        cursor.execute(
            """
            SELECT id
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        # ユニーク制約エラー防止のためのON CONFLICT句を用いてインサート
        # Insert the like record, avoiding constraint collisions.
        cursor.execute(
            """
            INSERT INTO prompt_likes (user_id, prompt_id)
            VALUES (%s, %s)
            ON CONFLICT (user_id, prompt_id) DO NOTHING
            RETURNING id
            """,
            (user_id, prompt_id),
        )
        inserted = cursor.fetchone()
        conn.commit()
        if inserted:
            return {"message": "いいねしました。", "liked": True}, 201
        return {"message": "すでにいいねしています。", "liked": True}, 200
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# プロンプトからユーザーの「いいね」を解除する関数
# Remove a "like" from a public prompt for a user.
def _remove_prompt_like_for_user(user_id: int, prompt_id: int) -> int:
    """
    ユーザーIDとプロンプトIDの一致するいいねレコードをDBから物理削除する。
    Delete a like record matching user ID and prompt ID from database.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM prompt_likes
            WHERE user_id = %s
              AND prompt_id = %s
            """,
            (user_id, prompt_id),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 有効な（論理削除や通報非表示されていない）プロンプトコメント件数をカウントする関数
# Count non-deleted and non-hidden comments for a specific prompt.
def _count_visible_prompt_comments(cursor: Any, prompt_id: int) -> int:
    """
    論理削除および通報による非表示状態になっていない、アクティブなコメント件数をカウントする。
    Retrieve count of active, visible comments for a specific prompt ID.
    """
    cursor.execute(
        """
        SELECT COUNT(*) AS total
        FROM prompt_comments
        WHERE prompt_id = %s
          AND deleted_at IS NULL
          AND hidden_by_reports_at IS NULL
        """,
        (prompt_id,),
    )
    row = cursor.fetchone() or {}
    if isinstance(row, dict):
        return int(row.get("total") or 0)
    return int(row[0] or 0)


# プロンプトに関連付けられたコメント一覧を取得する関数
# Retrieve all visible comments for a specific prompt.
def _fetch_prompt_comments(
    prompt_id: int,
    actor_user_id: int | None,
    actor_is_admin: bool,
) -> tuple[dict[str, Any], int]:
    """
    特定のプロンプトに紐づく有効なコメント一覧を、投稿者名、プロンプト所有者IDなどを含めてDBからロードする。
    Fetch list of visible comments for prompt_id and format them with permissions.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # 公開対象プロンプトであることを確認
        # Confirm prompt exists and is public.
        cursor.execute(
            """
            SELECT id
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        # コメント一覧とそれに関連するユーザー/プロンプト所有者情報をロード
        # Fetch active comments associated with the target prompt.
        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id,
                COALESCE(u.username, 'ユーザー') AS author_name,
                pc.content,
                pc.created_at,
                p.user_id AS prompt_owner_id,
                %s AS actor_is_admin
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            JOIN users AS u
              ON u.id = pc.user_id
            WHERE pc.prompt_id = %s
              AND pc.deleted_at IS NULL
              AND pc.hidden_by_reports_at IS NULL
            ORDER BY pc.created_at ASC, pc.id ASC
            LIMIT %s
            """,
            (actor_is_admin, prompt_id, PROMPT_COMMENT_LIST_LIMIT),
        )
        # 各コメントレコードに対し削除権限などの付加・整形を実行
        # Build comment payloads list.
        comments = [
            _serialize_prompt_comment_row(dict(row), actor_user_id)
            for row in cursor.fetchall()
        ]
        # 総コメント数の再取得
        # Retrieve total comments count.
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        return {"comments": comments, "comment_count": comment_count}, 200
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 新規コメントを登録する関数。同一内容の連投重複チェックも行う。
# Insert a new comment for a prompt. Prevents duplicate submissions in a short window.
def _add_prompt_comment_for_user(
    user_id: int,
    prompt_id: int,
    content: str,
    actor_is_admin: bool,
) -> tuple[dict[str, Any], int]:
    """
    対象プロンプトの存在と公開状態を検証し、同一内容の重複コメント送信(連投)を防ぎつつ、新規コメントをDBへ登録する。
    Verify public status, check duplicate window, and insert comment row into prompt_comments.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # 対象公開プロンプト存在チェック
        # Check target prompt.
        cursor.execute(
            """
            SELECT id, user_id
            FROM prompts
            WHERE id = %s
              AND is_public = TRUE
              AND deleted_at IS NULL
            LIMIT 1
            """,
            (prompt_id,),
        )
        prompt = cursor.fetchone()
        if not prompt:
            return {"error": "対象の公開プロンプトが見つかりませんでした。"}, 404

        # 重複・連投コメントチェック(同一ユーザー、同一コンテンツ、同一プロンプト、直近数秒間)
        # Prevent identical comments in the defined window.
        cursor.execute(
            """
            SELECT id
            FROM prompt_comments
            WHERE user_id = %s
              AND prompt_id = %s
              AND content = %s
              AND deleted_at IS NULL
              AND created_at >= (
                    CURRENT_TIMESTAMP - (%s * INTERVAL '1 second')
              )
            LIMIT 1
            """,
            (user_id, prompt_id, content, PROMPT_COMMENT_DUPLICATE_WINDOW_SECONDS),
        )
        duplicated = cursor.fetchone()
        if duplicated:
            return {"error": "同じ内容のコメントは時間をおいて投稿してください。"}, 409

        # コメント行をインサート
        # Insert the comment.
        cursor.execute(
            """
            INSERT INTO prompt_comments (prompt_id, user_id, content)
            VALUES (%s, %s, %s)
            RETURNING id, prompt_id, user_id, content, created_at
            """,
            (prompt_id, user_id, content),
        )
        inserted = dict(cursor.fetchone() or {})
        
        # 投稿したユーザー名を取得
        # Fetch the posting username.
        cursor.execute(
            """
            SELECT COALESCE(username, 'ユーザー') AS username
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )
        user_row = cursor.fetchone() or {}
        inserted["author_name"] = user_row.get("username") or "ユーザー"
        inserted["prompt_owner_id"] = prompt.get("user_id")
        inserted["actor_is_admin"] = actor_is_admin
        comment = _serialize_prompt_comment_row(inserted, user_id)
        
        # 最新のコメント総数をカウント
        # Count current visible comments count.
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": "コメントを投稿しました。",
                "comment": comment,
                "comment_count": comment_count,
            },
            201,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 自身のコメント、あるいはプロンプト投稿者/管理者権限によってコメントを論理削除する関数
# Soft delete a comment if authorized (author of comment, owner of prompt, or admin).
def _delete_prompt_comment_for_actor(
    actor_user_id: int,
    comment_id: int,
    actor_is_admin: bool,
) -> tuple[dict[str, Any], int]:
    """
    指定されたコメントIDが未削除であることを確認し、権限を検証（管理者、投稿者、プロンプト所有者）した上で論理削除する。
    Check deletion authority and soft delete the specified comment.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # コメントレコードと関連プロンプトの作成者IDを取得
        # Fetch comment and prompt owner details.
        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id,
                p.user_id AS prompt_owner_id
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            WHERE pc.id = %s
              AND pc.deleted_at IS NULL
            LIMIT 1
            """,
            (comment_id,),
        )
        comment = cursor.fetchone()
        if not comment:
            return {"error": "対象コメントが見つかりませんでした。"}, 404

        # 権限チェック
        # Check permissions.
        can_delete = actor_is_admin or actor_user_id in {
            comment.get("user_id"),
            comment.get("prompt_owner_id"),
        }
        if not can_delete:
            return {"error": "このコメントを削除する権限がありません。"}, 403

        # コメント削除(論理削除)を実行
        # Update comment deleted_at column.
        cursor.execute(
            """
            UPDATE prompt_comments
            SET deleted_at = CURRENT_TIMESTAMP
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (comment_id,),
        )
        prompt_id = int(comment.get("prompt_id"))
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": "コメントを削除しました。",
                "prompt_id": prompt_id,
                "comment_count": comment_count,
            },
            200,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# コメントを通報・報告し、報告数が閾値に達した場合は自動的に非表示にする関数
# Report a comment and automatically hide it if the report count reaches the threshold.
def _report_prompt_comment_for_user(
    reporter_user_id: int,
    comment_id: int,
    reason: str,
    details: str,
) -> tuple[dict[str, Any], int]:
    """
    ユーザーから対象コメントへの通報（理由、詳細）をDBに登録し、通報数が閾値以上であれば自動で非表示に切り替える。
    Insert a new report record. Check if the report threshold is crossed; if so, soft hide the comment.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # コメントレコードが有効(未削除、未非表示)かチェック
        # Verify comment is active.
        cursor.execute(
            """
            SELECT
                pc.id,
                pc.prompt_id,
                pc.user_id
            FROM prompt_comments AS pc
            JOIN prompts AS p
              ON p.id = pc.prompt_id
             AND p.deleted_at IS NULL
            WHERE pc.id = %s
              AND pc.deleted_at IS NULL
              AND pc.hidden_by_reports_at IS NULL
            LIMIT 1
            """,
            (comment_id,),
        )
        comment = cursor.fetchone()
        if not comment:
            return {"error": "対象コメントが見つかりませんでした。"}, 404
        # 自分自身のコメントは通報不可とする
        # Prevent self-reporting.
        if int(comment.get("user_id") or 0) == reporter_user_id:
            return {"error": "自分のコメントは報告できません。"}, 400

        # 通報データを挿入(同一ユーザーによる同一コメントへの重複通報は無効)
        # Insert comment report record.
        cursor.execute(
            """
            INSERT INTO prompt_comment_reports (
                comment_id,
                reporter_user_id,
                reason,
                details
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (comment_id, reporter_user_id) DO NOTHING
            RETURNING id
            """,
            (comment_id, reporter_user_id, reason, details or None),
        )
        inserted = cursor.fetchone()
        prompt_id = int(comment.get("prompt_id"))
        if not inserted:
            comment_count = _count_visible_prompt_comments(cursor, prompt_id)
            conn.commit()
            return (
                {
                    "message": "このコメントはすでに報告済みです。",
                    "already_reported": True,
                    "hidden": False,
                    "prompt_id": prompt_id,
                    "comment_count": comment_count,
                },
                200,
            )

        # 該当コメントの累積通報件数をカウント
        # Count total reports on this comment.
        cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM prompt_comment_reports
            WHERE comment_id = %s
            """,
            (comment_id,),
        )
        report_row = cursor.fetchone() or {}
        report_count = int(report_row.get("total") or 0)
        hidden = False
        
        # 閾値（3件など）以上の場合、hidden_by_reports_at をセットして非表示化
        # Auto-hide comment if threshold is reached.
        if report_count >= PROMPT_COMMENT_AUTO_HIDE_REPORT_THRESHOLD:
            cursor.execute(
                """
                UPDATE prompt_comments
                SET hidden_by_reports_at = CURRENT_TIMESTAMP,
                    hidden_reason = 'reported'
                WHERE id = %s
                  AND hidden_by_reports_at IS NULL
                """,
                (comment_id,),
            )
            hidden = cursor.rowcount > 0

        # 最新コメント総数のカウント
        # Recalculate visible comments.
        comment_count = _count_visible_prompt_comments(cursor, prompt_id)
        conn.commit()
        return (
            {
                "message": (
                    "コメントを報告しました。一定数の通報により非表示になりました。"
                    if hidden
                    else "コメントを報告しました。"
                ),
                "prompt_id": prompt_id,
                "comment_count": comment_count,
                "hidden": hidden,
                "already_reported": False,
            },
            201,
        )
    except Exception:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# 保存されている全プロンプトを取得するエンドポイント
# Endpoint to retrieve all public prompts.
@prompt_share_api_bp.get("/prompts", name="prompt_share_api.get_prompts")
async def get_prompts(request: Request):
    """
    保存されているすべての公開プロンプト一覧を取得して返却するエンドポイント。
    GET API endpoint to retrieve all shared public prompts with interaction flags.
    """
    session = getattr(request, "session", {}) or {}
    user_id = session.get("user_id")
    try:
        # 非ブロッキングスレッドプールでDB検索処理を実行
        # Run database operation in a separate thread.
        prompts = await run_blocking(_get_prompts_with_flags, user_id)
        return jsonify({"status": "success", "prompts": prompts})
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load shared prompts.",
        )


# プロンプト詳細を取得するエンドポイント
# Endpoint to retrieve details of a specific public prompt.
@prompt_share_api_bp.get("/prompts/{prompt_id}", name="prompt_share_api.get_prompt_detail")
async def get_prompt_detail(prompt_id: int):
    """
    特定のプロンプト詳細情報を取得して返却するエンドポイント。
    GET API endpoint to retrieve details of a specific public prompt by prompt_id.
    """
    try:
        # 非ブロッキングスレッドプールでDB検索処理を実行
        # Run database query in a separate thread.
        prompt = await run_blocking(_get_public_prompt_by_id, prompt_id)
        if not prompt:
            return jsonify({"error": "プロンプトが見つかりません"}, status_code=404)
        return jsonify({"status": "success", "prompt": prompt})
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load public prompt detail.",
        )


# プロンプトのコメント一覧を取得するエンドポイント
# Endpoint to retrieve list of comments for a specific prompt.
@prompt_share_api_bp.get(
    "/prompts/{prompt_id}/comments",
    name="prompt_share_api.get_prompt_comments",
)
async def get_prompt_comments(prompt_id: int, request: Request):
    """
    指定されたプロンプトに対するコメントの一覧を時系列順で取得するエンドポイント。
    GET API endpoint to fetch list of active comments on a public prompt.
    """
    session = getattr(request, "session", {}) or {}
    actor_user_id = session.get("user_id")
    actor_is_admin = bool(session.get("is_admin"))
    try:
        # 非ブロッキングスレッドプールでDB検索処理を実行
        # Run database retrieval in a separate thread.
        response_payload, status_code = await run_blocking(
            _fetch_prompt_comments,
            prompt_id,
            actor_user_id,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to load prompt comments.",
        )


# コメントを作成・投稿するエンドポイント
# Endpoint to submit/create a new comment for a public prompt.
@prompt_share_api_bp.post(
    "/prompts/{prompt_id}/comments",
    name="prompt_share_api.create_prompt_comment",
)
async def create_prompt_comment(prompt_id: int, request: Request):
    """
    ログイン中のユーザーが指定されたプロンプトに対して新規コメントを書き込むエンドポイント。
    POST API endpoint to post a new comment on a public prompt.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = int(request.session["user_id"])
    actor_is_admin = bool(request.session.get("is_admin"))

    # レートリミット、連投クールダウン制限の検証
    # Consume rate limit tokens.
    allowed, limit_message, retry_after = await run_blocking(
        _consume_prompt_comment_create_limits,
        request,
        user_id,
    )
    if not allowed:
        return jsonify_rate_limited(
            limit_message or "コメント投稿の試行回数が多すぎます。時間をおいて再試行してください。",
            retry_after=retry_after,
        )

    # リクエストデータがJSON辞書形式か検証
    # Validate payload formatting.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # 送信パラメーターをPromptCommentCreateRequestモデルでバリデーション
    # Check payload against request schema model.
    request_payload, validation_error = validate_payload_model(
        data,
        PromptCommentCreateRequest,
        error_message="コメント内容を入力してください。",
    )
    if validation_error is not None:
        return validation_error
        
    # スパム防止のためURLの最大埋め込みリンク数超過をチェック
    # Block comments containing too many links.
    if _contains_too_many_links(request_payload.content):
        return jsonify({"error": "URLを含むコメントは3件までにしてください。"}, status_code=400)

    try:
        # 非ブロッキングスレッドプールで新規コメントDB登録を実行
        # Perform database insertion in a separate thread.
        response_payload, status_code = await run_blocking(
            _add_prompt_comment_for_user,
            user_id,
            prompt_id,
            request_payload.content,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to create prompt comment.",
        )


# コメントを削除するエンドポイント
# Endpoint to delete a specific comment.
@prompt_share_api_bp.delete(
    "/comments/{comment_id}",
    name="prompt_share_api.delete_prompt_comment",
)
async def delete_prompt_comment(comment_id: int, request: Request):
    """
    ログイン中のユーザー自身、あるいは権限のあるユーザーがコメントを削除するエンドポイント。
    DELETE API endpoint to remove a comment by comment_id.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    actor_user_id = int(request.session["user_id"])
    actor_is_admin = bool(request.session.get("is_admin"))
    try:
        # 非ブロッキングスレッドプールでコメント削除を実行
        # Run DB soft deletion in a separate thread.
        response_payload, status_code = await run_blocking(
            _delete_prompt_comment_for_actor,
            actor_user_id,
            comment_id,
            actor_is_admin,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to delete prompt comment.",
        )


# コメントを通報するエンドポイント
# Endpoint to report a specific comment.
@prompt_share_api_bp.post(
    "/comments/{comment_id}/report",
    name="prompt_share_api.report_prompt_comment",
)
async def report_prompt_comment(comment_id: int, request: Request):
    """
    ログイン中のユーザーが指定された不適切なコメントを通報・報告するエンドポイント。
    POST API endpoint to report a comment by comment_id.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)

    # リクエストデータがJSON辞書形式か検証
    # Retrieve and validate JSON payload.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # 送信パラメータを通報用リクエストモデルで検証
    # Validate payload properties.
    request_payload, validation_error = validate_payload_model(
        data,
        PromptCommentReportRequest,
        error_message="報告理由を指定してください。",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 非ブロッキングスレッドプールで通報処理を実行
        # Run DB report operation in a separate thread.
        response_payload, status_code = await run_blocking(
            _report_prompt_comment_for_user,
            int(request.session["user_id"]),
            comment_id,
            request_payload.reason,
            request_payload.details,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to report prompt comment.",
        )


# 新しいプロンプトを投稿・共有するエンドポイント
# Endpoint to publish and share a new prompt.
@prompt_share_api_bp.post("/prompts", name="prompt_share_api.create_prompt")
async def create_prompt(request: Request):
    """
    新しいプロンプトを投稿・公開共有するエンドポイント（JSONおよびマルチパートフォームに対応）。
    POST API endpoint to publish and share a new prompt with optional reference image upload.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    # コンテンツタイプに応じてフォームデータ、またはJSONを取得
    # Determine the payload source based on request headers.
    content_type = request.headers.get("content-type", "")
    image_file = None
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        image_candidate = form.get("reference_image")
        image_file = image_candidate if getattr(image_candidate, "filename", "") else None
        data = {
            "title": form.get("title", ""),
            "category": form.get("category", ""),
            "content": form.get("content", ""),
            "prompt_type": form.get("prompt_type", PROMPT_TYPE_TEXT),
            "input_examples": form.get("input_examples", ""),
            "output_examples": form.get("output_examples", ""),
            "ai_model": form.get("ai_model", ""),
            "skill_markdown": form.get("skill_markdown", ""),
            "skill_python_script": form.get("skill_python_script", ""),
        }
    else:
        data, error_response = await require_json_dict(request)
        if error_response is not None:
            return error_response

    # リクエストデータモデルによるバリデーション
    # Validate payload properties.
    payload, validation_error = validate_payload_model(
        data,
        SharedPromptCreateRequest,
        error_message="必要なフィールドが不足しています。",
    )
    if validation_error is not None:
        return validation_error

    # 画像アップロード機能は画像生成プロンプトのみ許可する制限を確認
    # Confirm prompt type is allowed to have an image.
    normalized_prompt_type = _normalize_prompt_type(payload.prompt_type)
    if normalized_prompt_type != PROMPT_TYPE_IMAGE and image_file is not None:
        return jsonify(
            {"error": "画像は画像生成プロンプトでのみアップロードできます。"},
            status_code=400,
        )

    reference_image_url = None
    skill_markdown = payload.skill_markdown if normalized_prompt_type == PROMPT_TYPE_SKILL else ""
    skill_python_script = payload.skill_python_script if normalized_prompt_type == PROMPT_TYPE_SKILL else ""
    try:
        # 画像ファイルがある場合、ディスクに保存してURLを取得
        # Save upload reference image file to static folder.
        if image_file is not None:
            reference_image_url = await run_blocking(_save_prompt_reference_image, image_file, user_id)
        # プロンプトレコードをDBに新規作成
        # Create new prompt row in DB.
        prompt_id = await run_blocking(
            _create_prompt_for_user,
            user_id,
            payload.title,
            payload.category,
            payload.content,
            normalized_prompt_type,
            payload.input_examples,
            payload.output_examples,
            payload.ai_model,
            reference_image_url,
            skill_markdown,
            skill_python_script,
        )
        return jsonify({"message": "プロンプトが作成されました。", "prompt_id": prompt_id}, status_code=201)
    except ValueError as exc:
        # ファイルバリデーションなどのエラー時は、アップロード済みの画像を削除して差し戻し
        # Clean up any written file on valuation failures.
        if reference_image_url:
            await run_blocking(_delete_prompt_reference_image, reference_image_url)
        return jsonify({"error": str(exc)}, status_code=400)
    except Exception:
        # その他エラー発生時はアップロードした画像を削除し、500内部サーバーエラーを返却
        # Clean up files and return 500 on unexpected exceptions.
        if reference_image_url:
            await run_blocking(_delete_prompt_reference_image, reference_image_url)
        return log_and_internal_server_error(
            logger,
            "Failed to create shared prompt.",
        )


# 公開プロンプトをタスクに追加するエンドポイント
# Endpoint to duplicate a public prompt as a user's task template.
@prompt_share_api_bp.post("/task", name="prompt_share_api.add_prompt_as_task")
async def add_prompt_as_task(request: Request):
    """
    公開プロンプトを複製し、ログイン中のユーザー個人のタスクテンプレートとして追加インポートするエンドポイント。
    POST API endpoint to import a public prompt as a user's personal task template.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    # リクエストデータがJSON辞書形式か検証
    # Validate and retrieve JSON payload.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # リクエストボディモデルによるバリデーション
    # Validate payload properties.
    request_payload, validation_error = validate_payload_model(
        data,
        PromptTaskCreateRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 非ブロッキングスレッドプールでタスク追加処理を実行
        # Run task duplication logic in a separate thread.
        response_payload, status_code = await run_blocking(
            _add_prompt_as_task_for_user,
            user_id,
            request_payload.prompt_id,
        )
        if status_code in {200, 201} and "error" not in response_payload:
            response_payload = {
                **response_payload,
                "message": "チャットで使えるように追加しました。",
            }
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to add prompt as task.",
        )


# プロンプトに「いいね」を追加するエンドポイント
# Endpoint to add a "like" to a public prompt.
@prompt_share_api_bp.post("/like", name="prompt_share_api.add_like")
async def add_like(request: Request):
    """
    ログイン中のユーザーが指定されたプロンプトに対して「いいね」を送信するエンドポイント。
    POST API endpoint to like a public prompt.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    # リクエストデータがJSON辞書形式か検証
    # Validate and retrieve JSON payload.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # リクエストボディモデルによるバリデーション
    # Validate payload properties.
    request_payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 非ブロッキングスレッドプールでいいね追加を実行
        # Run DB like addition in a separate thread.
        response_payload, status_code = await run_blocking(
            _add_prompt_like_for_user,
            user_id,
            request_payload.prompt_id,
        )
        return jsonify(response_payload, status_code=status_code)
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to add prompt like.",
        )


# プロンプトの「いいね」を解除するエンドポイント
# Endpoint to remove a "like" from a public prompt.
@prompt_share_api_bp.delete("/like", name="prompt_share_api.remove_like")
async def remove_like(request: Request):
    """
    ログイン中のユーザーが指定されたプロンプトに対する「いいね」を取り消すエンドポイント。
    DELETE API endpoint to unlike a public prompt.
    """
    # ログイン認証チェック
    # Verify authentication state.
    if "user_id" not in request.session:
        return jsonify({"error": "ログインしていません"}, status_code=401)
    user_id = request.session["user_id"]

    # リクエストデータがJSON辞書形式か検証
    # Validate and retrieve JSON payload.
    data, error_response = await require_json_dict(request)
    if error_response is not None:
        return error_response

    # リクエストボディモデルによるバリデーション
    # Validate payload properties.
    request_payload, validation_error = validate_payload_model(
        data,
        PromptLikeRequest,
        error_message="必要なフィールドが不足しています",
    )
    if validation_error is not None:
        return validation_error

    try:
        # 非ブロッキングスレッドプールでいいね解除を実行
        # Run DB like deletion in a separate thread.
        await run_blocking(_remove_prompt_like_for_user, user_id, request_payload.prompt_id)
        return jsonify({"message": "いいねを解除しました。", "liked": False})
    except Exception:
        # エラー発生時はログに記録し、500内部サーバーエラーを返却
        # Log error and return 500 internal server error.
        return log_and_internal_server_error(
            logger,
            "Failed to remove prompt like.",
        )

