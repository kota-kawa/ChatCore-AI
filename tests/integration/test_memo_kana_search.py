"""メモのキーワード検索が、ひらがなとカタカナを区別せずタイトルと本文の両方に当たることを実 PostgreSQL で検証する。

PostgreSQL integration coverage for hiragana/katakana-insensitive memo keyword search.
"""

from __future__ import annotations

import os
import unittest
from uuid import uuid4

from sqlalchemy import text

from services.db import dispose_engine, session_scope
from services.repositories.memo_repository import fetch_memo_summaries, insert_memo


@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class MemoKanaSearchIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """fetch_memo_summaries のキーワード検索をかな表記ゆれのクエリで確かめる。

    Exercises fetch_memo_summaries keyword search with queries that differ in kana script.
    """

    async def asyncTearDown(self) -> None:
        await dispose_engine()

    # 日本語: キーワード検索だけを指定して一覧を取り、ヒットしたメモのタイトルを並べ替えて返す。
    # English: Run a keyword-only listing and return the sorted titles of the memos that matched.
    async def _search(self, session, user_id: int, query: str) -> list[str]:
        result = await fetch_memo_summaries(
            user_id,
            limit=20,
            offset=0,
            query=query,
            date_from="",
            date_to="",
            sort="recent",
            include_archived=False,
            only_archived=False,
            pinned_first=False,
            collection_id=None,
            semantic_query_embedding=None,
            session=session,
        )
        return sorted(memo["title"] for memo in result["memos"])

    async def test_hiragana_and_katakana_queries_find_each_other_in_title_and_body(self) -> None:
        suffix = uuid4().hex
        async with session_scope() as session, session.begin():
            user_id = int(
                (
                    await session.execute(
                        text("INSERT INTO users (email, username) VALUES (:email, 'かな検索') RETURNING id"),
                        {"email": f"memo-kana-{suffix}@example.test"},
                    )
                ).scalar_one()
            )
            await insert_memo(user_id, "海外旅行の持ち物はパスポートと現金", "本文がカタカナ", None, session=session)
            await insert_memo(user_id, "本文は漢字だけ", "ぱすぽーと更新メモ", None, session=session)
            await insert_memo(user_id, "関係のないメモ", "無関係", None, session=session)

            expected = ["ぱすぽーと更新メモ", "本文がカタカナ"]
            self.assertEqual(await self._search(session, user_id, "ぱすぽーと"), expected)
            self.assertEqual(await self._search(session, user_id, "パスポート"), expected)
            self.assertEqual(await self._search(session, user_id, "ぱすぽーと 持ち物"), ["本文がカタカナ"])
            self.assertEqual(await self._search(session, user_id, "ぱすぽーと 存在しない語"), [])

            await session.execute(text("DELETE FROM memo_entries WHERE user_id = :id"), {"id": user_id})
            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


if __name__ == "__main__":
    unittest.main()
