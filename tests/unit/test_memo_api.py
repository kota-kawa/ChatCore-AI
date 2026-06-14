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
    api_reorder_memo,
    api_share_memo,
    api_shared_memo,
    api_suggest_memo,
    api_update_collection,
    api_update_memo,
    _bulk_action,
)
from services.api_errors import ResourceNotFoundError
from tests.helpers.request_helpers import build_request


# 日本語: make request の生成処理を担当します。
# English: Handle creating for make request.
def make_request(method="GET", path="/memo/api", json_body=None, session=None, query_string=b""):
    return build_request(
        method=method,
        path=path,
        json_body=json_body,
        session=session,
        query_string=query_string,
    )


# 日本語: collect streaming body に関する処理の入口です。
# English: Entry point for logic related to collect streaming body.
async def collect_streaming_body(response):
    chunks = []
    # 日本語: 非同期の対象データを順番に処理します。
    # English: Process each asynchronous target item in order.
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    return b"".join(chunks)


# 日本語: run blocking inline の実行処理を非同期で担当します。
# English: Handle running for run blocking inline asynchronously.
async def run_blocking_inline(func, *args, **kwargs):
    return func(*args, **kwargs)


# 日本語: FakeBulkCursor に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeBulkCursor.
class FakeBulkCursor:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, *, owned_ids=None, collection_exists=True, rowcount=0):
        self.owned_ids = list(owned_ids or [])
        self.collection_exists = collection_exists
        self.rowcount = rowcount
        self.executed = []
        self.closed = False
        self._fetchall_result = []
        self._fetchone_result = None

    # 日本語: execute の実行処理を担当します。
    # English: Handle executing for execute.
    def execute(self, query, params=None):
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if "SELECT id FROM memo_entries" in normalized:
            self._fetchall_result = [(memo_id,) for memo_id in self.owned_ids]
            return
        # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
        # English: Switch the flow according to the current condition.
        if normalized == "SELECT 1 FROM memo_collections WHERE id = %s AND user_id = %s":
            self._fetchone_result = (1,) if self.collection_exists else None
            return

    # 日本語: fetchall に関する処理の入口です。
    # English: Entry point for logic related to fetchall.
    def fetchall(self):
        return self._fetchall_result

    # 日本語: fetchone に関する処理の入口です。
    # English: Entry point for logic related to fetchone.
    def fetchone(self):
        return self._fetchone_result

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: FakeBulkConnection に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to FakeBulkConnection.
class FakeBulkConnection:
    # 日本語: インスタンス生成時に必要な初期状態を設定します。
    # English: Initialize the required instance state when the object is created.
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.closed = False

    # 日本語: cursor に関する処理の入口です。
    # English: Entry point for logic related to cursor.
    def cursor(self, *args, **kwargs):
        return self._cursor

    # 日本語: commit に関する処理の入口です。
    # English: Entry point for logic related to commit.
    def commit(self):
        self.committed = True

    # 日本語: close に関する処理の入口です。
    # English: Entry point for logic related to close.
    def close(self):
        self.closed = True


# 日本語: MemoApiTestCase に関するデータや振る舞いをまとめます。
# English: Group data and behavior related to MemoApiTestCase.
class MemoApiTestCase(unittest.TestCase):
    # 日本語: test recent memos returns summary payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test recent memos returns summary payload.
    def test_recent_memos_returns_summary_payload(self):
        request = make_request(
            path="/memo/api/recent",
            query_string=b"limit=5&q=design&date_from=2026-04-01&date_to=2026-04-30",
            session={"user_id": 7},
        )

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.memo._fetch_memo_summaries",
            return_value={"total": 1, "memos": [{"id": 1, "title": "サンプル"}]},
        ) as mock_fetch:
            response = asyncio.run(
                api_recent_memos(
                    request,
                    limit=5,
                    q="design",
                    date_from="2026-04-01",
                    date_to="2026-04-30",
                )
            )

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["memos"][0]["title"], "サンプル")
        self.assertEqual(mock_fetch.call_args.kwargs["query"], "design")
        self.assertEqual(mock_fetch.call_args.kwargs["date_from"], "2026-04-01")
        self.assertEqual(mock_fetch.call_args.kwargs["date_to"], "2026-04-30")

    # 日本語: test recent memos requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test recent memos requires login.
    def test_recent_memos_requires_login(self):
        request = make_request(path="/memo/api/recent", query_string=b"limit=5")
        response = asyncio.run(api_recent_memos(request, limit=5))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: test create memo requires response のテスト検証を担当します。
    # English: Handle verifying test behavior for test create memo requires response.
    def test_create_memo_requires_response(self):
        request = make_request(
            method="POST",
            json_body={"ai_response": ""},
            session={"user_id": 7},
        )
        response = asyncio.run(api_create_memo(request))
        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")

    # 日本語: test create memo requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test create memo requires login.
    def test_create_memo_requires_login(self):
        request = make_request(
            method="POST",
            json_body={"ai_response": "ok"},
        )
        response = asyncio.run(api_create_memo(request))
        self.assertEqual(response.status_code, 401)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "fail")
        self.assertEqual(payload["error"], "ログインが必要です")

    # 日本語: test create memo success のテスト検証を担当します。
    # English: Handle verifying test behavior for test create memo success.
    def test_create_memo_success(self):
        request = make_request(
            method="POST",
            json_body={
                "ai_response": "ok",
                "title": "",
                "background_color": "#fff8b8",
            },
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.routes.run_blocking", new=run_blocking_inline), patch(
            "blueprints.memo._insert_memo", return_value=42
        ) as mock_insert, patch("blueprints.memo._schedule_embedding"):
            response = asyncio.run(api_create_memo(request))

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo_id"], 42)
        self.assertEqual(mock_insert.call_args.args[:4], (7, "ok", "ok", None))
        self.assertEqual(mock_insert.call_args.args[4], "#fff8b8")

    # 日本語: test memo detail returns payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo detail returns payload.
    def test_memo_detail_returns_payload(self):
        request = make_request(path="/memo/api/10", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.memo._fetch_memo_detail",
            return_value={"id": 10, "title": "詳細メモ", "ai_response": "response"},
        ):
            response = asyncio.run(api_memo_detail(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo"]["title"], "詳細メモ")

    # 日本語: test update memo requires any field のテスト検証を担当します。
    # English: Handle verifying test behavior for test update memo requires any field.
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

    # 日本語: test update memo success のテスト検証を担当します。
    # English: Handle verifying test behavior for test update memo success.
    def test_update_memo_success(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/10",
            json_body={"title": "Updated title"},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.routes.run_blocking", new=run_blocking_inline), patch(
            "blueprints.memo._update_memo",
            return_value={"id": 10, "title": "Updated title"},
        ), patch("blueprints.memo._schedule_embedding"):
            response = asyncio.run(api_update_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo"]["title"], "Updated title")

    # 日本語: test update memo allows response edits のテスト検証を担当します。
    # English: Handle verifying test behavior for test update memo allows response edits.
    def test_update_memo_allows_response_edits(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/10",
            json_body={
                "ai_response": "updated answer",
                "background_color": "#dbeafe",
            },
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.routes.run_blocking", new=run_blocking_inline), patch(
            "blueprints.memo._update_memo",
            return_value={"id": 10, "ai_response": "updated answer"},
        ) as mock_update, patch("blueprints.memo._schedule_embedding"):
            response = asyncio.run(api_update_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["memo"]["ai_response"], "updated answer")
        self.assertEqual(mock_update.call_args.kwargs["ai_response"], "updated answer")
        self.assertEqual(mock_update.call_args.kwargs["background_color"], "#dbeafe")

    # 日本語: test delete memo success のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete memo success.
    def test_delete_memo_success(self):
        request = make_request(method="DELETE", path="/memo/api/10", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._delete_memo", return_value=None):
            response = asyncio.run(api_delete_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")

    # 日本語: test archive toggle success のテスト検証を担当します。
    # English: Handle verifying test behavior for test archive toggle success.
    def test_archive_toggle_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/10/archive",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._set_memo_archive_state", return_value={"id": 10, "is_archived": True}):
            response = asyncio.run(api_archive_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["memo"]["is_archived"], True)

    # 日本語: test pin toggle success のテスト検証を担当します。
    # English: Handle verifying test behavior for test pin toggle success.
    def test_pin_toggle_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/10/pin",
            json_body={"enabled": True},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._set_memo_pin_state", return_value={"id": 10, "is_pinned": True}):
            response = asyncio.run(api_pin_memo(request, memo_id=10))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertTrue(payload["memo"]["is_pinned"])

    # 日本語: test suggest memo returns title のテスト検証を担当します。
    # English: Handle verifying test behavior for test suggest memo returns title.
    def test_suggest_memo_returns_title(self):
        request = make_request(
            method="POST",
            path="/memo/api/suggest",
            json_body={"ai_response": "response"},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.memo.suggest_title",
            return_value={"title": "提案タイトル"},
        ):
            response = asyncio.run(api_suggest_memo(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["title"], "提案タイトル")

    # 日本語: test bulk memo passes action payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test bulk memo passes action payload.
    def test_bulk_memo_passes_action_payload(self):
        request = make_request(
            method="POST",
            path="/memo/api/bulk",
            json_body={"action": "archive", "memo_ids": [10, 11]},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._bulk_action", return_value={"affected": 2}) as mock_bulk:
            response = asyncio.run(api_bulk_memo(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["affected"], 2)
        self.assertEqual(mock_bulk.call_args.args[:3], (7, "archive", [10, 11]))

    # 日本語: test reorder memo passes neighbor payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test reorder memo passes neighbor payload.
    def test_reorder_memo_passes_neighbor_payload(self):
        request = make_request(
            method="POST",
            path="/memo/api/reorder",
            json_body={"memo_id": 12, "before_id": 10, "after_id": 11},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.routes.run_blocking", new=run_blocking_inline), patch(
            "blueprints.memo._reorder_memo",
            return_value={"id": 12, "title": "Moved"},
        ) as mock_reorder:
            response = asyncio.run(api_reorder_memo(request))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["memo"]["title"], "Moved")
        self.assertEqual(mock_reorder.call_args.args[:2], (7, 12))
        self.assertEqual(mock_reorder.call_args.kwargs["before_id"], 10)
        self.assertEqual(mock_reorder.call_args.kwargs["after_id"], 11)

    # 日本語: test bulk action reports actual affected rows のテスト検証を担当します。
    # English: Handle verifying test behavior for test bulk action reports actual affected rows.
    def test_bulk_action_reports_actual_affected_rows(self):
        fake_cursor = FakeBulkCursor(owned_ids=[10, 11], rowcount=2)
        fake_conn = FakeBulkConnection(fake_cursor)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.get_db_connection", return_value=fake_conn):
            result = _bulk_action(7, "archive", [10, 11], collection_id=None)
        self.assertEqual(result["affected"], 2)
        self.assertTrue(fake_conn.committed)
        self.assertTrue(fake_cursor.closed)

    # 日本語: test bulk action returns zero when collection is not owned のテスト検証を担当します。
    # English: Handle verifying test behavior for test bulk action returns zero when collection is not owned.
    def test_bulk_action_returns_zero_when_collection_is_not_owned(self):
        fake_cursor = FakeBulkCursor(owned_ids=[10, 11], collection_exists=False, rowcount=2)
        fake_conn = FakeBulkConnection(fake_cursor)
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo.get_db_connection", return_value=fake_conn):
            result = _bulk_action(7, "set_collection", [10, 11], collection_id=99)
        self.assertEqual(result["affected"], 0)
        self.assertTrue(fake_conn.committed)

    # 日本語: test collection routes return payloads のテスト検証を担当します。
    # English: Handle verifying test behavior for test collection routes return payloads.
    def test_collection_routes_return_payloads(self):
        list_request = make_request(path="/memo/api/collections", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._insert_collection", return_value={"id": 2, "name": "Ideas"}):
            create_response = asyncio.run(api_create_collection(create_request))
        self.assertEqual(create_response.status_code, 200)
        create_payload = json.loads(create_response.body.decode())
        self.assertEqual(create_payload["collection"]["id"], 2)

    # 日本語: test update collection success のテスト検証を担当します。
    # English: Handle verifying test behavior for test update collection success.
    def test_update_collection_success(self):
        request = make_request(
            method="PATCH",
            path="/memo/api/collections/2",
            json_body={"name": "Updated", "color": "#10b981"},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._update_collection", return_value={"id": 2, "name": "Updated"}):
            response = asyncio.run(api_update_collection(request, collection_id=2))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["collection"]["name"], "Updated")

    # 日本語: test delete collection success のテスト検証を担当します。
    # English: Handle verifying test behavior for test delete collection success.
    def test_delete_collection_success(self):
        request = make_request(method="DELETE", path="/memo/api/collections/2", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch("blueprints.memo._delete_collection", return_value=None):
            response = asyncio.run(api_delete_collection(request, collection_id=2))
        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.body.decode())
        self.assertEqual(payload["status"], "success")

    # 日本語: test export memos returns json download のテスト検証を担当します。
    # English: Handle verifying test behavior for test export memos returns json download.
    def test_export_memos_returns_json_download(self):
        request = make_request(path="/memo/api/export", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.memo._fetch_memos_for_export",
            return_value=[{"id": 10, "title": "Export", "ai_response": "body"}],
        ):
            response = asyncio.run(api_export_memos(request, format="json", ids="10"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("memos.json", response.headers["content-disposition"])
        body = asyncio.run(collect_streaming_body(response))
        payload = json.loads(body.decode())
        self.assertEqual(payload[0]["title"], "Export")

    # 日本語: test share memo requires login のテスト検証を担当します。
    # English: Handle verifying test behavior for test share memo requires login.
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

    # 日本語: test share memo returns share url のテスト検証を担当します。
    # English: Handle verifying test behavior for test share memo returns share url.
    def test_share_memo_returns_share_url(self):
        request = make_request(
            method="POST",
            path="/memo/api/share",
            json_body={"memo_id": 5, "expires_in_days": 7},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test memo share detail returns state のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo share detail returns state.
    def test_memo_share_detail_returns_state(self):
        request = make_request(path="/memo/api/5/share", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test memo share refresh success のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo share refresh success.
    def test_memo_share_refresh_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/5/share",
            json_body={"force_refresh": True, "expires_in_days": 30},
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test memo share revoke success のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo share revoke success.
    def test_memo_share_revoke_success(self):
        request = make_request(
            method="POST",
            path="/memo/api/5/share/revoke",
            session={"user_id": 7},
        )
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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

    # 日本語: test shared memo endpoint returns payload のテスト検証を担当します。
    # English: Handle verifying test behavior for test shared memo endpoint returns payload.
    def test_shared_memo_endpoint_returns_payload(self):
        request = make_request(path="/memo/api/shared", query_string=b"token=memo-share-token")

        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
        with patch(
            "blueprints.memo.get_shared_memo_payload",
            return_value=(
                {
                    "memo": {
                        "id": 5,
                        "title": "共有メモ",
                        "created_at": "2024-01-01T09:30:00",
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

    # 日本語: test memo detail not found returns 404 のテスト検証を担当します。
    # English: Handle verifying test behavior for test memo detail not found returns 404.
    def test_memo_detail_not_found_returns_404(self):
        request = make_request(path="/memo/api/999", session={"user_id": 7})
        # 日本語: 必要なリソースやコンテキストを限定して利用します。
        # English: Use the required resource or context within this limited block.
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
