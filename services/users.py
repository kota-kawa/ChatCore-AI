from typing import Any

from .db import get_db_connection
from .default_tasks import default_task_rows

DEFAULT_USERNAME = "ユーザー"
DEFAULT_AVATAR_URL = "/static/user-icon.png"
LEGACY_AVATAR_URL_MAX_LENGTH = 255
EMAIL_AUTH_PROVIDER = "email"
GOOGLE_AUTH_PROVIDER = "google"
ACCOUNT_DELETE_CONFIRMATION_TEXT = "DELETE ACCOUNT"


# 認証プロバイダのメタデータを検証・正規化する
# Validate and normalize authentication provider metadata.
# 日本語: normalize provider metadata の正規化処理を担当します。
# English: Handle normalizing for normalize provider metadata.
def _normalize_provider_metadata(
    auth_provider: str,
    email: str,
    provider_user_id: str | None,
    provider_email: str | None,
) -> tuple[str | None, str | None]:
    normalized_provider_user_id = (provider_user_id or "").strip() or None
    normalized_provider_email = (provider_email or "").strip() or None

    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if auth_provider == EMAIL_AUTH_PROVIDER:
        normalized_provider_user_id = normalized_provider_user_id or email
        normalized_provider_email = normalized_provider_email or email

    return normalized_provider_user_id, normalized_provider_email


# アバターURLを検証・正規化し、無効な場合はデフォルトのアバターURLを返す
# Validate and normalize the avatar URL, returning the default if invalid.
# 日本語: normalize avatar url の正規化処理を担当します。
# English: Handle normalizing for normalize avatar url.
def _normalize_avatar_url(avatar_url: str | None) -> str:
    normalized = (avatar_url or "").strip()
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not normalized:
        return DEFAULT_AVATAR_URL
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if len(normalized) > LEGACY_AVATAR_URL_MAX_LENGTH:
        return DEFAULT_AVATAR_URL
    return normalized


# ユーザーの認証プロバイダ情報をテーブルに挿入または更新（アップサート）する
# Insert or update (upsert) the user's authentication provider information in the database.
# 日本語: upsert user auth provider に関する処理の入口です。
# English: Entry point for logic related to upsert user auth provider.
def _upsert_user_auth_provider(
    cursor: Any,
    user_id: int,
    provider: str,
    provider_user_id: str | None,
    provider_email: str | None,
) -> None:
    cursor.execute(
        """
        INSERT INTO user_auth_providers (
            user_id,
            provider,
            provider_user_id,
            provider_email
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id, provider) DO UPDATE
           SET provider_user_id = EXCLUDED.provider_user_id,
               provider_email = EXCLUDED.provider_email,
               updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, provider, provider_user_id, provider_email),
    )


# 共通のデフォルトタスクを新規ユーザーにコピーする
# Copy common default tasks into user-specific tasks.
# 日本語: copy default tasks for user に関する処理の入口です。
# English: Entry point for logic related to copy default tasks for user.
def copy_default_tasks_for_user(user_id: int) -> None:
    # 共有タスクをユーザー専用タスクとして重複なく複製する
    # Copy shared default tasks into user-owned rows without duplicates.
    """user_id IS NULL の共通タスクを指定ユーザーに複製"""
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT name, prompt_template, response_rules,
                       output_skeleton, input_examples,
                       output_examples, display_order
                  FROM task_with_examples
                 WHERE user_id IS NULL
                   AND deleted_at IS NULL
                """,
            )
            defaults = cursor.fetchall()
            if not defaults:
                defaults = default_task_rows()

            for name, tmpl, response_rules, output_skeleton, inp, out, disp in defaults:
                cursor.execute(
                    """
                    SELECT 1 FROM task_with_examples
                     WHERE user_id = %s AND name = %s
                       AND deleted_at IS NULL
                    """,
                    (user_id, name)
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    """
                    INSERT INTO task_with_examples
                          (user_id, name, prompt_template,
                           response_rules, output_skeleton,
                           input_examples, output_examples, display_order)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (user_id, name, tmpl, response_rules, output_skeleton, inp, out, disp)
                )

            conn.commit()
        finally:
            cursor.close()


# 指定されたメールアドレスを持つユーザーを取得する
# Retrieve a user by their email address.
# 日本語: get user by email の取得処理を担当します。
# English: Handle fetching for get user by email.
def get_user_by_email(email: str) -> dict[str, Any] | None:
    # メールアドレス一致のユーザー1件を返す
    # Fetch a single user by email.
    """メールアドレスでユーザーを取得"""
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT u.*,
                       gap.provider AS auth_provider,
                       gap.provider_user_id,
                       gap.provider_email
                  FROM users AS u
                  LEFT JOIN user_auth_providers AS gap
                    ON gap.user_id = u.id
                   AND gap.provider = %s
                 WHERE u.email = %s
                """,
                (GOOGLE_AUTH_PROVIDER, email),
            )
            return cursor.fetchone()
        finally:
            cursor.close()


# GoogleのユーザーID（プロバイダ識別子）に紐付くユーザーを取得する
# Retrieve a user by their Google provider user ID.
# 日本語: get user by google id の取得処理を担当します。
# English: Handle fetching for get user by google id.
def get_user_by_google_id(google_user_id: str) -> dict[str, Any] | None:
    # Google の安定IDでユーザーを取得する
    # Look up a user by Google provider identity.
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT u.*,
                       p.provider AS auth_provider,
                       p.provider_user_id,
                       p.provider_email
                  FROM user_auth_providers AS p
                  JOIN users AS u
                    ON u.id = p.user_id
                 WHERE p.provider = %s
                   AND p.provider_user_id = %s
                """,
                (GOOGLE_AUTH_PROVIDER, google_user_id),
            )
            return cursor.fetchone()
        finally:
            cursor.close()


# ユーザーIDに紐付くユーザー情報を取得する
# Retrieve user information by user ID.
# 日本語: get user by id の取得処理を担当します。
# English: Handle fetching for get user by id.
def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    # プロフィール表示に必要なユーザー情報を取得する
    # Fetch user fields needed by profile and session endpoints.
    """ユーザーIDでユーザーを取得"""
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT id, email, is_verified, created_at,
                       username, bio, avatar_url, llm_profile_context
                  FROM users
                 WHERE id = %s
                """,
                (user_id,)
            )
            return cursor.fetchone()
        finally:
            cursor.close()


# 新しいユーザーレコードを作成し、そのIDを返す
# Create a new user record and return its ID.
# 日本語: create user の作成処理を担当します。
# English: Handle creating for create user.
def create_user(
    email: str,
    username: str | None = None,
    avatar_url: str | None = None,
    *,
    auth_provider: str = EMAIL_AUTH_PROVIDER,
    provider_user_id: str | None = None,
    provider_email: str | None = None,
    is_verified: bool = False,
) -> int | None:
    # 未認証ユーザーを作成し、採番された user_id を返す
    # Create an unverified user and return the generated user_id.
    """未認証ユーザーを新規作成"""
    normalized_username = (username or "").strip()[:255] or DEFAULT_USERNAME
    normalized_avatar_url = _normalize_avatar_url(avatar_url)
    normalized_provider_user_id, normalized_provider_email = _normalize_provider_metadata(
        auth_provider,
        email,
        provider_user_id,
        provider_email,
    )
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    username,
                    avatar_url,
                    is_verified
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    email,
                    normalized_username,
                    normalized_avatar_url,
                    is_verified,
                ),
            )
            row = cursor.fetchone()
            user_id = row[0] if row else None
            if user_id is None:
                conn.rollback()
                return None

            _upsert_user_auth_provider(
                cursor,
                user_id,
                auth_provider,
                normalized_provider_user_id,
                normalized_provider_email,
            )
            conn.commit()
            return user_id
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


# 指定されたユーザーIDにGoogleアカウントの認証情報を紐付ける
# Link a Google account authentication provider to an existing user.
# 日本語: link google account に関する処理の入口です。
# English: Entry point for logic related to link google account.
def link_google_account(user_id: int, google_user_id: str, provider_email: str) -> None:
    # 既存ユーザーへ Google 連携情報を紐付け・更新する
    # Attach or refresh Google provider metadata for an existing user.
    normalized_google_user_id = (google_user_id or "").strip()
    normalized_provider_email = (provider_email or "").strip() or None
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if not normalized_google_user_id:
        raise ValueError("google_user_id is required")

    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            _upsert_user_auth_provider(
                cursor,
                user_id,
                GOOGLE_AUTH_PROVIDER,
                normalized_google_user_id,
                normalized_provider_email,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


# プロフィール項目（ユーザー名やアバター）が未設定の場合、Googleの情報で更新する
# Update user profile fields (username, avatar) with Google details if they are currently default/unset.
# 日本語: update user profile from google if unset の更新処理を担当します。
# English: Handle updating for update user profile from google if unset.
def update_user_profile_from_google_if_unset(
    user_id: int,
    name: str | None = None,
    picture: str | None = None,
) -> None:
    # 既定値のままのプロフィール項目だけ Google 情報で初期化する
    # Seed profile fields from Google only when the user still has defaults.
    normalized_name = (name or "").strip()
    normalized_picture = (picture or "").strip()

    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT username, avatar_url
                  FROM users
                 WHERE id = %s
                """,
                (user_id,),
            )
            current = cursor.fetchone()
            if not current:
                return

            next_username = current.get("username") or DEFAULT_USERNAME
            next_avatar_url = current.get("avatar_url") or DEFAULT_AVATAR_URL

            if normalized_name and next_username.strip() in {"", DEFAULT_USERNAME}:
                next_username = normalized_name
            normalized_avatar_url = _normalize_avatar_url(normalized_picture)
            if normalized_picture and next_avatar_url.strip() in {"", DEFAULT_AVATAR_URL}:
                next_avatar_url = normalized_avatar_url

            cursor.execute(
                """
                UPDATE users
                   SET username = %s,
                       avatar_url = %s
                 WHERE id = %s
                """,
                (next_username, next_avatar_url, user_id),
            )
            conn.commit()
        finally:
            cursor.close()


# ユーザーに関連する全データとアカウント自体をデータベースから削除する
# Delete all data associated with a user and remove their account from the database.
# 日本語: delete user account の削除処理を担当します。
# English: Handle deleting for delete user account.
def delete_user_account(user_id: int) -> bool:
    # Delete user-owned records that are not fully covered by cascading FKs,
    # then remove the user row in the same transaction.
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT id
                  FROM users
                 WHERE id = %s
                 FOR UPDATE
                """,
                (user_id,),
            )
            if not cursor.fetchone():
                conn.rollback()
                return False

            for query in (
                "DELETE FROM prompt_likes WHERE user_id = %s",
                "DELETE FROM prompt_list_entries WHERE user_id = %s",
                "DELETE FROM memo_entries WHERE user_id = %s",
                "DELETE FROM memory_facts WHERE user_id = %s",
                "DELETE FROM user_auth_providers WHERE user_id = %s",
                "DELETE FROM user_passkeys WHERE user_id = %s",
                "DELETE FROM chat_rooms WHERE user_id = %s",
                "DELETE FROM task_with_examples WHERE user_id = %s",
                "DELETE FROM prompts WHERE user_id = %s",
            ):
                cursor.execute(query, (user_id,))

            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


# ユーザーの認証状態（is_verified）をTrue（認証済み）に変更する
# Set the user's verification status (is_verified) to True in the database.
# 日本語: set user verified の設定処理を担当します。
# English: Handle setting for set user verified.
def set_user_verified(user_id: int) -> None:
    # 認証完了後に is_verified フラグを更新する
    # Mark user as verified after successful verification.
    """ユーザーを認証済みに更新"""
    # 日本語: 必要なリソースやコンテキストを限定して利用します。
    # English: Use the required resource or context within this limited block.
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users SET is_verified = TRUE
                WHERE id = %s
                """,
                (user_id,)
            )
            conn.commit()
        finally:
            cursor.close()
