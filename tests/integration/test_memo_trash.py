"""PostgreSQL integration coverage for the memo trash: hidden everywhere, restorable, purgeable."""

from __future__ import annotations

import os
import unittest
from uuid import uuid4

from sqlalchemy import text

from services.api_errors import ApiServiceError, ResourceNotFoundError
from services.db import dispose_engine, session_scope
from services.mcp_memo_service import (
    append_memo,
    get_memo,
    list_collections,
    list_memos,
    search_memos,
    update_memo,
)
from services.memo_share import (
    create_or_get_shared_memo_token,
    get_memo_share_state,
    get_shared_memo_payload,
    revoke_shared_memo_token,
)
from services.repositories.embedding_backfill_repository import EmbeddingBackfillRepository
from services.repositories.memo_embedding_repository import MemoEmbeddingRepository
from services.repositories.memo_export_repository import fetch_memos_for_export
from services.repositories.memo_repository import (
    bulk_action,
    delete_memo,
    empty_memo_trash,
    fetch_collections,
    fetch_memo_detail,
    fetch_memo_summaries,
    insert_collection,
    insert_memo,
    purge_expired_memo_trash,
    purge_memo,
    reorder_memo,
    restore_memo,
    set_memo_archive_state,
    set_memo_pin_state,
    update_collection,
)
from services.repositories.memo_repository import (
    update_memo as update_memo_record,
)
from services.request_models import McpMemoAppendRequest, McpMemoUpdateRequest

VECTOR = [1.0] + [0.0] * 767


async def _summaries(user_id, session, **overrides):
    options = {
        "limit": 50,
        "offset": 0,
        "query": "",
        "date_from": "",
        "date_to": "",
        "sort": "recent",
        "include_archived": True,
        "only_archived": False,
        "pinned_first": True,
        "collection_id": None,
        "semantic_query_embedding": None,
        "session": session,
    }
    options.update(overrides)
    return await fetch_memo_summaries(user_id, **options)


@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class MemoTrashIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        suffix = uuid4().hex
        self.marker = f"trashmarker{suffix[:12]}"
        self.user_ids: list[int] = []
        async with session_scope() as session, session.begin():
            for label in ("owner", "other"):
                result = await session.execute(
                    text("INSERT INTO users (email, username) VALUES (:email, :name) RETURNING id"),
                    {"email": f"memo-trash-{label}-{suffix}@example.test", "name": f"ゴミ箱 {label}"},
                )
                self.user_ids.append(int(result.scalar_one()))
        self.owner, self.other = self.user_ids

    async def asyncTearDown(self) -> None:
        async with session_scope() as session, session.begin():
            for user_id in self.user_ids:
                await session.execute(text("DELETE FROM memo_entries WHERE user_id = :id"), {"id": user_id})
                await session.execute(text("DELETE FROM memo_collections WHERE user_id = :id"), {"id": user_id})
                await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
        await dispose_engine()

    async def _memo(self, session, title: str, *, user_id: int | None = None, collection_id=None) -> int:
        memo_id = await insert_memo(
            user_id or self.owner,
            f"{title} {self.marker} body",
            title,
            collection_id,
            session=session,
        )
        assert memo_id is not None
        return int(memo_id)

    async def test_trashed_memo_is_invisible_to_every_other_path(self) -> None:
        async with session_scope() as session, session.begin():
            collection = await insert_collection(self.owner, "未分類", "#112233", session=session)
            trashed = await self._memo(session, "消すメモ", collection_id=collection["id"])
            kept = await self._memo(session, "残すメモ", collection_id=collection["id"])
            neighbor = await self._memo(session, "並べ替え先")
            await MemoEmbeddingRepository(session).store(trashed, VECTOR)
            await MemoEmbeddingRepository(session).store(kept, VECTOR)
            share = await create_or_get_shared_memo_token(trashed, self.owner, session=session)
            token = share["share_token"]
            self.assertEqual((await get_shared_memo_payload(token, session=session))["memo"]["id"], trashed)
            await delete_memo(self.owner, trashed, session=session)

            # 通常一覧・件数・キーワード検索・意味検索・コレクション絞り込み
            for overrides in (
                {},
                {"include_archived": False},
                {"query": self.marker},
                {"query": "消すメモ"},
                {"collection_id": collection["id"]},
            ):
                result = await _summaries(self.owner, session, **overrides)
                self.assertNotIn(trashed, [memo["id"] for memo in result["memos"]], overrides)
                self.assertEqual(result["total"], len(result["memos"]), overrides)
            self.assertEqual((await _summaries(self.owner, session, query=self.marker))["total"], 2)

            # 詳細・更新・アーカイブ・ピン・並べ替え・一括操作
            with self.assertRaises(ResourceNotFoundError):
                await fetch_memo_detail(self.owner, trashed, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await update_memo_record(
                    self.owner, trashed, title="x", ai_response=None, collection_id=None,
                    clear_collection=False, session=session,
                )
            for action in (set_memo_archive_state, set_memo_pin_state):
                with self.assertRaises(ResourceNotFoundError):
                    await action(self.owner, trashed, True, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await reorder_memo(self.owner, trashed, before_id=None, after_id=neighbor, session=session)
            with self.assertRaises(ApiServiceError):
                await reorder_memo(self.owner, neighbor, before_id=trashed, after_id=None, session=session)
            for action in ("archive", "unarchive", "pin", "unpin", "clear_collection", "delete"):
                result = await bulk_action(self.owner, action, [trashed], collection_id=None, session=session)
                self.assertEqual(result, {"affected": 0}, action)
            result = await bulk_action(
                self.owner, "set_collection", [trashed], collection_id=collection["id"], session=session
            )
            self.assertEqual(result, {"affected": 0})

            # コレクションの件数
            self.assertEqual([c["memo_count"] for c in await fetch_collections(self.owner, session=session)], [1])
            renamed = await update_collection(self.owner, collection["id"], "改名", None, session=session)
            self.assertEqual(renamed["memo_count"], 1)

            # 共有: 状態 API・公開ページ
            with self.assertRaises(ResourceNotFoundError):
                await get_memo_share_state(trashed, self.owner, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await create_or_get_shared_memo_token(trashed, self.owner, force_refresh=True, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await revoke_shared_memo_token(trashed, self.owner, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await get_shared_memo_payload(token, session=session)

            # エクスポート
            self.assertEqual(
                [memo["id"] for memo in await fetch_memos_for_export(self.owner, None, session=session)],
                sorted([neighbor, kept], reverse=True),
            )
            self.assertEqual(await fetch_memos_for_export(self.owner, [trashed], session=session), [])

            # MCP・チャットのメモツールが共有するサービス
            listed = await list_memos(self.owner, session=session)
            self.assertNotIn(trashed, [memo.id for memo in listed.memos])
            self.assertEqual(listed.total, 2)
            found = await search_memos(self.owner, self.marker, mode="keyword", session=session)
            self.assertNotIn(trashed, [memo.id for memo in found.memos])
            with self.assertRaises(ResourceNotFoundError):
                await get_memo(self.owner, trashed, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await update_memo(
                    self.owner, trashed, McpMemoUpdateRequest(expected_revision=1, title="x"), session=session
                )
            with self.assertRaises(ResourceNotFoundError):
                await append_memo(
                    self.owner, trashed, McpMemoAppendRequest(expected_revision=1, text="追記"), session=session
                )
            self.assertEqual((await list_collections(self.owner, session=session)).collections[0].memo_count, 1)

            # 埋め込みのバックフィル
            batch = await EmbeddingBackfillRepository(session).fetch_batch(
                "memo_entries", after_id=0, include_existing=True, batch_size=1000
            )
            self.assertNotIn(trashed, [row[0] for row in batch])
            self.assertIn(kept, [row[0] for row in batch])

            # ゴミ箱一覧にだけ現れ、削除日時が付く
            trash = await _summaries(self.owner, session, only_trashed=True)
            self.assertEqual([memo["id"] for memo in trash["memos"]], [trashed])
            self.assertEqual(trash["total"], 1)
            self.assertIsNotNone(trash["memos"][0]["deleted_at"])
            self.assertIsNotNone(trash["memos"][0]["trash_expires_at"])
            self.assertEqual((await _summaries(self.other, session, only_trashed=True))["total"], 0)

    async def test_trashed_pinned_memo_does_not_shift_the_sort_order_of_new_pins(self) -> None:
        async with session_scope() as session, session.begin():
            trashed = await self._memo(session, "ピン済みのゴミ")
            other = await self._memo(session, "新しいピン")
            await set_memo_pin_state(self.owner, trashed, True, session=session)
            await delete_memo(self.owner, trashed, session=session)

            await set_memo_pin_state(self.owner, other, True, session=session)

            sort_order = await session.scalar(
                text("SELECT sort_order FROM memo_entries WHERE id = :id"), {"id": other}
            )
            self.assertEqual(int(sort_order), 1)

    async def test_restore_brings_back_memo_with_its_previous_state(self) -> None:
        async with session_scope() as session, session.begin():
            collection = await insert_collection(self.owner, "戻す先", "#445566", session=session)
            memo_id = await self._memo(session, "戻すメモ", collection_id=collection["id"])
            await set_memo_pin_state(self.owner, memo_id, True, session=session)
            await set_memo_archive_state(self.owner, memo_id, True, session=session)
            token = (await create_or_get_shared_memo_token(memo_id, self.owner, session=session))["share_token"]
            before = await fetch_memo_detail(self.owner, memo_id, session=session)

            await delete_memo(self.owner, memo_id, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await delete_memo(self.owner, memo_id, session=session)

            restored = await restore_memo(self.owner, memo_id, session=session)
            self.assertIsNone(restored["deleted_at"])
            for key in ("is_pinned", "is_archived", "collection_id", "title", "ai_response", "revision"):
                self.assertEqual(restored[key], before[key], key)
            # 共有はゴミ箱へ移した時点で解除され、復元しても自動では再開しない
            # Sharing is revoked on trashing and does not resume on restore.
            self.assertFalse(restored["is_active"])
            self.assertTrue(restored["is_revoked"])
            self.assertFalse((await get_memo_share_state(memo_id, self.owner, session=session))["is_active"])
            with self.assertRaises(ResourceNotFoundError):
                await get_shared_memo_payload(token, session=session)
            # 共有設定から有効にし直すと新しいリンクで公開され、古いリンクは使えないまま
            # Enabling sharing again publishes a new link; the old one stays dead.
            renewed = await create_or_get_shared_memo_token(memo_id, self.owner, session=session)
            self.assertNotEqual(renewed["share_token"], token)
            self.assertEqual(
                (await get_shared_memo_payload(renewed["share_token"], session=session))["memo"]["id"], memo_id
            )
            with self.assertRaises(ResourceNotFoundError):
                await get_shared_memo_payload(token, session=session)
            self.assertEqual((await _summaries(self.owner, session, only_trashed=True))["total"], 0)
            with self.assertRaises(ResourceNotFoundError):
                await restore_memo(self.owner, memo_id, session=session)

    async def test_bulk_trash_revokes_sharing_and_bulk_restore_does_not_resume_it(self) -> None:
        async with session_scope() as session, session.begin():
            shared = await self._memo(session, "共有中")
            unshared = await self._memo(session, "共有なし")
            token = (await create_or_get_shared_memo_token(shared, self.owner, session=session))["share_token"]

            self.assertEqual(
                await bulk_action(self.owner, "delete", [shared, unshared], collection_id=None, session=session),
                {"affected": 2},
            )
            revoked_at = await session.scalar(
                text("SELECT revoked_at FROM shared_memo_entries WHERE memo_entry_id = :id"), {"id": shared}
            )
            self.assertIsNotNone(revoked_at)
            with self.assertRaises(ResourceNotFoundError):
                await get_shared_memo_payload(token, session=session)

            await bulk_action(self.owner, "restore", [shared, unshared], collection_id=None, session=session)

            self.assertFalse((await get_memo_share_state(shared, self.owner, session=session))["is_active"])
            self.assertFalse((await get_memo_share_state(unshared, self.owner, session=session))["is_active"])
            with self.assertRaises(ResourceNotFoundError):
                await get_shared_memo_payload(token, session=session)

    async def test_other_users_cannot_restore_purge_or_empty_each_others_trash(self) -> None:
        async with session_scope() as session, session.begin():
            mine = await self._memo(session, "自分")
            theirs = await self._memo(session, "他人", user_id=self.other)
            await delete_memo(self.owner, mine, session=session)
            await delete_memo(self.other, theirs, session=session)

            with self.assertRaises(ResourceNotFoundError):
                await restore_memo(self.owner, theirs, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await purge_memo(self.owner, theirs, session=session)
            with self.assertRaises(ResourceNotFoundError):
                await delete_memo(self.owner, theirs, session=session)
            self.assertEqual(
                await bulk_action(self.owner, "restore", [theirs], collection_id=None, session=session),
                {"affected": 0},
            )
            self.assertEqual(
                await bulk_action(self.owner, "purge", [theirs], collection_id=None, session=session),
                {"affected": 0},
            )

            self.assertEqual(await empty_memo_trash(self.owner, session=session), 1)
            self.assertEqual((await _summaries(self.owner, session, only_trashed=True))["total"], 0)
            self.assertEqual((await _summaries(self.other, session, only_trashed=True))["total"], 1)

    async def test_purge_deletes_only_trashed_memos_and_their_share_rows(self) -> None:
        async with session_scope() as session, session.begin():
            live = await self._memo(session, "生きている")
            trashed = await self._memo(session, "ゴミ箱")
            await create_or_get_shared_memo_token(trashed, self.owner, session=session)
            await delete_memo(self.owner, trashed, session=session)

            with self.assertRaises(ResourceNotFoundError):
                await purge_memo(self.owner, live, session=session)
            await purge_memo(self.owner, trashed, session=session)

            count = text("SELECT count(*) FROM memo_entries WHERE id = :id")
            shares = text("SELECT count(*) FROM shared_memo_entries WHERE memo_entry_id = :id")
            self.assertEqual(await session.scalar(count, {"id": trashed}), 0)
            self.assertEqual(await session.scalar(shares, {"id": trashed}), 0)
            self.assertEqual(await session.scalar(count, {"id": live}), 1)

    async def test_bulk_actions_move_restore_and_purge_within_their_own_scope(self) -> None:
        async with session_scope() as session, session.begin():
            first = await self._memo(session, "一括1")
            second = await self._memo(session, "一括2")
            third = await self._memo(session, "一括3")

            self.assertEqual(
                await bulk_action(self.owner, "delete", [first, second], collection_id=None, session=session),
                {"affected": 2},
            )
            self.assertEqual((await _summaries(self.owner, session))["total"], 1)
            # restore / purge は生きているメモに効かない
            for action in ("restore", "purge"):
                self.assertEqual(
                    await bulk_action(self.owner, action, [third], collection_id=None, session=session),
                    {"affected": 0},
                )
            self.assertEqual(
                await bulk_action(self.owner, "restore", [first], collection_id=None, session=session),
                {"affected": 1},
            )
            self.assertEqual(
                await bulk_action(self.owner, "purge", [second], collection_id=None, session=session),
                {"affected": 1},
            )
            remaining = await session.scalars(
                text("SELECT id FROM memo_entries WHERE id IN (:a, :b, :c) ORDER BY id").bindparams(
                    a=first, b=second, c=third
                )
            )
            self.assertEqual(list(remaining), [first, third])

    async def test_retention_purge_removes_only_memos_trashed_over_thirty_days_ago(self) -> None:
        async with session_scope() as session, session.begin():
            expired = await self._memo(session, "期限切れ")
            recent = await self._memo(session, "期限内")
            live = await self._memo(session, "通常")
            await delete_memo(self.owner, expired, session=session)
            await delete_memo(self.owner, recent, session=session)
            set_age = text(
                "UPDATE memo_entries SET deleted_at = CURRENT_TIMESTAMP - make_interval(days => :days) WHERE id = :id"
            )
            await session.execute(set_age, {"days": 31, "id": expired})
            await session.execute(set_age, {"days": 29, "id": recent})

            deleted = await purge_expired_memo_trash(session=session)

            self.assertGreaterEqual(deleted, 1)
            remaining = await session.scalars(
                text("SELECT id FROM memo_entries WHERE id IN (:a, :b, :c) ORDER BY id").bindparams(
                    a=expired, b=recent, c=live
                )
            )
            self.assertEqual(list(remaining), [recent, live])


if __name__ == "__main__":
    unittest.main()
