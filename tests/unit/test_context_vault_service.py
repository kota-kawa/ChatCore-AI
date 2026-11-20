"""文脈の事実のリクエストモデルの検証と ContextVaultService（作成・更新・一覧・検索・ダイジェスト）
の入出力と埋め込みの予約を検証するテスト。

Tests the context fact request models and ContextVaultService (create, update, list, search, digest),
including input/output shaping and embedding scheduling.
"""

import unittest
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from services.api_errors import ApiServiceError
from services.context_vault_service import (
    build_digest,
    create_fact,
    get_fact,
    get_memory_use_settings,
    list_facts,
    search_facts,
    update_fact,
    update_memory_use_settings,
)
from services.repositories.context_fact_provenance_repository import FactProvenance
from services.request_models import (
    ContextFactCreateRequest,
    ContextFactUpdateRequest,
    McpContextFactSaveRequest,
)
from services.response_models import ContextFactListItemResponse, ContextFactResponse


# 日本語: 事実テーブルの 1 行分の辞書を作ります。
# English: Build one fact-table row dict.
def fact_row(**overrides):
    row = {
        "id": 3,
        "user_id": 7,
        "fact_type": "preference",
        "title": "Editor",
        "content": "Uses vim keybindings",
        "source_kind": "manual",
        "source_ref": None,
        "source_client_id": None,
        "importance": 50,
        "status": "active",
        "revision": 2,
        "created_at": "2026-07-18T01:00:00",
        "updated_at": "2026-07-18T02:00:00",
    }
    row.update(overrides)
    return row


# 日本語: async with と begin() だけを備えた、トランザクション境界の代役です。
# English: A stand-in for the transaction boundary that supports only async with and begin().
class _TransactionSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def begin(self):
        return self


# 日本語: リポジトリの非同期メソッドをモックに差し替えた入れ物を作ります。
# English: Build a repository stand-in whose async methods are mocks.
def _repo():
    repo = MagicMock()
    for name in (
        "create_fact",
        "update_fact",
        "get_fact",
        "list_facts",
        "count_active",
        "list_active_for_digest",
        "semantic_search",
        "text_search",
    ):
        setattr(repo, name, AsyncMock())
    return repo


# 日本語: 一覧が出典・置き換えの関係を読む ContextFactProvenanceRepository の代役。load は行の id ごとの FactProvenance を返します。
# English: Build a stand-in for ContextFactProvenanceRepository (the list reads sources and replacement relations from it);
# load returns a FactProvenance per row id.
def _provenance_repo(by_id=None):
    repo = MagicMock()

    async def load(_user_id, rows):
        return {int(row["id"]): (by_id or {}).get(int(row["id"]), FactProvenance()) for row in rows}

    repo.load = AsyncMock(side_effect=load)
    return repo


# 日本語: 作成・更新リクエストの入力契約を確認します。
# English: Check the input contract of the create and update requests.
class ContextFactRequestModelTestCase(unittest.TestCase):
    def test_create_and_update_requests_validate_contracts(self):
        with self.assertRaises(ValidationError):
            ContextFactCreateRequest(fact_type="preference", title=" ", content="x")
        with self.assertRaises(ValidationError):
            ContextFactUpdateRequest(revision=1)
        self.assertEqual(
            ContextFactCreateRequest(
                fact_type="preference", title="Editor", content="Vim"
            ).importance,
            50,
        )
        payload = McpContextFactSaveRequest(
            fact_type="preference",
            title="Editor",
            content="Vim",
            idempotency_key="retry-1",
        )
        self.assertEqual(payload.idempotency_key, "retry-1")


# 日本語: リポジトリをモックし、サービスの冪等性、リビジョン、埋め込みの予約を確認します。
# English: Mock the repository and check idempotency, revisions and embedding scheduling in the service.
class ContextVaultServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_create_hashes_idempotency_and_schedules_after_transaction(self):
        repo = _repo()
        repo.create_fact.return_value = fact_row(
            revision=1,
            source_kind="mcp",
            source_ref="conversation:3",
            source_client_id="cursor",
            importance=80,
        )
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
                importance=80,
                source_kind="mcp",
                source_ref="conversation:3",
                source_client_id="cursor",
                idempotency_key="retry-1",
            )

        self.assertEqual(result.id, 3)
        kwargs = repo.create_fact.call_args.kwargs
        self.assertEqual(
            kwargs["idempotency_key_hash"],
            sha256(b"7\0mcp\0cursor\0retry-1").hexdigest(),
        )
        schedule.assert_called_once_with(
            3, "preference", "Editor", "Uses vim keybindings", 1
        )

    async def test_idempotent_replay_does_not_schedule_embedding(self):
        repo = _repo()
        repo.create_fact.return_value = fact_row(_idempotent_replay=True)
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await create_fact(
                7,
                fact_type="preference",
                title="Editor",
                content="Uses vim",
                idempotency_key="retry-1",
            )
        self.assertEqual(result.id, 3)
        schedule.assert_not_called()

    async def test_update_passes_revision_and_reembeds_active_fact(self):
        repo = _repo()
        repo.update_fact.return_value = fact_row(content="new", revision=3)
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope",
            return_value=_TransactionSession(),
        ), patch("services.context_vault_service.schedule_embedding") as schedule:
            result = await update_fact(
                7,
                3,
                expected_revision=2,
                content="new",
                importance=90,
            )
        self.assertEqual(result.revision, 3)
        self.assertEqual(repo.update_fact.call_args.kwargs["expected_revision"], 2)
        schedule.assert_called_once()

    async def test_responses_carry_confidence_and_last_confirmed_at(self):
        repo = _repo()
        repo.get_fact.return_value = fact_row(
            source_kind="chat", confidence=0.8, last_confirmed_at="2026-09-01T10:00:00"
        )
        with patch("services.context_vault_service._repository", return_value=repo):
            confirmed = await get_fact(7, 3, session=object())
        repo.get_fact.return_value = fact_row(source_kind="mcp")
        with patch("services.context_vault_service._repository", return_value=repo):
            unconfirmed = await get_fact(7, 3, session=object())

        self.assertEqual(confirmed.confidence, 0.8)
        self.assertEqual(confirmed.last_confirmed_at, "2026-09-01T10:00:00")
        self.assertIsNone(unconfirmed.confidence)
        self.assertIsNone(unconfirmed.last_confirmed_at)

    async def test_list_reports_the_reason_only_for_deprecated_facts(self):
        # 旧バージョンのコードが復元した行には理由が残るので、有効な事実には返さない。理由が無い無効化済みの行は None。
        # An older code color leaves the reason on restore, so an active fact never reports one; a deprecated row without one is None.
        cases = (
            ({"status": "deprecated", "deprecated_reason": "capacity"}, "capacity"),
            ({"status": "deprecated", "deprecated_reason": "user"}, "user"),
            ({"status": "deprecated", "deprecated_reason": None}, None),
            ({"status": "deprecated"}, None),
            ({"status": "active", "deprecated_reason": "capacity"}, None),
        )
        for row, expected in cases:
            repo = _repo()
            repo.list_facts.return_value = [fact_row(**row)]
            repo.count_active.return_value = 0
            with self.subTest(row=row), patch("services.context_vault_service._repository", return_value=repo), patch(
                "services.context_vault_service.ContextFactProvenanceRepository", return_value=_provenance_repo()
            ):
                result = await list_facts(7, status="deprecated", session=object())
            self.assertEqual(result.facts[0].deprecated_reason, expected)

    async def test_only_the_web_list_carries_deprecated_reason(self):
        # 理由・出典・置き換えの関係は記憶の画面の一覧だけが返す。単体取得・更新・MCP の応答・ダイジェスト・検索は、これらの項目を持たない
        # main と同じ形で、AI に渡る内容と、ダイジェストの文字予算を測る JSON の長さを変えない。
        # Only the memory screen's list returns the reason, sources and replacement relations. Single reads, updates, MCP responses,
        # the digest and search keep the shape without them, so what reaches the AI and the JSON length the digest budget measures
        # are unchanged.
        expected_keys = {
            "id", "fact_type", "title", "content", "status", "revision", "source_kind", "importance",
            "confidence", "last_confirmed_at", "created_at", "updated_at",
        }  # fmt: skip
        self.assertEqual(set(ContextFactResponse.model_fields), expected_keys)
        self.assertEqual(
            set(ContextFactListItemResponse.model_fields),
            expected_keys | {"deprecated_reason", "source_count", "last_mentioned_at", "sources", "superseded_by", "replaces"},
        )

        repo = _repo()
        row = fact_row(status="deprecated", deprecated_reason="capacity")
        repo.get_fact.return_value = row
        repo.update_fact.return_value = row
        repo.list_active_for_digest.return_value = [fact_row(deprecated_reason="capacity")]
        repo.text_search.return_value = [fact_row(deprecated_reason="capacity")]
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.session_scope", return_value=_TransactionSession()
        ), patch("services.context_vault_service.schedule_embedding"):
            fetched = await get_fact(7, 3, session=object())
            updated = await update_fact(7, 3, expected_revision=1, status="deprecated")
            digest = await build_digest(7, session=object())
            search = await search_facts(7, "editor", session=object())

        self.assertNotIsInstance(fetched, ContextFactListItemResponse)
        self.assertEqual(set(fetched.model_dump()), expected_keys)
        self.assertEqual(set(updated.model_dump()), expected_keys)
        self.assertEqual(set(digest.groups[0].facts[0].model_dump()), expected_keys)
        self.assertEqual(set(search.facts[0].model_dump()), expected_keys)
        for name in ("deprecated_reason", "source_count", "sources", "superseded_by", "replaces", "last_mentioned_at"):
            self.assertNotIn(name, digest.model_dump_json())

    async def test_update_is_unconfirmed_unless_the_owner_edits(self):
        for owner, expected in ((None, False), (True, True)):
            repo = _repo()
            repo.update_fact.return_value = fact_row(content="new", revision=3)
            extra = {} if owner is None else {"confirmed_by_owner": owner}
            with self.subTest(owner=owner), patch(
                "services.context_vault_service._repository", return_value=repo
            ), patch(
                "services.context_vault_service.session_scope",
                return_value=_TransactionSession(),
            ), patch("services.context_vault_service.schedule_embedding"):
                await update_fact(7, 3, expected_revision=2, content="new", **extra)
            self.assertIs(repo.update_fact.call_args.kwargs["confirmed_by_owner"], expected)

    async def test_list_uses_keyset_cursor_and_total_active(self):
        repo = _repo()
        repo.list_facts.return_value = [fact_row(id=4), fact_row(id=3)]
        repo.count_active.return_value = 2
        provenance = _provenance_repo()
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.ContextFactProvenanceRepository", return_value=provenance
        ):
            result = await list_facts(7, limit=1, session=object())
        self.assertEqual(len(result.facts), 1)
        # 出典・置き換えの関係は、返す行だけを 1 回でまとめて読む（余分に取った 1 行は含めない）。
        # Sources and replacement relations are read once for the returned rows only (not the extra row fetched to detect a next page).
        provenance.load.assert_awaited_once()
        self.assertEqual([row["id"] for row in provenance.load.await_args.args[1]], [4])
        self.assertEqual(result.total_active, 2)
        self.assertIsNotNone(result.next_cursor)
        repo.list_facts.assert_awaited_once()
        repo.count_active.assert_awaited_once_with(7)

    async def test_list_passes_the_search_query_and_attaches_provenance_per_fact(self):
        repo = _repo()
        repo.list_facts.return_value = [
            fact_row(id=4, status="active"),
            fact_row(id=3, status="deprecated", deprecated_reason="superseded"),
        ]
        repo.count_active.return_value = 1
        provenance = _provenance_repo(
            {
                4: FactProvenance(
                    source_count=5,
                    last_mentioned_at="2026-11-01T00:00:00+00:00",
                    sources=[{"chat_room_id": "room-1", "evidence": "東京に住んでいます", "observed_at": "2026-11-01T00:00:00+00:00"}],
                    replaces={"id": 3, "title": "旧住所", "content": "大阪に住んでいる"},
                ),
                3: FactProvenance(superseded_by={"id": 4, "title": "住所"}),
            }
        )
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.ContextFactProvenanceRepository", return_value=provenance
        ):
            result = await list_facts(7, query="東京", session=object())

        self.assertEqual(repo.list_facts.await_args.kwargs["query"], "東京")
        newer, older = result.facts
        self.assertEqual(newer.source_count, 5)
        self.assertEqual(newer.last_mentioned_at, "2026-11-01T00:00:00+00:00")
        self.assertEqual(newer.sources[0].evidence, "東京に住んでいます")
        self.assertEqual(newer.replaces.title, "旧住所")
        self.assertIsNone(newer.superseded_by)
        self.assertEqual(older.superseded_by.id, 4)
        self.assertEqual((older.source_count, older.sources, older.replaces), (0, [], None))

    async def test_digest_groups_and_search_falls_back_from_semantic(self):
        repo = _repo()
        repo.list_active_for_digest.return_value = [
            fact_row(fact_type="project", importance=90),
            fact_row(id=4, fact_type="preference", importance=60),
        ]
        repo.semantic_search.return_value = []
        repo.text_search.return_value = [fact_row()]
        with patch("services.context_vault_service._repository", return_value=repo), patch(
            "services.context_vault_service.embeddings_available", return_value=True
        ), patch(
            "services.context_vault_service.asyncio.to_thread",
            new=AsyncMock(return_value=[0.1, 0.2]),
        ):
            digest = await build_digest(7, session=object())
            search = await search_facts(7, "editor", mode="semantic", session=object())
        self.assertEqual([group.fact_type for group in digest.groups], ["preference", "project"])
        self.assertEqual(len(search.facts), 1)
        repo.text_search.assert_awaited_once()

    async def test_memory_use_settings_return_the_stored_value(self):
        repo = _repo()
        repo.get_memory_use_enabled = AsyncMock(return_value=True)
        repo.update_memory_use_enabled = AsyncMock(return_value=False)
        with patch("services.context_vault_service._repository", return_value=repo):
            current = await get_memory_use_settings(7, session=object())
            updated = await update_memory_use_settings(7, False, session=object())

        self.assertTrue(current.enabled)
        self.assertFalse(updated.enabled)
        repo.update_memory_use_enabled.assert_awaited_once_with(7, False)

    async def test_search_rejects_empty_query(self):
        with self.assertRaises(ApiServiceError):
            await search_facts(7, " ", session=object())


if __name__ == "__main__":
    unittest.main()
