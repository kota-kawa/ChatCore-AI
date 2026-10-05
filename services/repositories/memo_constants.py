from __future__ import annotations

# メモが存在しない際のエラーメッセージ
# Error message when a memo is not found.
MEMO_NOT_FOUND_ERROR = "メモが見つかりません。"

# コレクションが存在しない際のエラーメッセージ
# Error message when a collection is not found.
COLLECTION_NOT_FOUND_ERROR = "コレクションが見つかりません。"

# メモ一覧取得時のデフォルト取得件数
# Default limit/count for fetching memo lists.
DEFAULT_MEMO_LIST_LIMIT = 20

# メモ一覧取得時の最大取得件数制限
# Maximum limit/count allowed for fetching memo lists.
MAX_MEMO_LIST_LIMIT = 100

# メモ概要（抜粋）のデフォルト文字数
# Default character length for memo excerpts/previews.
DEFAULT_EXCERPT_LENGTH = 180

# ゴミ箱に入れたメモを完全に削除するまでの保持日数
# Days a trashed memo is kept before it is permanently deleted.
MEMO_TRASH_RETENTION_DAYS = 30

# 期限切れのゴミ箱を1回の削除文で消す上限件数。残りは同じ周期内の次のバッチか次の周期に回す。
# Cap on trashed memos removed by one delete statement; the rest wait for the next batch or cycle.
MEMO_TRASH_PURGE_BATCH_SIZE = 500

# ゴミ箱のメモだけを対象にする一括操作（それ以外の一括操作はゴミ箱のメモに触れない）
# Bulk actions that target trashed memos only; every other bulk action never touches them.
TRASH_BULK_ACTIONS = frozenset({"restore", "purge"})
