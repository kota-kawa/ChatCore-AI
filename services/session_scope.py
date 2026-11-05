"""セッションミドルウェアと、その上で動く処理が共有する ASGI scope のキーと Redis キー。

Keys of the ASGI scope and of Redis shared by the session middleware and the code built on it.
"""

from __future__ import annotations

# 日本語: 以下の SESSION_* は ASGI scope に保存するキー名。
# English: The SESSION_* names below are keys stored in the ASGI scope.
SESSION_IDS_TO_DELETE_SCOPE_KEY = "_session_ids_to_delete"
SESSION_RESTORE_STATUS_SCOPE_KEY = "_session_restore_status"
SESSION_ORIGINAL_DATA_SCOPE_KEY = "_session_original_data"
SESSION_ORIGINAL_ID_SCOPE_KEY = "_session_original_id"
# 同じブラウザでログイン中だが表示していないアカウントのセッションID（待機セッション）。
# 読み書きの規則は services/account_sessions.py にある。
# Session IDs of accounts that are signed in on this browser but not the active one.
# services/account_sessions.py owns the rules for reading and changing this list.
PARKED_SESSION_IDS_SCOPE_KEY = "_parked_session_ids"
PARKED_SESSION_IDS_ORIGINAL_SCOPE_KEY = "_parked_session_ids_original"
# 日本語: 1 つのブラウザで同時に待機させられるアカウント数の上限。
# English: Maximum number of parked accounts kept for a single browser.
MAX_PARKED_SESSIONS = 4
# 待機中のセッション本体に付ける目印。待機に回る前に始まったリクエストが、
# このセッションを指す Cookie を書き戻して表示中のアカウントを戻してしまうのを防ぐ。
# Marker stored in a parked session's data. It stops a request that started before the
# session was parked from re-issuing a cookie for it and reverting the active account.
PARKED_SESSION_FLAG = "_parked"

# 日本語: Cookie のセッションを Redis から復元した結果の区分（新規／復元済み／見つからない／Redis 利用不可）。
# English: Outcome categories of restoring the cookie's session from Redis (new / restored / missing / Redis unavailable).
SESSION_RESTORE_NEW = "new"
SESSION_RESTORE_RESTORED = "restored"
SESSION_RESTORE_MISSING = "missing"
SESSION_RESTORE_REDIS_UNAVAILABLE = "redis_unavailable"


def session_redis_key(session_id: str) -> str:
    # 日本語: Redisのセッションキーを作成する
    # English: Create a Redis session key
    return f"session:{session_id}"
