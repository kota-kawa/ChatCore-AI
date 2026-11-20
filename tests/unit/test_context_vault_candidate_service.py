"""記憶の自動抽出サービス（保存の設定確認、入力の整形、保存した事実の埋め込み予約、抽出の設定）を検証するテスト。

Tests the memory auto-extraction service: the setting check on store, input shaping, embedding scheduling for
saved facts, and the extraction setting.
"""

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from services.context_vault_candidate_service import (
    get_extraction_settings,
    is_context_extraction_enabled,
    store_extracted_facts,
    update_extraction_settings,
)
from services.context_vault_embeddings import build_context_fact_embedding_text
from services.context_vault_reconcile import (
    CONTEXT_RECONCILE_MODEL,
    RECONCILE_MAX_DISTANCE,
    RECONCILE_NEIGHBOR_LIMIT,
    CandidatePlan,
    ReconcileResolution,
)
from services.llm import GPT_6_LUNA_MODEL


# 日本語: 事実テーブルの 1 行分の辞書を作ります。
# English: Build one fact-table row dict.
def _fact(**overrides):
    row = {
        "id": 31,
        "user_id": 7,
        "fact_type": "project",
        "title": "Edited title",
        "content": "Edited content",
        "source_kind": "chat",
        "source_ref": "room-123",
        "source_client_id": None,
        "importance": 95,
        "status": "active",
        "revision": 1,
        "created_at": "2026-07-23T12:00:00",
        "updated_at": "2026-07-23T12:00:00",
    }
    row.update(overrides)
    return row


# 日本語: リポジトリの非同期メソッドをモックに差し替えた入れ物を作ります。
# English: Build a repository stand-in whose async methods are mocks.
def _repo():
    repo = MagicMock()
    for name in (
        "get_extraction_settings",
        "update_extraction_settings",
        "store_extracted",
    ):
        setattr(repo, name, AsyncMock())
    return repo


# 日本語: リポジトリをモックし、サービス層の入出力の整形と呼び出し順を確認します。
# English: Mock the repository and check the service layer's input/output shaping and call order.
class ContextVaultCandidateServiceTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_store_extracted_facts_requires_setting_and_normalizes_input(self):
        repo = _repo()
        repo.get_extraction_settings.side_effect = [False, True]
        repo.store_extracted.return_value = [_fact()]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            disabled = await store_extracted_facts(
                7,
                candidates=[{"fact_type": "project", "title": "T", "content": "C"}],
                source_ref="room-123",
                session=object(),
            )
            self.assertEqual(disabled, [])
            repo.store_extracted.assert_not_awaited()
            stored = await store_extracted_facts(
                7,
                candidates=[
                    {
                        "fact_type": "project",
                        "title": "  Chat-Core  ",
                        "content": "  Phase 2  ",
                        "importance": 80,
                        "confidence": 0.9,
                        "internal": "ignored",
                    },
                    {"fact_type": "bogus", "title": "Bad", "content": "Bad"},
                ],
                source_ref="  room-123  ",
                session=object(),
            )
        self.assertEqual([fact["id"] for fact in stored], [31])
        prepared = repo.store_extracted.call_args.args[1]
        self.assertEqual(len(prepared), 1)
        self.assertEqual(prepared[0]["title"], "Chat-Core")
        self.assertEqual(prepared[0]["source_kind"], "chat")
        self.assertEqual(prepared[0]["source_ref"], "room-123")
        self.assertEqual(len(prepared[0]["fingerprint"]), 64)

    async def test_store_extracted_facts_passes_evidence_and_message_origin_to_the_repository(self):
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.store_extracted.return_value = []
        candidates = [
            {"fact_type": "project", "title": "T", "content": "C", "evidence": "  I build T  "},
            {"fact_type": "project", "title": "T2", "content": "C2", "evidence": "x" * 1500},
            {"fact_type": "project", "title": "T3", "content": "C3"},
        ]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            await store_extracted_facts(
                7,
                candidates=candidates,
                source_ref="chat:room-1:message:9",
                room_id="room-1",
                user_message_id=8,
                session=object(),
            )

        prepared = repo.store_extracted.call_args.args[1]
        # 長い引用は候補を落とさず 1000 文字で切り、前後の空白は除く。引用が無い候補は空のまま渡す。
        # An overlong quote is cut to 1000 characters instead of dropping the candidate; a missing quote stays empty.
        self.assertEqual([candidate["evidence"] for candidate in prepared], ["I build T", "x" * 1000, ""])
        # 呼び出し側のセッションでは照合(埋め込み・LLM)をしないので、照合の結果は渡さない。
        # With a caller-supplied session nothing is reconciled (no embedding or LLM), so no plans are passed.
        self.assertEqual(repo.store_extracted.call_args.kwargs, {"room_id": "room-1", "user_message_id": 8, "plans": None})

    async def test_store_extracted_facts_schedules_embedding_for_each_saved_fact_after_commit(self):
        saved = [_fact(id=31, revision=1), _fact(id=32, title="Second", content="Other", revision=1)]
        candidates = [{"fact_type": "project", "title": "T", "content": "C"}]
        with patch(
            "services.context_vault_candidate_service._transaction",
            new=AsyncMock(return_value=saved),
        ), patch("services.context_vault_candidate_service.schedule_embedding") as schedule, patch(
            "services.context_vault_candidate_service._plan_reconciliation", new=AsyncMock(return_value={})
        ):
            result = await store_extracted_facts(7, candidates=candidates, source_ref="chat:r:message:1")
        self.assertEqual(result, saved)
        self.assertEqual([call.args[0] for call in schedule.call_args_list], [31, 32])
        schedule.assert_any_call(32, "project", "Second", "Other", 1)

        # 呼び出し側のセッションを使う場合は、コミット前に予約しない。
        # With a caller-supplied session nothing is scheduled before the caller commits.
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.store_extracted.return_value = saved
        with patch("services.context_vault_candidate_service._repository", return_value=repo), patch(
            "services.context_vault_candidate_service.schedule_embedding"
        ) as schedule:
            await store_extracted_facts(7, candidates=candidates, source_ref="chat:r:message:1", session=object())
        schedule.assert_not_called()

    async def test_store_extracted_facts_without_valid_candidates_does_not_touch_repository(self):
        repo = _repo()
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            result = await store_extracted_facts(
                7,
                candidates=[{"fact_type": "bogus", "title": "Bad", "content": "Bad"}, "not-a-dict"],  # type: ignore[list-item]
                source_ref="room-123",
                session=object(),
            )
        self.assertEqual(result, [])
        repo.get_extraction_settings.assert_not_awaited()

    async def test_extraction_runs_whenever_the_setting_is_on_even_at_the_cap(self):
        # 上限でも入れ替えと再言及の記録があるので、抽出を走らせる条件は設定だけにする。
        # At the cap there is still replacement and re-mention recording, so the setting alone decides whether extraction runs.
        repo = _repo()
        repo.get_extraction_settings.side_effect = [True, False]
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            self.assertTrue(await is_context_extraction_enabled(7, session=object()))
            self.assertFalse(await is_context_extraction_enabled(7, session=object()))


    async def test_get_and_update_extraction_settings_return_the_stored_value(self):
        repo = _repo()
        repo.get_extraction_settings.return_value = True
        repo.update_extraction_settings.return_value = False
        with patch("services.context_vault_candidate_service._repository", return_value=repo):
            current = await get_extraction_settings(7, session=object())
            updated = await update_extraction_settings(7, False, session=object())

        self.assertTrue(current.enabled)
        self.assertFalse(updated.enabled)
        repo.update_extraction_settings.assert_awaited_once_with(7, False)


_MODULE = "services.context_vault_candidate_service"
_EMBEDDING = [0.125] * 768


# 日本語: 照合の経路に使うリポジトリ・トランザクション・埋め込み・LLM をまとめて差し替える入れ物。events に、DB トランザクションの開閉・
# 埋め込み・LLM・保存の呼び出し順を記録するので、「トランザクションの外で埋め込みと LLM を呼ぶ」ことを順序で確かめられる。
# English: Stands in for the repository, transactions, embedding and LLM used by reconciliation. events records the order of DB
# transaction open/close, embedding, LLM and store calls, so "embedding and LLM run outside any transaction" is checked by order.
class _ReconcileHarness:
    def __init__(self, *, neighbors=None, llm_response=None, embedding=_EMBEDDING):
        self.events: list[str] = []
        self.neighbors = neighbors if neighbors is not None else {}
        self.llm_response = llm_response
        self.embedding = embedding
        self.embedded_texts: list[str] = []
        self.llm_calls: list[tuple] = []
        self.duplicate_matches: list | None = None
        self.llm_error: Exception | None = None
        self.neighbor_error: Exception | None = None
        self.saved: list[dict] = []
        self.enabled = True

        self.repo = MagicMock()
        self.repo.get_extraction_settings = AsyncMock(side_effect=lambda _user_id: self.enabled)
        self.repo.find_duplicate_matches = AsyncMock(side_effect=self._find_duplicate_matches)
        self.repo.store_extracted = AsyncMock(side_effect=self._store_extracted)
        self.facts = MagicMock()
        self.facts.find_reconcile_neighbors = AsyncMock(side_effect=self._find_neighbors)

    async def _find_duplicate_matches(self, _user_id, candidates):
        if self.duplicate_matches is not None:
            return self.duplicate_matches
        return [None] * len(candidates)

    async def _find_neighbors(self, _user_id, embedding, **kwargs):
        self.neighbor_kwargs = kwargs
        if self.neighbor_error is not None:
            raise self.neighbor_error
        return list(self.neighbors.get(tuple(embedding[:1]), self.neighbors.get("default", [])))

    async def _store_extracted(self, _user_id, prepared, **kwargs):
        self.events.append("store")
        self.store_kwargs = kwargs
        return list(self.saved)

    async def _transaction(self, session, operation):
        self.events.append("tx_open")
        try:
            return await operation(object())
        finally:
            self.events.append("tx_close")

    def _generate_embedding(self, text):
        self.events.append("embed")
        self.embedded_texts.append(text)
        return self.embedding

    def _llm(self, messages, model):
        self.events.append("llm")
        self.llm_calls.append((messages, model))
        if self.llm_error is not None:
            raise self.llm_error
        return self.llm_response

    def patches(self, *, embeddings_available=True):
        return [
            patch(f"{_MODULE}._repository", return_value=self.repo),
            patch(f"{_MODULE}.ContextFactRepository", return_value=self.facts),
            patch(f"{_MODULE}._transaction", new=self._transaction),
            patch(f"{_MODULE}.embeddings_available", return_value=embeddings_available),
            patch(f"{_MODULE}.generate_embedding", side_effect=self._generate_embedding),
            patch(f"{_MODULE}.get_llm_json_response", side_effect=self._llm),
            patch(f"{_MODULE}.schedule_embedding"),
        ]

    async def run(self, candidates=None, *, embeddings_available=True, **kwargs):
        candidates = candidates or [{"fact_type": "profile", "title": "  Home city ", "content": "Lives in Osaka"}]
        patchers = self.patches(embeddings_available=embeddings_available)
        mocks = [patcher.start() for patcher in patchers]
        try:
            self.schedule = mocks[-1]
            return await store_extracted_facts(7, candidates=candidates, source_ref="chat:r:message:1", **kwargs)
        finally:
            for patcher in patchers:
                patcher.stop()


def _neighbor(fact_id=12, *, status="active", revision=3, content="Lives in Tokyo"):
    return {
        "id": fact_id,
        "revision": revision,
        "fact_type": "profile",
        "title": "Home city",
        "content": content,
        "status": status,
        "last_mentioned": datetime(2026, 11, 1, 9, 0, tzinfo=UTC),
    }


def _decisions(*decisions):
    return json.dumps({"decisions": list(decisions)})


# 日本語: 保存の前の照合（埋め込み・近い記憶・LLM の判定）が、保存へ渡す結果と呼び出し順、失敗時の挙動を確かめます。
# English: Checks what reconciliation before storage (embedding, nearby memory, the LLM decision) hands to storage, the order of
# calls, and behavior on failure.
class ContextVaultReconcileFlowTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_update_decision_is_handed_to_storage_with_the_embedding_and_skips_the_post_save_embedding(self):
        harness = _ReconcileHarness(
            neighbors={"default": [_neighbor(12, revision=5)]},
            llm_response=_decisions({"candidate": 0, "action": "update", "target_id": 12}),
        )
        harness.saved = [_fact(id=41, embedding_status="ready")]

        saved = await harness.run()

        self.assertEqual(saved, harness.saved)
        plans = harness.store_kwargs["plans"]
        self.assertEqual(
            plans,
            {0: CandidatePlan(embedding=_EMBEDDING, resolution=ReconcileResolution("supersede", 12, 5))},
        )
        # 照合で作った埋め込みを保存した事実は、保存後の埋め込みの予約をしない。
        # A fact saved with the embedding made while reconciling is not scheduled for an embedding after the save.
        harness.schedule.assert_not_called()

    async def test_order_is_read_then_embed_then_read_then_llm_then_store_with_no_transaction_open_across_embed_or_llm(self):
        harness = _ReconcileHarness(
            neighbors={"default": [_neighbor()]},
            llm_response=_decisions({"candidate": 0, "action": "noop", "target_id": 12}),
        )

        await harness.run()

        self.assertEqual(
            harness.events,
            [
                "tx_open", "tx_close",  # 設定と重複判定の読み取り / the setting and duplicate-check read
                "embed",  # トランザクションの外 / outside any transaction
                "tx_open", "tx_close",  # 近い記憶の読み取り / the nearby-memory read
                "llm",  # トランザクションの外 / outside any transaction
                "tx_open", "store", "tx_close",  # ロックを取る保存 / the save that takes the lock
            ],
        )

    async def test_candidate_embedding_text_is_the_one_the_stored_fact_would_be_embedded_with(self):
        harness = _ReconcileHarness()
        harness.saved = [_fact(id=41, fact_type="profile", title="Home city", content="Lives in Osaka", embedding_status="ready")]

        await harness.run()

        [text] = harness.embedded_texts
        saved = harness.saved[0]
        self.assertEqual(text, build_context_fact_embedding_text(saved["fact_type"], saved["title"], saved["content"]))

    async def test_the_llm_gets_the_extraction_model_the_distance_ceiling_and_a_json_input(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]}, llm_response=_decisions())

        await harness.run()

        [(messages, model)] = harness.llm_calls
        self.assertEqual(model, CONTEXT_RECONCILE_MODEL)
        self.assertEqual(model, GPT_6_LUNA_MODEL)
        self.assertEqual(harness.neighbor_kwargs, {"limit": RECONCILE_NEIGHBOR_LIMIT, "max_distance": RECONCILE_MAX_DISTANCE})
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["candidates"][0]["title"], "Home city")
        self.assertEqual(payload["candidates"][0]["nearby_memory_ids"], [12])
        self.assertEqual(payload["memories"][0]["last_mentioned"], "2026-11-01")

    async def test_without_a_nearby_memory_the_llm_is_not_called_and_the_candidate_is_added_with_its_embedding(self):
        harness = _ReconcileHarness(neighbors={})

        await harness.run()

        self.assertEqual(harness.llm_calls, [])
        self.assertEqual(harness.store_kwargs["plans"], {0: CandidatePlan(embedding=_EMBEDDING)})

    async def test_when_embeddings_are_unavailable_nothing_is_embedded_read_or_asked_and_the_post_save_embedding_remains(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]})
        harness.saved = [_fact(id=41)]

        await harness.run(embeddings_available=False)

        self.assertEqual(harness.embedded_texts, [])
        self.assertEqual(harness.llm_calls, [])
        harness.facts.find_reconcile_neighbors.assert_not_awaited()
        self.assertEqual(harness.store_kwargs["plans"], {})
        harness.schedule.assert_called_once()

    async def test_a_candidate_whose_embedding_failed_is_added_and_embedded_after_the_save(self):
        harness = _ReconcileHarness(embedding=None, neighbors={"default": [_neighbor()]})
        harness.saved = [_fact(id=41)]

        await harness.run()

        self.assertEqual(harness.llm_calls, [])
        self.assertEqual(harness.store_kwargs["plans"], {})
        harness.schedule.assert_called_once()

    async def test_duplicates_are_neither_embedded_nor_reconciled(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]})
        harness.duplicate_matches = [{"fact_id": 12, "fact_status": "active"}]

        await harness.run()

        self.assertEqual(harness.embedded_texts, [])
        self.assertEqual(harness.llm_calls, [])
        self.assertEqual(harness.store_kwargs["plans"], {})

    async def test_when_the_setting_is_off_nothing_is_embedded_or_asked(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]})
        harness.enabled = False

        saved = await harness.run()

        self.assertEqual(saved, [])
        self.assertEqual(harness.embedded_texts, [])
        self.assertEqual(harness.llm_calls, [])
        harness.repo.store_extracted.assert_not_awaited()

    async def test_an_llm_failure_adds_the_candidate_and_keeps_its_embedding(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]})
        harness.llm_error = RuntimeError("provider down")

        with self.assertLogs(_MODULE, level="WARNING") as logs:
            await harness.run()

        self.assertEqual(harness.store_kwargs["plans"], {0: CandidatePlan(embedding=_EMBEDDING)})
        self.assertEqual(harness.events[-3:], ["tx_open", "store", "tx_close"])
        self.assertEqual(logs.records[0].error_type, "RuntimeError")

    async def test_invalid_empty_and_missing_llm_responses_add_the_candidate(self):
        for label, response in (("none", None), ("empty", ""), ("garbage", "update 12"), ("foreign id", _decisions(
            {"candidate": 0, "action": "update", "target_id": 99}
        ))):
            with self.subTest(label):
                harness = _ReconcileHarness(neighbors={"default": [_neighbor()]}, llm_response=response)

                await harness.run()

                self.assertEqual(harness.store_kwargs["plans"], {0: CandidatePlan(embedding=_EMBEDDING)})

    async def test_a_failing_nearby_memory_read_adds_the_candidate_without_logging_the_sql_parameters(self):
        harness = _ReconcileHarness()
        harness.neighbor_error = RuntimeError("INSERT ... parameters: ('Lives in Osaka',)")

        with self.assertLogs(_MODULE, level="WARNING") as logs:
            await harness.run()

        self.assertEqual(harness.llm_calls, [])
        self.assertEqual(harness.store_kwargs["plans"], {0: CandidatePlan(embedding=_EMBEDDING)})
        record = logs.records[0]
        self.assertIsNone(record.exc_info)
        self.assertNotIn("Osaka", logs.output[0])
        self.assertNotIn("Osaka", str(record.__dict__))

    async def test_a_failing_first_read_still_saves_the_candidate_as_before(self):
        harness = _ReconcileHarness()
        harness.repo.find_duplicate_matches = AsyncMock(side_effect=RuntimeError("db down"))

        with self.assertLogs(_MODULE, level="WARNING"):
            await harness.run()

        self.assertEqual(harness.store_kwargs["plans"], {})

    async def test_nothing_in_the_logs_carries_memory_text_or_the_llm_response(self):
        for response in (
            "Lives in Osaka, not json",
            '{"decisions": [{"candidate": 0, "action": "update", "target_id": 99, "note": "Lives in Osaka"}], "x": "Tokyo"}',
        ):
            with self.subTest(response=response):
                harness = _ReconcileHarness(neighbors={"default": [_neighbor(content="Lives in Tokyo")]}, llm_response=response)
                harness.llm_error = None

                with self.assertLogs(level="DEBUG") as logs:
                    await harness.run()

                joined = "\n".join(logs.output) + str([record.__dict__ for record in logs.records])
                self.assertNotIn("Osaka", joined)
                self.assertNotIn("Tokyo", joined)
                self.assertNotIn("Home city", joined)

    async def test_with_a_caller_session_nothing_is_embedded_or_asked(self):
        harness = _ReconcileHarness(neighbors={"default": [_neighbor()]})

        await harness.run(session=object())

        self.assertEqual(harness.embedded_texts, [])
        self.assertEqual(harness.llm_calls, [])
        self.assertIsNone(harness.store_kwargs["plans"])

    async def test_candidates_are_reconciled_by_their_index_in_the_prepared_list(self):
        # 2 件のうち 1 件目が重複なら、照合の対象は 2 件目（添字 1）だけで、結果もその添字で保存へ渡す。
        # When the first of two candidates is a duplicate, only the second (index 1) is reconciled and the result keeps that index.
        harness = _ReconcileHarness(
            neighbors={"default": [_neighbor(12, revision=2)]},
            llm_response=_decisions({"candidate": 1, "action": "update", "target_id": 12}),
        )
        harness.duplicate_matches = [{"fact_id": 5, "fact_status": "active"}, None]

        await harness.run(
            [
                {"fact_type": "profile", "title": "A", "content": "first"},
                {"fact_type": "profile", "title": "B", "content": "second"},
            ]
        )

        self.assertEqual(
            harness.store_kwargs["plans"],
            {1: CandidatePlan(embedding=_EMBEDDING, resolution=ReconcileResolution("supersede", 12, 2))},
        )
        self.assertEqual(len(harness.embedded_texts), 1)


if __name__ == "__main__":
    unittest.main()
