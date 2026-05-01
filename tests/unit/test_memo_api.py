import asyncio
import json
import unittest
from unittest.mock import patch

from blueprints.memo import (
    api_archive_memo,
    api_bulk_memo,
    api_create_collection,
    api_create_memo,
    api_delete_collection,
    api_delete_memo,
    api_export_memos,
    api_list_collections,
    api_memo_detail,
    api_memo_share_detail,
    api_memo_share_refresh,
    api_memo_share_revoke,
    api_pin_memo,
    api_recent_memos,
    api_share_memo,
    api_shared_memo,
    api_suggest_memo,
    api_update_collection,
    api_update_memo,
    _bulk_action,
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


async def collect_streaming_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


class FakeBulkCursor:
    def __init__(self, *, owned_ids=None, collection_exists=True, rowcount=0):
        self.owned_ids = list(owned_ids or [])
        self.collection_exists = collection_exists
        self.rowcount = rowcount
        self.executed = []
        self.closed = False
        self._fetchall_result = []
        self._fetchone_result = None

    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if "SELECT id FROM memo_entries" in normalized:
            self._fetchall_result = [(memo_id,) for memo_id in self.owned_ids]
            return
        if normalized == "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s":
            self._fetchone_result = (1,) if self.collection_exists else None
            return

    def fetchall(self):
        return self._fetchall_result

    def fetchone(self):
        return self._fetchone_result

    def close(self):
        self.closed = True


class FakeBulkConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self, *args, **kwargs):
        return self._cursor

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


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

    def test_pin_toggle_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/10/pin",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._set_memo_pin_state", return_value={"id": 10, "is_pinned": True}):
            response = asyncio.run(api_pin_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertTrue(payload["memo"]["is_pinned"])

    def test_suggest_memo_returns_title_and_tags(self):
        request = make_request(
            method="POST",
            path="/memo/api/suggest",
            json_body={"input_content": "input", "ai_response": "response"},
            session={"user_id": 7},
        )
        with patch(
            "blueprints.memo.suggest_title_and_tags",
            return_value={"title": "提案タイトル", "tags": "設計 仕様"},
        ):
            response = asyncio.run(api_suggest_memo(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["title"], "提案タイトル")
        self.assertEqual(payload["tags"], "設計 仕様")

    def test_bulk_memo_passes_action_payload(self):
        request = make_request(
            method="POST",
            path="/memo/api/bulk",
            json_body={"action": "add_tags", "memo_ids": [10, 11], "tags": "重要"},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._bulk_action", return_value={"affected": 2}) as mock_bulk:
            response = asyncio.run(api_bulk_memo(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["affected"], 2)
        self.assertEqual(mock_bulk.call_args.args[:3], (7, "add_tags", [10, 11]))
        self.assertEqual(mock_bulk.call_args.kwargs["tags"], "重要")

    def test_bulk_action_reports_actual_affected_rows(self):
        fake_cursor = FakeBulkCursor(owned_ids=[10, 11], rowcount=2)
        fake_conn = FakeBulkConnection(fake_cursor)
        with patch("blueprints.memo.get_db_connection", return_value=fake_conn):
            result = _bulk_action(7, "archive", [10, 11], tags=None, collection_id=None)
        self.assertEqual(result["affected"], 2)
        self.assertTrue(fake_conn.committed)
        self.assertTrue(fake_cursor.closed)

    def test_bulk_action_returns_zero_when_collection_is_not_owned(self):
        fake_cursor = FakeBulkCursor(owned_ids=[10, 11], collection_exists=False, rowcount=2)
        fake_conn = FakeBulkConnection(fake_cursor)
        with patch("blueprints.memo.get_db_connection", return_value=fake_conn):
            result = _bulk_action(7, "set_collection", [10, 11], tags=None, collection_id=99)
        self.assertEqual(result["affected"], 0)
        self.assertTrue(fake_conn.committed)

    def test_collection_routes_return_payloads(self):
        list_request = make_request(path="/memo/api/collections", session={"user_id": 7})
        with patch("blueprints.memo._fetch_collections", return_value=[{"id": 1, "name": "Work"}]):
            list_response = asyncio.run(api_list_collections(list_request))
        self.assertEqual(list_response.status_code, 200)
        list_payload = json.loads(list_response.body.decode())
        self.assertEqual(list_payload["collections"][0]["name"], "Work")

        create_request = make_request(
            method="POST",
            path="/memo/api/collections",
            json_body={"name": "Ideas", "color": "#3b82f6"},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._insert_collection", return_value={"id": 2, "name": "Ideas"}):
            create_response = asyncio.run(api_create_collection(create_request))
        self.assertEqual(create_response.status_code, 200)
        create_payload = json.loads(create_response.body.decode())
        self.assertEqual(create_payload["collection"]["id"], 2)

    def test_update_collection_success(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/collections/2",
            json_body={"name": "Updated", "color": "#10b981"},
            session={"user_id": 7},
        )
        with patch("blueprints.memo._update_collection", return_value={"id": 2, "name": "Updated"}):
            response = asyncio.run(api_update_collection(request, collection_id=2))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["collection"]["name"], "Updated")

    def test_delete_collection_success(self):
        request = make_request(method="DELETE", path="/memo/api/collections/2", session={"user_id": 7})
        with patch("blueprints.memo._delete_collection", return_value=None):
            response = asyncio.run(api_delete_collection(request, collection_id=2))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")

    def test_export_memos_returns_json_download(self):
        request = make_request(path="/memo/api/export", session={"user_id": 7})
        with patch(
            "blueprints.memo._fetch_memos_for_export",
            return_value=[{"id": 10, "title": "Export", "tags": "仕事", "ai_response": "body"}],
        ):
            response = asyncio.run(api_export_memos(request, format="json", ids="10"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("memos.json", response.headers["content-disposition"])
        body = asyncio.run(collect_streaming_body(response))
        payload = json.loads(body.decode())
        self.assertEqual(payload[0]["title"], "Export")

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
