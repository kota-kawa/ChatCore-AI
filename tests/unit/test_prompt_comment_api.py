import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.prompt_share.prompt_share_api import (
    create_prompt_comment,
    delete_prompt_comment,
    get_prompt_comments,
    report_prompt_comment,
)
from tests.helpers.request_helpers import build_request


def make_request(method, path, payload=None, session=None):
    return build_request(
        method=method,
        path=path,
        json_body=payload,
        session=session,
    )


class PromptCommentApiTestCase(unittest.TestCase):
    def test_get_prompt_comments_returns_payload(self):
        request = make_request(
            "GET",
            "/prompt_share/api/prompts/10/comments",
            session={"user_id": 7},
        )
        expected_payload = {"comments": [{"id": 1, "content": "hello"}], "comment_count": 1}

        with patch(
            "blueprints.prompt_share.prompt_share_api._fetch_prompt_comments",
            return_value=(expected_payload, 200),
        ) as mock_fetch:
            response = asyncio.run(get_prompt_comments(10, request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["comment_count"], 1)
        self.assertEqual(payload["comments"][0]["id"], 1)
        mock_fetch.assert_called_once_with(10, 7, False)

    def test_create_prompt_comment_requires_login(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={"content": "test"},
            session={},
        )

        response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "ログインしていません")

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
        ), patch("blueprints.prompt_share.prompt_share_api._add_prompt_comment_for_user") as mock_add:
            response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "15")
        payload = json.loads(response.body.decode("utf-8"))
        self.assertIn("試行回数", payload["error"])
        mock_add.assert_not_called()

    def test_create_prompt_comment_rejects_too_many_links(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={
                "content": (
                    "https://a.example www.b.example https://c.example "
                    "https://d.example"
                )
            },
            session={"user_id": 2},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._consume_prompt_comment_create_limits",
            return_value=(True, None, None),
        ), patch("blueprints.prompt_share.prompt_share_api._add_prompt_comment_for_user") as mock_add:
            response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "URLを含むコメントは3件までにしてください。")
        mock_add.assert_not_called()

    def test_create_prompt_comment_returns_created_payload(self):
        request = make_request(
            "POST",
            "/prompt_share/api/prompts/10/comments",
            payload={"content": "とても参考になりました"},
            session={"user_id": 5},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._consume_prompt_comment_create_limits",
            return_value=(True, None, None),
        ), patch(
            "blueprints.prompt_share.prompt_share_api._add_prompt_comment_for_user",
            return_value=(
                {
                    "message": "コメントを投稿しました。",
                    "comment": {"id": 22, "content": "とても参考になりました"},
                    "comment_count": 3,
                },
                201,
            ),
        ) as mock_add:
            response = asyncio.run(create_prompt_comment(10, request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["comment"]["id"], 22)
        self.assertEqual(payload["comment_count"], 3)
        mock_add.assert_called_once_with(5, 10, "とても参考になりました", False)

    def test_delete_prompt_comment_returns_payload(self):
        request = make_request(
            "DELETE",
            "/prompt_share/api/comments/88",
            session={"user_id": 4},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._delete_prompt_comment_for_actor",
            return_value=({"message": "コメントを削除しました。", "comment_count": 2, "prompt_id": 10}, 200),
        ) as mock_delete:
            response = asyncio.run(delete_prompt_comment(88, request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["comment_count"], 2)
        mock_delete.assert_called_once_with(4, 88, False)

    def test_report_prompt_comment_requires_json_object(self):
        request = build_request(
            method="POST",
            path="/prompt_share/api/comments/12/report",
            raw_body=b"[]",
            session={"user_id": 4},
            headers=[(b"content-type", b"application/json")],
        )

        with patch("blueprints.prompt_share.prompt_share_api._report_prompt_comment_for_user") as mock_report:
            response = asyncio.run(report_prompt_comment(12, request))

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertEqual(payload["error"], "JSON形式が不正です。")
        mock_report.assert_not_called()

    def test_report_prompt_comment_returns_payload(self):
        request = make_request(
            "POST",
            "/prompt_share/api/comments/12/report",
            payload={"reason": "abuse"},
            session={"user_id": 4},
        )

        with patch(
            "blueprints.prompt_share.prompt_share_api._report_prompt_comment_for_user",
            return_value=(
                {
                    "message": "コメントを報告しました。",
                    "hidden": False,
                    "already_reported": False,
                    "prompt_id": 10,
                    "comment_count": 8,
                },
                201,
            ),
        ) as mock_report:
            response = asyncio.run(report_prompt_comment(12, request))

        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.body.decode("utf-8"))
        self.assertFalse(payload["hidden"])
        self.assertEqual(payload["comment_count"], 8)
        mock_report.assert_called_once_with(4, 12, "abuse", "")


if __name__ == "__main__":
    unittest.main()
