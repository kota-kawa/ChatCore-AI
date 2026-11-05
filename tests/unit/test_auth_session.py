"""ログイン成功時の認証セッション確立(establish_authenticated_session)が、旧セッション ID の無効化、ユーザー情報の設定、
ロケールの扱いを正しく行うことを検証する単体テスト。

Unit tests that establish_authenticated_session retires the old session ID, stores the user data, and handles the locale correctly on login.
"""

import unittest

from services.auth_session import establish_authenticated_session
from services.session_middleware import SESSION_IDS_TO_DELETE_SCOPE_KEY
from tests.helpers.request_helpers import build_request


# 認証セッションの確立時におけるセッションIDのローテーション（旧セッションIDの無効化処理登録）やセッション変数設定をテストするクラス。
# Test class to check session ID rotation and session variable initialization during authenticated session establishment.
class AuthSessionTestCase(unittest.TestCase):
    # 既存のセッションが存在する場合に、セッションIDがローテーション（削除保留リストへの追加・現在のIDの初期化）され、
    # ユーザーIDやメールアドレスがセッションに設定されることを検証します。
    # Verify that an existing session ID is rotated (appended to the pending delete list and reset)
    # and authenticated session attributes are initialized.
    def test_establish_authenticated_session_rotates_existing_session_id(self):
        request = build_request(path="/api/login", session={"pre_auth": "keep"})
        request.scope["session_id"] = "session-before-login"

        establish_authenticated_session(request, user_id="42", email="user@example.com")

        pending_ids = request.scope.get(SESSION_IDS_TO_DELETE_SCOPE_KEY)
        self.assertIsInstance(pending_ids, set)
        self.assertIn("session-before-login", pending_ids)
        self.assertIsNone(request.scope.get("session_id"))
        self.assertEqual(request.session["user_id"], 42)
        self.assertEqual(request.session["user_email"], "user@example.com")
        self.assertEqual(request.session["pre_auth"], "keep")
        self.assertTrue(request.session.get("_permanent"))

    # 既存のセッションIDが存在しない（新規セッション等の）状態で認証セッションを確立した際、
    # 削除保留リストに追加されずに正常にセッションが開始されることを検証します。
    # Verify that establishing a session when no pre-existing session ID exists
    # initializes the session successfully without registering any pending deletions.
    def test_establish_authenticated_session_without_existing_session_id(self):
        request = build_request(path="/api/login", session={})

        establish_authenticated_session(request, user_id=7, email="user2@example.com")

        self.assertIsNone(request.scope.get("session_id"))
        self.assertNotIn(SESSION_IDS_TO_DELETE_SCOPE_KEY, request.scope)
        self.assertEqual(request.session["user_id"], 7)
        self.assertEqual(request.session["user_email"], "user2@example.com")
        self.assertTrue(request.session.get("_permanent"))

    # 日本語: preferred_locale を明示すると、言語タグ("en-US")が基本言語("en")に正規化されてセッションに入り、
    #         読み込み済みフラグが立つことを検証します。
    # English: Verify that an explicit preferred_locale ("en-US") is normalized to its base language ("en")
    #          in the session and marks it as loaded.
    def test_establish_authenticated_session_sets_explicit_locale(self):
        request = build_request(path="/api/login", session={})

        establish_authenticated_session(
            request,
            user_id=7,
            email="user2@example.com",
            preferred_locale="en-US",
        )

        self.assertEqual(request.session["preferred_locale"], "en")
        self.assertTrue(request.session["_preferred_locale_loaded"])


if __name__ == "__main__":
    unittest.main()
