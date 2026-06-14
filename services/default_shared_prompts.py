import time
from typing import Any

from .db import Error, get_db_connection, is_retryable_db_error, rollback_connection

SAMPLE_PROMPT_OWNER_EMAIL = "sample-prompts@chat-core.local"
SAMPLE_PROMPT_OWNER_NAME = "運営サンプル"

DEFAULT_SHARED_PROMPTS = [
    {
        "title": "会議の議事録を短時間で整理するテンプレート",
        "category": "仕事",
        "content": (
            "以下の会議メモを、決定事項・保留事項・担当者アクションに分けて整理してください。"
            "曖昧な点は「確認事項」として列挙し、最後に次回会議までのToDoを箇条書きでまとめてください。"
        ),
        "input_examples": "メモ: 新機能Aは来月公開予定。UI修正は田中さん担当。API仕様は未確定。",
        "output_examples": (
            "決定事項: 新機能Aは来月公開予定\n"
            "保留事項: API仕様の確定\n"
            "担当者アクション: UI修正(田中さん)\n"
            "確認事項: API仕様の最終レビュー日\n"
            "ToDo: API仕様確定会議を設定"
        ),
    },
    {
        "title": "英語プレゼン練習用フィードバックプロンプト",
        "category": "勉強",
        "content": (
            "以下の英語スピーチ原稿を評価し、文法・語彙・発音しづらい箇所・聞き手への伝わりやすさの観点で"
            "改善案を提案してください。最後に60秒版の短縮原稿も作成してください。"
        ),
        "input_examples": "Today I want to talk about why team communication is important in project.",
        "output_examples": (
            "文法: in project -> in projects\n"
            "語彙: important の代わりに critical を提案\n"
            "60秒版: Team communication is critical for project success..."
        ),
    },
    {
        "title": "旅行プランを予算内で最適化するプロンプト",
        "category": "旅行",
        "content": (
            "希望条件と予算をもとに、移動・宿泊・食事・観光を含む1日ごとの旅行プランを作成してください。"
            "予算超過の可能性がある場合は、代替案を優先度順に提示してください。"
        ),
        "input_examples": "2泊3日で福岡旅行。予算は6万円。グルメ中心で移動は公共交通機関。",
        "output_examples": (
            "1日目: 博多ラーメン巡り + 中洲散策\n"
            "2日目: 太宰府天満宮 + 屋台\n"
            "3日目: 市場で朝食後に帰路\n"
            "代替案: 宿泊をビジネスホテルに変更すると約8,000円節約"
        ),
    },
    {
        "title": "趣味ブログのネタ出しと構成案を作る",
        "category": "趣味",
        "content": (
            "テーマに沿ってブログ記事のネタを5件提案し、それぞれにタイトル案・導入文・見出し構成(3つ)を"
            "作成してください。初心者にも読みやすい語り口でお願いします。"
        ),
        "input_examples": "テーマ: 週末に始めるフィルムカメラ",
        "output_examples": (
            "ネタ1 タイトル: 初心者向けフィルムカメラの選び方\n"
            "導入文: 最初の一台選びで迷わないために...\n"
            "見出し: 1. 必要な機能 2. 予算別おすすめ 3. 購入後の最初の設定"
        ),
    },
]
DB_WRITE_MAX_ATTEMPTS = 3
DB_RETRY_BACKOFF_SECONDS = 0.05


def _extract_id(
    row: dict[str, Any] | tuple[Any, ...] | None, key_name: str = "id"
) -> Any:
    # DB結果が dict/tuple どちらでもIDを取り出せるようにする
    # Extract ID from DB rows regardless of dict or tuple shape.
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key_name)
    return row[0]


def _ensure_sample_owner(cursor: Any) -> int:
    # サンプル投稿者ユーザーを再利用し、未作成なら作成してIDを返す
    # Reuse sample owner user or create it when missing, then return its ID.
    cursor.execute(
        "SELECT id FROM users WHERE email = %s",
        (SAMPLE_PROMPT_OWNER_EMAIL,),
    )
    row = cursor.fetchone()
    owner_id = _extract_id(row)
    if owner_id is not None:
        return owner_id

    cursor.execute(
        """
        INSERT INTO users (email, username, is_verified)
        VALUES (%s, %s, TRUE)
        RETURNING id
        """,
        (SAMPLE_PROMPT_OWNER_EMAIL, SAMPLE_PROMPT_OWNER_NAME),
    )
    row = cursor.fetchone()
    owner_id = _extract_id(row)
    if owner_id is None:
        raise RuntimeError("Failed to create sample prompt owner.")
    cursor.execute(
        """
        INSERT INTO user_auth_providers (
            user_id,
            provider,
            provider_user_id,
            provider_email
        )
        VALUES (%s, 'email', %s, %s)
        ON CONFLICT (user_id, provider) DO UPDATE
           SET provider_user_id = EXCLUDED.provider_user_id,
               provider_email = EXCLUDED.provider_email,
               updated_at = CURRENT_TIMESTAMP
        """,
        (owner_id, SAMPLE_PROMPT_OWNER_EMAIL, SAMPLE_PROMPT_OWNER_EMAIL),
    )
    return owner_id


def ensure_default_shared_prompts() -> int:
    # サンプル投稿者配下に標準公開プロンプトを不足分だけ投入する
    # Seed missing public sample prompts under the sample owner account.
    for attempt in range(1, DB_WRITE_MAX_ATTEMPTS + 1):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            try:
                owner_user_id = _ensure_sample_owner(cursor)
                inserted = 0
                existing_titles: set[str] = set()

                if DEFAULT_SHARED_PROMPTS:
                    titles = [prompt["title"] for prompt in DEFAULT_SHARED_PROMPTS]
                    placeholders = ", ".join(["%s"] * len(titles))
                    cursor.execute(
                        f"""
                        SELECT title
                          FROM prompts
                         WHERE user_id = %s
                           AND deleted_at IS NULL
                           AND title IN ({placeholders})
                        """,
                        (owner_user_id, *titles),
                    )
                    existing_titles = {
                        str(row["title"] if isinstance(row, dict) else row[0])
                        for row in (cursor.fetchall() or [])
                    }

                for prompt in DEFAULT_SHARED_PROMPTS:
                    if prompt["title"] in existing_titles:
                        continue

                    cursor.execute(
                        """
                        INSERT INTO prompts
                            (user_id, is_public, title, category, content, author, input_examples, output_examples, created_at)
                        VALUES (%s, TRUE, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            owner_user_id,
                            prompt["title"],
                            prompt["category"],
                            prompt["content"],
                            SAMPLE_PROMPT_OWNER_NAME,
                            prompt["input_examples"],
                            prompt["output_examples"],
                        ),
                    )
                    existing_titles.add(prompt["title"])
                    inserted += 1

                if inserted > 0:
                    conn.commit()

                return inserted
            except Error as exc:
                rollback_connection(conn)
                if is_retryable_db_error(exc) and attempt < DB_WRITE_MAX_ATTEMPTS:
                    time.sleep(DB_RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise
            except BaseException:
                rollback_connection(conn)
                raise
            finally:
                cursor.close()

    raise RuntimeError("Failed to seed default shared prompts after retry attempts.")
