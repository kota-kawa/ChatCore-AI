"""公開プロンプトのコメント API（取得・投稿・削除・通報）を検証するテスト。
ログイン要否、レート制限、リンク数の上限、通報の重複判定を、非同期サービスをモックして確かめる。

Tests for the public-prompt comment APIs (list, create, delete, report):
login requirement, rate limiting, the link-count cap and duplicate-report handling, with the async service mocked.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from blueprints.prompt_share.prompt_share_api import (
    create_prompt_comment,
    delete_prompt_comment,
    get_prompt_comments,
    report_prompt_comment,
)
from tests.helpers.request_helpers import build_request


# テスト用の JSON リクエストを組み立てる補助関数。
# Helper that builds a JSON request for the tests.
def make_request(method, path, payload=None, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


# コメント API の各ルートが入力を検証し、サービスの結果を HTTP 応答へ変換することを検証するテストクラス。
# Test class verifying that each comment route validates input and turns the service result into an HTTP response.
class PromptCommentApiTestCase(unittest.TestCase):
    def test_get_prompt_comments_returns_payload_from_async_service(self):
        request = make_request(
            "GET",
            "/prompt_share/api/prompts/10/comments",
            session={"user_id": 7},
        )
        service = MagicMock()
        service.list_comments = AsyncMock(
            return_value=(
                [
                    {
                        "id": 1,
                        "prompt_id": 10,
                        "user_id": 8,
                        "author_name": "tester",
                        "content": "hello",
                        "created_at": "2024-01-01T00:00:00",
                        "prompt_owner_id": 7,
                    }
                ],
                1,
            )
        )

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(get_prompt_comments(10, request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["comment_count"], 1)
        self.assertEqual(payload["comments"][0]["id"], 1)
        service.list_comments.assert_awaited_once_with(prompt_id=10, limit=200)

    def test_create_prompt_comment_requires_login(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={"content": "test"},
            session={},
        )

        response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["error"], "ログインしていません")

    def test_create_prompt_comment_returns_rate_limited(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={"content": "test"},
            session={"user_id": 2},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._consume_prompt_comment_create_limits",
            return_value=(False, "試行回数が多すぎます。15秒ほど待ってから再試行してください。", 15),
        ), patch("blueprints.prompt_share.prompt_share_api._service") as service_factory:
            response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "15")
        self.assertIn("試行回数", json.loads(response.body.decode("utf-8"))["error"])
        service_factory.assert_not_called()

    def test_create_prompt_comment_rejects_too_many_links(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={
                "content": "https://a.example www.b.example https://c.example https://d.example"
            },
            session={"user_id": 2},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._consume_prompt_comment_create_limits",
            return_value=(True, None, None),
        ), patch("blueprints.prompt_share.prompt_share_api._service") as service_factory:
            response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            json.loads(response.body.decode("utf-8"))["error"],
            "URLを含むコメントは3件までにしてください。",
        )
        service_factory.assert_not_called()

    def test_create_prompt_comment_returns_created_payload(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={"content": "とても参考になりました"},
            session={"user_id": 5},
        )
        service = MagicMock()
        service.add_comment = AsyncMock(
            return_value=(
                {
                    "id": 22,
                    "prompt_id": 10,
                    "user_id": 5,
                    "author_name": "tester",
                    "content": "とても参考になりました",
                    "created_at": "2024-01-01T00:00:00",
                    "prompt_owner_id": 7,
                    "comment_count": 3,
                },
                201,
            )
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._consume_prompt_comment_create_limits",
            return_value=(True, None, None),
        ), patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(create_prompt_comment(10, request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(payload["comment"]["id"], 22)
        self.assertEqual(payload["comment_count"], 3)
        service.add_comment.assert_awaited_once_with(
            user_id=5,
            prompt_id=10,
            content="とても参考になりました",
            actor_is_admin=False,
            duplicate_window_seconds=60,
        )

    def test_delete_prompt_comment_returns_payload(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/comments/88",
            session={"user_id": 4},
        )
        service = MagicMock()
        service.delete_comment = AsyncMock(return_value=({"comment_count": 2, "prompt_id": 10}, 200))

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(delete_prompt_comment(88, request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["comment_count"], 2)
        service.delete_comment.assert_awaited_once_with(
            actor_user_id=4,
            comment_id=88,
            actor_is_admin=False,
        )

    def test_report_prompt_comment_requires_json_object(self):
        request = build_request(
            method="POST",
            path="/prompt_share/api/comments/12/report",
            raw_body=b"[]",
            session={"user_id": 4},
            headers=[(b"content-type", b"application/json")],
        )

        with patch("blueprints.prompt_share.prompt_share_api._service") as service_factory:
            response = asyncio.run(report_prompt_comment(12, request))

        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.body.decode("utf-8"))["error"], "JSON形式が不正です。")
        service_factory.assert_not_called()

    def test_report_prompt_comment_returns_payload(self):
        request = make_request(
            "POST",
            "/prompt_share/api/comments/12/report",
            payload={"reason": "abuse"},
            session={"user_id": 4},
        )
        service = MagicMock()
        service.report_comment = AsyncMock(
            return_value=(
                {
                    "hidden": False,
                    "already_reported": False,
                    "prompt_id": 10,
                    "comment_count": 8,
                },
                201,
            )
        )

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(report_prompt_comment(12, request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 201)
        self.assertFalse(payload["hidden"])
        self.assertEqual(payload["comment_count"], 8)
        service.report_comment.assert_awaited_once_with(
            reporter_user_id=4,
            comment_id=12,
            reason="abuse",
            details="",
            auto_hide_threshold=3,
        )

    def test_report_prompt_comment_returns_already_reported_context(self):
        request = make_request(
            "POST",
            "/prompt_share/api/comments/12/report",
            payload={"reason": "abuse"},
            session={"user_id": 4},
        )
        service = MagicMock()
        service.report_comment = AsyncMock(
            return_value=(
                {
                    "already_reported": True,
                    "hidden": False,
                    "prompt_id": 10,
                    "comment_count": 8,
                },
                200,
            )
        )

        with patch("blueprints.prompt_share.prompt_share_api._service", return_value=service):
            response = asyncio.run(report_prompt_comment(12, request))

        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["already_reported"])
        self.assertEqual(payload["prompt_id"], 10)
        self.assertEqual(payload["comment_count"], 8)


if __name__ == "__main__":
    unittest.main()
