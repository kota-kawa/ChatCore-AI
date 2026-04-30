import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.memo import (
    api_archive_memo,
    api_create_memo,
    api_delete_memo,
    api_memo_detail,
    api_memo_share_detail,
    api_memo_share_refresh,
    api_memo_share_revoke,
    api_recent_memos,
    api_share_memo,
    api_shared_memo,
    api_update_memo,
)
from services.api_errors import ResourceNotFoundError
from tests.helpers.request_helpers import build_request


def make_request(method="GET", path="/memo/api", json_body=None, session=None, query_string=b""):
    return build_request(
        method=method,
        path=path,
        json_body=json_body,
        session=session,
        query_string=query_string,
    )


class MemoApiTestCase(unittest.TestCase):
    def test_recent_memos_returns_summary_payload(self):
        request = make_request(
            path="/memo/api/recent",
            query_string=b"limit=5&q=design&tag=work&date_from=2026-04-01&date_to=2026-04-30",
            session={"user_id": 7},
        )

        with patch(
            "blueprints.memo._fetch_memo_summaries",
            return_value={"total": 1, "memos": [{"id": 1, "title": "サンプル"}]},
        ) as mock_fetch:
            response = asyncio.run(
                api_recent_memos(
                    request,
                    limit=5,
                    q="design",
                    tag="work",
                    date_from="2026-04-01",
                    date_to="2026-04-30",
                )
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["memos"][0]["title"], "サンプル")
        self.assertEqual(mock_fetch.call_args.kwargs["query"], "design")
        self.assertEqual(mock_fetch.call_args.kwargs["tag"], "work")
        self.assertEqual(mock_fetch.call_args.kwargs["date_from"], "2026-04-01")
        self.assertEqual(mock_fetch.call_args.kwargs["date_to"], "2026-04-30")

    def test_recent_memos_requires_login(self):
        request = make_request(path="/memo/api/recent", query_string=b"limit=5")
        response = asyncio.run(api_recent_memos(request, limit=5))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "ログインが必要です")

    def test_create_memo_requires_response(self):
        request = make_request(
            method="POST",
            json_body={"input_content": "x", "ai_response": ""},
            session={"user_id": 7},
        )
        response = asyncio.run(api_create_memo(request))
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    def test_create_memo_requires_login(self):
        request = make_request(
            method="POST",
            json_body={"input_content": "x", "ai_response": "ok"},
        )
        response = asyncio.run(api_create_memo(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "ログインが必要です")

    def test_create_memo_success(self):
        request = make_request(
            method="POST",
            json_body={"input_content": "x", "ai_response": "ok", "title": "", "tags": ""},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._insert_memo", return_value=42):
            response = asyncio.run(api_create_memo(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo_id"], 42)

    def test_memo_detail_returns_payload(self):
        request = make_request(path="/memo/api/10", session={"user_id": 7})
        with patch(
            "blueprints.memo._fetch_memo_detail",
            return_value={"id": 10, "title": "詳細メモ", "ai_response": "response"},
        ):
            response = asyncio.run(api_memo_detail(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo"]["title"], "詳細メモ")

    def test_update_memo_requires_any_field(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/10",
            json_body={},
            session={"user_id": 7},
        )
        response = asyncio.run(api_update_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    def test_update_memo_success(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/10",
            json_body={"title": "更新済みタイトル", "tags": "仕事"},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.memo._update_memo",
            return_value={"id": 10, "title": "更新済みタイトル", "tags": "仕事"},
        ):
            response = asyncio.run(api_update_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo"]["title"], "更新済みタイトル")

    def test_delete_memo_success(self):
        request = make_request(method="DELETE", path="/memo/api/10", session={"user_id": 7})
        with patch("blueprints.memo._delete_memo", return_value=None):
            response = asyncio.run(api_delete_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")

    def test_archive_toggle_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/10/archive",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._set_memo_archive_state", return_value={"id": 10, "is_archived": True}):
            response = asyncio.run(api_archive_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["memo"]["is_archived"], True)

    def test_share_memo_requires_login(self):
        request = make_request(
            method="POST",
            path="/memo/api/share",
            json_body={"memo_id": 5},
        )
        response = asyncio.run(api_share_memo(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "ログインが必要です")

    def test_share_memo_returns_share_url(self):
        request = make_request(
            method="POST",
            path="/memo/api/share",
            json_body={"memo_id": 5, "expires_in_days": 7},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.memo.create_or_get_shared_memo_token",
            return_value={
                "share_token": "memo-share-token",
                "expires_at": None,
                "revoked_at": None,
                "is_expired": False,
                "is_revoked": False,
                "is_active": True,
                "is_reused": False,
            },
        ), patch(
            "blueprints.memo.frontend_url",
            return_value="https://chatcore-ai.com/shared/memo/memo-share-token",
        ):
            response = asyncio.run(api_share_memo(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["share_token"], "memo-share-token")
        self.assertEqual(payload["share_url"], "https://chatcore-ai.com/shared/memo/memo-share-token")

    def test_memo_share_detail_returns_state(self):
        request = make_request(path="/memo/api/5/share", session={"user_id": 7})
        with patch(
            "blueprints.memo.get_memo_share_state",
            return_value={
                "share_token": "memo-share-token",
                "expires_at": None,
                "revoked_at": None,
                "is_expired": False,
                "is_revoked": False,
                "is_active": True,
                "is_reused": True,
            },
        ), patch(
            "blueprints.memo.frontend_url",
            return_value="https://chatcore-ai.com/shared/memo/memo-share-token",
        ):
            response = asyncio.run(api_memo_share_detail(request, memo_id=5))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertTrue(payload["is_active"])
        self.assertIn("/shared/memo/", payload["share_url"])

    def test_memo_share_refresh_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/5/share",
            json_body={"force_refresh": True, "expires_in_days": 30},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.memo.create_or_get_shared_memo_token",
            return_value={
                "share_token": "memo-share-token",
                "expires_at": None,
                "revoked_at": None,
                "is_expired": False,
                "is_revoked": False,
                "is_active": True,
                "is_reused": False,
            },
        ), patch(
            "blueprints.memo.frontend_url",
            return_value="https://chatcore-ai.com/shared/memo/memo-share-token",
        ):
            response = asyncio.run(api_memo_share_refresh(request, memo_id=5))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["share_token"], "memo-share-token")

    def test_memo_share_revoke_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/5/share/revoke",
            session={"user_id": 7},
        )
        with patch(
            "blueprints.memo.revoke_shared_memo_token",
            return_value={
                "share_token": "memo-share-token",
                "expires_at": None,
                "revoked_at": "2026-04-30T12:00:00",
                "is_expired": False,
                "is_revoked": True,
                "is_active": False,
                "is_reused": False,
            },
        ):
            response = asyncio.run(api_memo_share_revoke(request, memo_id=5))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertFalse(payload["is_active"])

    def test_shared_memo_endpoint_returns_payload(self):
        request = make_request(path="/memo/api/shared", query_string=b"token=memo-share-token")

        with patch(
            "blueprints.memo.get_shared_memo_payload",
            return_value=(
                {
                    "memo": {
                        "id": 5,
                        "title": "共有メモ",
                        "created_at": "2024-01-01T09:30:00",
                        "tags": "仕事",
                        "input_content": "input",
                        "ai_response": "response",
                    }
                },
                200,
            ),
        ):
            response = asyncio.run(api_shared_memo(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["memo"]["title"], "共有メモ")
        self.assertEqual(payload["memo"]["ai_response"], "response")

    def test_memo_detail_not_found_returns_404(self):
        request = make_request(path="/memo/api/999", session={"user_id": 7})
        with patch(
            "blueprints.memo._fetch_memo_detail",
            side_effect=ResourceNotFoundError("メモが見つかりません。", status="fail"),
        ):
            response = asyncio.run(api_memo_detail(request, memo_id=999))
        self.assertEqual(response.status_code, 404)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")


if __name__ == "__main__":
    unittest.main()
