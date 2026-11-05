"""表示言語設定の API ルート (GET/PUT /api/user/preferences) のテスト。

Tests for the preferred-locale API routes (GET/PUT /api/user/preferences).
"""

import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.chat.preferences import get_user_preferences, update_user_preferences
from tests.helpers.request_helpers import build_request


# レスポンス本文の JSON をデコードするテスト用ヘルパー。
# Test helper that decodes the JSON body of a response.
def response_json(response):
    return json.loads(response.body.decode("utf-8"))


# ログイン要否、保存済みでない場合の言語解決、DB 保存とセッション・Cookie 更新の順序、入力検証を確かめる。
# Covers the login requirement, locale resolution when nothing is saved, the DB-first ordering of
# session/cookie updates, and input validation.
class UserPreferencesRoutesTestCase(unittest.TestCase):
    def test_get_requires_login(self):
        request = build_request(path="/api/user/preferences")
        response = asyncio.run(get_user_preferences(request))
        self.assertEqual(response.status_code, 401)

    def test_get_returns_resolved_locale_when_not_explicitly_saved(self):
        request = build_request(
            path="/api/user/preferences",
            session={"user_id": 7, "_preferred_locale_loaded": True},
            headers=[(b"accept-language", b"en-US")],
        )
        response = asyncio.run(get_user_preferences(request))
        self.assertEqual(response_json(response), {"locale": "en"})

    # DB への保存が成功した後でだけセッションと Cookie を更新する。
    # The session and cookie are updated only after the DB write succeeds.
    def test_update_persists_db_before_session_and_cookie(self):
        session = {"user_id": 7}
        request = build_request(
            method="PUT",
            path="/api/user/preferences",
            session=session,
            json_body={"locale": "en"},
        )
        with patch(
            "blueprints.chat.preferences.update_user_preferred_locale",
            return_value=True,
        ) as update:
            response = asyncio.run(update_user_preferences(request))

        update.assert_called_once_with(7, "en")
        self.assertEqual(response_json(response), {"locale": "en"})
        self.assertEqual(session["preferred_locale"], "en")
        self.assertTrue(session["_preferred_locale_loaded"])
        self.assertIn("chatcore_locale=en", response.headers["set-cookie"])

    # DB 保存が失敗したら 500 を返し、セッションにも Cookie にも反映しない (表示と保存値のずれを防ぐ)。
    # When the DB write fails, return 500 and leave both session and cookie untouched (avoids a mismatch with the stored value).
    def test_update_db_failure_does_not_change_session_or_cookie(self):
        session = {"user_id": 7}
        request = build_request(
            method="PUT",
            path="/api/user/preferences",
            session=session,
            json_body={"locale": "en"},
        )
        with self.assertLogs("blueprints.chat.preferences", level="ERROR"):
            with patch(
                "blueprints.chat.preferences.update_user_preferred_locale",
                side_effect=RuntimeError("db unavailable"),
            ):
                response = asyncio.run(update_user_preferences(request))

        self.assertEqual(response.status_code, 500)
        self.assertNotIn("preferred_locale", session)
        self.assertNotIn("set-cookie", response.headers)

    def test_update_rejects_unsupported_locale(self):
        request = build_request(
            method="PUT",
            path="/api/user/preferences",
            session={"user_id": 7},
            json_body={"locale": "fr"},
        )
        with patch("blueprints.chat.preferences.update_user_preferred_locale") as update:
            response = asyncio.run(update_user_preferences(request))
        self.assertEqual(response.status_code, 400)
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
