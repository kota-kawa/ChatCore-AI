"""個人コンテキスト保管庫ブループリントで使う定数(一覧の既定件数とエラーメッセージ)。

Constants for the personal context vault blueprint: the default list size and error messages.
"""

from __future__ import annotations

# Web UI 一覧のデフォルト取得件数。
# Default number of facts returned by the web listing endpoint.
DEFAULT_CONTEXT_LIST_LIMIT = 50

CONTEXT_FACT_CREATE_ERROR = "コンテキストを保存できませんでした。"
CONTEXT_FACT_UPDATE_ERROR = "コンテキストを更新できませんでした。"
CONTEXT_FACT_DELETE_ERROR = "コンテキストを削除できませんでした。"

# 一覧の検索語の最大文字数。
# The longest search query the list accepts.
MAX_CONTEXT_SEARCH_QUERY_LENGTH = 200

# 「すべての記憶を削除」が、誤操作を防ぐためにリクエストへ求める確認の値。
# The confirmation value "delete all memories" requires in the request, to prevent accidents.
DELETE_ALL_CONFIRMATION = "delete-all"
