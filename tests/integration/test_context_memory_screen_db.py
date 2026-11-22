"""記憶の画面の書き込み（置き換えを元に戻す・1 件の削除・すべての削除）と一覧の出典の読み取りを、
実 PostgreSQL の外部キー（SET NULL・CASCADE）、窓関数、advisory lock を通して検証する。
単体テストはクエリの組み立てとモックしたセッションの実行順しか見ないため、ここで実際の行の変化を確かめる。

PostgreSQL integration coverage for the memory screen's writes (undo a replacement, delete one, delete all) and its list provenance,
run through the real foreign keys (SET NULL, CASCADE), window functions and advisory lock. The unit tests only see the built queries
and the mocked session's call order, so the actual row changes are checked here.
"""

from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_errors import ApiServiceError
from services.db import dispose_engine, session_scope
from services.repositories.context_fact_curation_repository import ContextFactCurationRepository
from services.repositories.context_fact_provenance_repository import (
    MAX_LISTED_SOURCES_PER_FACT,
    ContextFactProvenanceRepository,
)
from services.repositories.context_fact_repository import MAX_ACTIVE_CONTEXT_FACTS, ContextFactRepository
from services.search_terms import split_search_terms


# 日本語: 作ったデータはすべて、この試験が作った利用者の行から外部キーの CASCADE で消える。
# 最後に利用者を消し、途中で失敗してもトランザクションのロールバックで残らない。
# English: Everything created hangs off the users this test creates and goes with them through CASCADE; the users are deleted at the end,
# and a failure midway rolls the transaction back, so nothing is left behind.
@unittest.skipUnless(
    os.environ.get("DATABASE_URL"),
    "requires DATABASE_URL pointing at a PostgreSQL test database",
)
class ContextMemoryScreenDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self) -> None:
        await dispose_engine()

    async def _create_user(self, session: AsyncSession, label: str, **settings: bool) -> int:
        columns = ["email", "username", *settings]
        values = [":email", ":username", *(f":{name}" for name in settings)]
        return int(
            (
                await session.execute(
                    text(f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(values)}) RETURNING id"),
                    {"email": f"memory-screen-{label}-{uuid4().hex}@example.test", "username": label, **settings},
                )
            ).scalar_one()
        )

    async def _create_fact(
        self,
        session: AsyncSession,
        user_id: int,
        title: str,
        *,
        status: str = "active",
        deprecated_reason: str | None = None,
        superseded_by: int | None = None,
    ) -> int:
        return int(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO context_facts
                            (user_id, fact_type, title, content, status, deprecated_reason, superseded_by_fact_id)
                        VALUES (:user_id, 'profile', :title, :content, :status, :reason, :superseded_by)
                        RETURNING id
                        """
                    ),
                    {
                        "user_id": user_id,
                        "title": title,
                        "content": f"{title}の内容",
                        "status": status,
                        "reason": deprecated_reason,
                        "superseded_by": superseded_by,
                    },
                )
            ).scalar_one()
        )

    async def _create_room(self, session: AsyncSession, user_id: int) -> str:
        room_id = f"memory-screen-room-{uuid4().hex}"
        await session.execute(
            text("INSERT INTO chat_rooms (id, user_id) VALUES (:id, :user_id)"), {"id": room_id, "user_id": user_id}
        )
        return room_id

    async def _add_source(
        self, session: AsyncSession, user_id: int, fact_id: int, room_id: str, evidence: str, observed_at: datetime
    ) -> None:
        await session.execute(
            text(
                """
                INSERT INTO context_fact_sources (fact_id, user_id, chat_room_id, evidence, observed_at)
                VALUES (:fact_id, :user_id, :room_id, :evidence, :observed_at)
                """
            ),
            {"fact_id": fact_id, "user_id": user_id, "room_id": room_id, "evidence": evidence, "observed_at": observed_at},
        )

    async def _add_candidate(
        self, session: AsyncSession, user_id: int, label: str, *, status: str, promoted_fact_id: int | None = None
    ) -> int:
        return int(
            (
                await session.execute(
                    text(
                        """
                        INSERT INTO context_fact_candidates
                            (user_id, fact_type, title, content, status, fingerprint, promoted_fact_id)
                        VALUES (:user_id, 'profile', :title, :content, :status, :fingerprint, :promoted)
                        RETURNING id
                        """
                    ),
                    {
                        "user_id": user_id,
                        "title": label,
                        "content": f"{label}の内容",
                        "status": status,
                        "fingerprint": uuid4().hex + uuid4().hex,
                        "promoted": promoted_fact_id,
                    },
                )
            ).scalar_one()
        )

    async def _count(self, session: AsyncSession, table: str, **where: object) -> int:
        clause = " AND ".join(f"{column} = :{column}" for column in where) or "TRUE"
        return int(await session.scalar(text(f"SELECT count(*) FROM {table} WHERE {clause}"), where) or 0)

    async def _fact_row(self, session: AsyncSession, fact_id: int):
        return (
            await session.execute(
                text("SELECT status, deprecated_reason, superseded_by_fact_id, revision FROM context_facts WHERE id = :id"),
                {"id": fact_id},
            )
        ).first()

    # 日本語: 元に戻すは、新しい記憶を理由 user で無効化して古い記憶を有効へ戻し、有効件数を変えない。有効件数が上限ちょうどでも通る。
    # English: Undo deprecates the newer memory with reason user and makes the older one active again, leaving the active count as it
    # was, including when the count is exactly at the cap.
    async def test_revert_swaps_the_two_memories_without_changing_the_active_count_even_at_the_cap(self) -> None:
        async with session_scope() as session, session.begin():
            user_id = await self._create_user(session, "revert")
            newer = await self._create_fact(session, user_id, "新しい記憶")
            older = await self._create_fact(
                session, user_id, "古い記憶", status="deprecated", deprecated_reason="superseded", superseded_by=newer
            )
            for index in range(MAX_ACTIVE_CONTEXT_FACTS - 1):
                await self._create_fact(session, user_id, f"埋め草{index}")
            repository = ContextFactRepository(session)
            self.assertEqual(await repository.count_active(user_id), MAX_ACTIVE_CONTEXT_FACTS)

            deprecated, restored = await ContextFactCurationRepository(session).revert_replacement(user_id, newer, 1)

            self.assertEqual(
                (deprecated["id"], deprecated["status"], restored["id"], restored["status"]),
                (newer, "deprecated", older, "active"),
            )
            newer_row = await self._fact_row(session, newer)
            older_row = await self._fact_row(session, older)
            self.assertEqual(tuple(newer_row), ("deprecated", "user", None, 2))
            self.assertEqual(tuple(older_row), ("active", None, None, 2))
            self.assertEqual(await repository.count_active(user_id), MAX_ACTIVE_CONTEXT_FACTS)

            # 同じ revision でもう一度は戻せない（状態が変わっている）。
            # The same revision cannot undo twice (the state has changed).
            with self.assertRaises(ApiServiceError) as conflict:
                await ContextFactCurationRepository(session).revert_replacement(user_id, newer, 1)
            self.assertEqual(conflict.exception.status_code, 409)

            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})

    # 日本語: 1 件の削除は、出典と、その記憶を指す候補を消し、それを置き換え先にしていた古い記憶は
    # 無効化済みのまま置き換え先だけが NULL になる。ほかの記憶・候補と、ほかの利用者の記憶には触れない。
    # English: Deleting one memory removes its sources and the candidates pointing at it; an older memory that pointed at it stays
    # deprecated with only its replacement reference nulled. Other memories, candidates and other users' memories are untouched.
    async def test_delete_one_cascades_sources_removes_its_candidates_and_nulls_the_replacement_link(self) -> None:
        async with session_scope() as session, session.begin():
            user_id = await self._create_user(session, "delete-one")
            other_user = await self._create_user(session, "delete-one-other")
            room_id = await self._create_room(session, user_id)
            now = datetime.now(UTC)

            target = await self._create_fact(session, user_id, "消す記憶")
            older = await self._create_fact(
                session, user_id, "古い記憶", status="deprecated", deprecated_reason="superseded", superseded_by=target
            )
            kept = await self._create_fact(session, user_id, "残す記憶")
            others_fact = await self._create_fact(session, other_user, "他人の記憶")
            await self._add_source(session, user_id, target, room_id, "消す記憶の出典", now)
            await self._add_source(session, user_id, kept, room_id, "残す記憶の出典", now)
            promoted_candidate = await self._add_candidate(
                session, user_id, "消す記憶の候補", status="approved", promoted_fact_id=target
            )
            unrelated_candidate = await self._add_candidate(session, user_id, "無関係な候補", status="rejected")

            await ContextFactCurationRepository(session).delete_fact(user_id, target, 1)

            self.assertIsNone(await self._fact_row(session, target))
            self.assertEqual(await self._count(session, "context_fact_sources", fact_id=target), 0)
            self.assertEqual(await self._count(session, "context_fact_candidates", id=promoted_candidate), 0)
            older_row = await self._fact_row(session, older)
            self.assertEqual(tuple(older_row), ("deprecated", "superseded", None, 1))
            self.assertEqual(await self._count(session, "context_fact_sources", fact_id=kept), 1)
            self.assertEqual(await self._count(session, "context_fact_candidates", id=unrelated_candidate), 1)
            self.assertIsNotNone(await self._fact_row(session, kept))
            self.assertIsNotNone(await self._fact_row(session, others_fact))

            # 別の利用者の記憶は、revision が合っていても本人でないので消せない。
            # Another user's memory cannot be deleted even with a matching revision.
            with self.assertRaises(ApiServiceError) as missing:
                await ContextFactCurationRepository(session).delete_fact(user_id, others_fact, 1)
            self.assertEqual(missing.exception.status_code, 404)

            await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [user_id, other_user]})

    # 日本語: すべての削除は、本人の記憶・出典・候補（却下済みを含む全状態）を消し、
    # ほかの利用者の記憶・出典・候補と、本人の users の設定は残す。
    # English: Delete-all removes the owner's memories, sources and candidates (every status, rejected included) and leaves other users'
    # memories, sources and candidates and the owner's users settings alone.
    async def test_delete_all_removes_only_the_owners_rows_and_keeps_the_settings(self) -> None:
        async with session_scope() as session, session.begin():
            user_id = await self._create_user(
                session, "delete-all", context_auto_extract_enabled=False, memory_use_enabled=False
            )
            other_user = await self._create_user(session, "delete-all-other")
            room_id = await self._create_room(session, user_id)
            other_room = await self._create_room(session, other_user)
            now = datetime.now(UTC)

            active = await self._create_fact(session, user_id, "有効")
            await self._create_fact(session, user_id, "無効化済み", status="deprecated", deprecated_reason="user")
            await self._add_source(session, user_id, active, room_id, "出典", now)
            for status in ("pending", "approved", "rejected"):
                await self._add_candidate(session, user_id, f"候補{status}", status=status)
            others_fact = await self._create_fact(session, other_user, "他人の記憶")
            await self._add_source(session, other_user, others_fact, other_room, "他人の出典", now)
            await self._add_candidate(session, other_user, "他人の候補", status="rejected")

            deleted = await ContextFactCurationRepository(session).delete_all_facts(user_id)

            self.assertEqual(deleted, 2)
            self.assertEqual(await self._count(session, "context_facts", user_id=user_id), 0)
            self.assertEqual(await self._count(session, "context_fact_sources", user_id=user_id), 0)
            self.assertEqual(await self._count(session, "context_fact_candidates", user_id=user_id), 0)
            self.assertEqual(await self._count(session, "context_facts", user_id=other_user), 1)
            self.assertEqual(await self._count(session, "context_fact_sources", user_id=other_user), 1)
            self.assertEqual(await self._count(session, "context_fact_candidates", user_id=other_user), 1)
            settings = (
                await session.execute(
                    text("SELECT context_auto_extract_enabled, memory_use_enabled FROM users WHERE id = :id"), {"id": user_id}
                )
            ).first()
            self.assertEqual(tuple(settings), (False, False))

            await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [user_id, other_user]})

    # 日本語: 一覧の出典は、記憶ごとの全出典から件数と最後の時刻を求め、新しい順の上位 3 件だけを行として返す。置き換えの関係も付く。
    # English: The list provenance derives each memory's count and last time from all of its sources and returns only the newest three
    # as rows, with the replacement relations attached.
    async def test_list_provenance_counts_all_sources_but_lists_only_the_newest_three(self) -> None:
        async with session_scope() as session, session.begin():
            user_id = await self._create_user(session, "provenance")
            other_user = await self._create_user(session, "provenance-other")
            room_id = await self._create_room(session, user_id)
            other_room = await self._create_room(session, other_user)
            base = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)

            many = await self._create_fact(session, user_id, "出典が多い")
            few = await self._create_fact(session, user_id, "出典が少ない")
            none = await self._create_fact(session, user_id, "出典なし")
            older = await self._create_fact(
                session, user_id, "置き換えられた", status="deprecated", deprecated_reason="superseded", superseded_by=many
            )
            for day in (2, 0, 4, 1, 3):
                await self._add_source(session, user_id, many, room_id, f"{day}日目の引用", base + timedelta(days=day))
            await self._add_source(session, user_id, few, room_id, "ひとつだけ", base + timedelta(days=9))
            # 別の利用者の出典は、本人の記憶の行を指していても混ざらない
            # （実際には起きないが、問い合わせが user_id で絞ることを確かめる）。
            # Another user's source never mixes in, even one pointing at the owner's memory (it cannot happen in practice; this checks
            # that the query is scoped by user_id).
            await self._add_source(session, other_user, many, other_room, "他人の引用", base + timedelta(days=30))

            repository = ContextFactProvenanceRepository(session)
            active = await repository.load(
                user_id,
                [{"id": fact, "status": "active", "deprecated_reason": None} for fact in (many, few, none)],
            )
            replaced = await repository.load(
                user_id, [{"id": older, "status": "deprecated", "deprecated_reason": "superseded"}]
            )

            self.assertEqual(active[many].source_count, 5)
            self.assertEqual(active[many].last_mentioned_at, (base + timedelta(days=4)).isoformat())
            self.assertEqual(
                [source["evidence"] for source in active[many].sources],
                ["4日目の引用", "3日目の引用", "2日目の引用"],
            )
            self.assertEqual(len(active[many].sources), MAX_LISTED_SOURCES_PER_FACT)
            self.assertEqual(active[many].replaces, {"id": older, "title": "置き換えられた", "content": "置き換えられたの内容"})
            self.assertEqual((active[few].source_count, [s["evidence"] for s in active[few].sources]), (1, ["ひとつだけ"]))
            self.assertEqual((active[none].source_count, active[none].sources, active[none].last_mentioned_at), (0, [], None))
            self.assertEqual(replaced[older].superseded_by, {"id": many, "title": "出典が多い"})

            await session.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": [user_id, other_user]})

    # 日本語: 一覧の検索(q)とキーワード検索(search_context が使う text_search)は同じ語の一致条件を使う。語の AND、大文字小文字、
    # LIKE のワイルドカード(% _ \)を含む検索語で、2 つが同じ行を同じ順で返し、語の部分一致の定義とも一致することを実 DB で確かめる。
    # English: The list search (q) and the keyword search (text_search, used by search_context) share one term-match condition. For
    # queries with several terms, mixed case and LIKE wildcards (% _ \), both return the same rows in the same order, equal to the
    # plain definition of the term match, checked against a real database.
    async def test_list_search_and_keyword_search_match_the_same_rows(self) -> None:
        facts = [
            ("Alpha Beta", "x"),
            ("alpha", "beta 100% done"),
            ("under_score", "plain"),
            ("underXscore", "plain"),
            ("back\\slash", "plain"),
            ("百分率", "100%"),
            ("全角", "東京に住んでいる"),
        ]
        queries = ["alpha beta", "ALPHA", "100%", "%", "_", "under_score", "\\", "back\\slash", "a%a", "東京 住", "none-such", "alpha,beta"]
        async with session_scope() as session, session.begin():
            user_id = await self._create_user(session, "search-equivalence")
            for title, content in facts:
                await session.execute(
                    text(
                        "INSERT INTO context_facts (user_id, fact_type, title, content, status) "
                        "VALUES (:user_id, 'profile', :title, :content, 'active')"
                    ),
                    {"user_id": user_id, "title": title, "content": content},
                )
            repository = ContextFactRepository(session)
            for query in queries:
                with self.subTest(query=query):
                    listed = [row["id"] for row in await repository.list_facts(user_id, query=query, limit=50)]
                    searched = [row["id"] for row in await repository.text_search(user_id, query, limit=50)]
                    self.assertEqual(listed, searched)
                    terms = split_search_terms(query)
                    expected = {
                        title
                        for title, content in facts
                        if all(term.lower() in title.lower() or term.lower() in content.lower() for term in terms)
                    }
                    titles = {row["title"] for row in await repository.list_facts(user_id, query=query, limit=50)}
                    self.assertEqual(titles, expected)

            await session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


if __name__ == "__main__":
    unittest.main()
