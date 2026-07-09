# services/prompt_categories.py
"""共有プロンプトのカテゴリ軸を定義する単一の真実の源。

[JP] カテゴリは「話題」ではなく「タスク（AIに何をさせるか）」で分類する。
話題の流行に左右されないため、カテゴリ自体の追加・変更をほぼ不要にできる。
DBには安定キー (例: "writing") を保存し、日本語ラベルは表示時に解決する。
これにより将来の改名・多言語化でも過去データが壊れない。
旧カテゴリ（日本語ラベル保存時代の値）はエイリアスで新キーへ正規化する。
カテゴリの追加は、原則このモジュールへ1エントリ足すだけで済む（DBスキーマ変更不要）。

[EN] Single source of truth for the shared-prompt category axis. Categories are
task-oriented (what the prompt makes the AI do), not topic-oriented, so the set
stays stable over time. The DB stores stable keys; Japanese labels are resolved
at render time. Legacy Japanese values are normalized via aliases. Mirror in
frontend/scripts/prompt_share/prompt_category_registry.ts.
"""

from __future__ import annotations

from dataclasses import dataclass

# カテゴリ未設定を表す空値。表示側では「未分類」として扱う。
# Empty value meaning "no category"; rendered as 未分類 by the frontend.
CATEGORY_UNSET = ""

# その他カテゴリのキー。未知の旧値の移行先にも使う。
# Key for the catch-all category; also the migration target for unknown values.
CATEGORY_OTHER = "other"


@dataclass(frozen=True)
class PromptCategory:
    """カテゴリ軸の1エントリ。"""

    key: str
    label: str
    # Bootstrap Icons のクラス名 (フロントのミラーと一致させる)。
    # Bootstrap Icons class name (kept in sync with the frontend mirror).
    icon: str


# --- カテゴリレジストリ -----------------------------------------------------
# 並び順はフィルタUI・投稿フォームの表示順。"other" は必ず末尾に置く。
# Order drives the filter UI and composer form; "other" must stay last.
PROMPT_CATEGORIES: dict[str, PromptCategory] = {
    category.key: category
    for category in (
        PromptCategory(key="writing", label="文章作成", icon="bi-pencil"),
        PromptCategory(key="coding", label="開発・プログラミング", icon="bi-code-slash"),
        PromptCategory(key="business", label="仕事・ビジネス", icon="bi-briefcase"),
        PromptCategory(key="learning", label="学習・教育", icon="bi-book"),
        PromptCategory(key="research", label="調査・分析", icon="bi-graph-up"),
        PromptCategory(key="ideation", label="アイデア・企画", icon="bi-lightbulb"),
        PromptCategory(key="creative", label="創作・ロールプレイ", icon="bi-palette"),
        PromptCategory(key="language", label="翻訳・語学", icon="bi-translate"),
        PromptCategory(key="daily_life", label="暮らし・相談", icon="bi-house-heart"),
        PromptCategory(key="hobby", label="趣味・エンタメ", icon="bi-controller"),
        PromptCategory(key=CATEGORY_OTHER, label="その他", icon="bi-stars"),
    )
}

# 旧カテゴリ（日本語ラベル保存値）から新キーへのエイリアス。
# DBマイグレーション・リクエスト正規化の両方がこの対応表を参照する。
# Aliases mapping legacy Japanese category values to canonical keys.
# Both the DB migration and request normalization consult this table.
LEGACY_CATEGORY_ALIASES: dict[str, str] = {
    "恋愛": "daily_life",
    "旅行": "daily_life",
    "グルメ": "daily_life",
    "勉強": "learning",
    "趣味": "hobby",
    "スポーツ": "hobby",
    "音楽": "hobby",
    "仕事": "business",
    "その他": CATEGORY_OTHER,
    # 投稿フォームの旧初期値。未設定として扱う。
    # Legacy composer sentinel; treated as unset.
    "未選択": CATEGORY_UNSET,
}


def normalize_category(value: object) -> str | None:
    """カテゴリ値を正規化する。

    正準キーはそのまま、旧日本語値はエイリアスで解決、空値は CATEGORY_UNSET。
    未知の値は None を返す（呼び出し側でバリデーションエラーにする）。
    Normalize a category value: canonical keys pass through, legacy Japanese
    values resolve via aliases, empty means unset. Unknown values return None
    so the caller can reject them.
    """
    normalized = str(value or "").strip()
    if not normalized:
        return CATEGORY_UNSET
    lowered = normalized.lower()
    if lowered in PROMPT_CATEGORIES:
        return lowered
    return LEGACY_CATEGORY_ALIASES.get(normalized)


def is_valid_category(value: object) -> bool:
    """カテゴリ値が受理可能（正準キー・エイリアス・空）かを返す。"""
    return normalize_category(value) is not None


def category_label(value: object) -> str:
    """カテゴリキーから表示ラベルを解決する（未設定・未知は空文字列）。"""
    normalized = normalize_category(value)
    if not normalized:
        return ""
    category = PROMPT_CATEGORIES.get(normalized)
    return category.label if category is not None else ""


def category_keys_matching(query: str) -> list[str]:
    """ラベルまたはキーが検索語に部分一致するカテゴリキーの一覧を返す。

    DBにはキーが保存されるため、日本語ラベルでの検索（例:「文章」）を
    カテゴリ一致に変換する用途で使う。
    Return category keys whose label or key contains the query, so that
    Japanese label searches still match keyed categories in SQL.
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return []
    return [
        category.key
        for category in PROMPT_CATEGORIES.values()
        if needle in category.label.lower() or needle in category.key
    ]
