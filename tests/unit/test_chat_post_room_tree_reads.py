"""Guard the number of queries one chat post performs.

POST /api/chat used to load the whole ``chat_history`` tree of a room up to four
times: once for the branch tip, once for the LLM history, once for the prior
web-search evidence and once more to rebuild the room summary.  Each read went
through its own transaction, so a single post took four connections out of a
pool configured with ``max_overflow=0``.

Storing the facts extracted from a turn had the same shape: one
``SELECT ... FOR UPDATE`` per fact.

These tests drive the real :class:`ChatRepository` against a recording session
and count how often it queries, and which columns each read transfers.
"""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from starlette.responses import JSONResponse

from services.chat_use_case import ChatPostUseCase, ChatPostUseCaseDependencies
from services.models import ChatHistory, ChatRoom, MemoryFact
from services.repositories.chat_repository import ChatRepository
from tests.helpers.request_helpers import build_request

ROOM_ID = "room-1"
USER_ID = 42


class _FakeResult:
    """Minimal stand-in for the Result objects ChatRepository consumes."""

    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    @property
    def rowcount(self):
        return len(self._rows)


class _RecordingSession:
    """AsyncSession double that answers chat queries and records every SELECT."""

    def __init__(self, room: ChatRoom, history: list[ChatHistory]) -> None:
        self.room = room
        self.history = list(history)
        self.chat_history_selects: list[list[str]] = []
        self.memory_fact_selects: list[str] = []
        self.memory_facts: list[MemoryFact] = []
        self._pending: list = []

    async def execute(self, statement):
        sql = str(statement)
        if sql.lstrip().startswith("SELECT") and "FROM chat_history" in sql:
            columns = list(statement.selected_columns.keys())
            self.chat_history_selects.append(columns)
            if "FOR UPDATE" in sql:
                return _FakeResult(self.history[-1:])
            rows = [
                {name: getattr(row, name) for name in columns}
                for row in sorted(self.history, key=lambda item: item.id)
            ]
            return _FakeResult(rows)
        if sql.lstrip().startswith("SELECT") and "FROM chat_rooms" in sql:
            return _FakeResult([self.room])
        if sql.lstrip().startswith("SELECT") and "FROM memory_facts" in sql:
            self.memory_fact_selects.append(sql)
            return _FakeResult(
                [(row, str(row.fact).lower()) for row in self.memory_facts]
            )
        return _FakeResult([])

    async def scalar(self, _statement):
        return self.room.active_root_id

    def add(self, record):
        self._pending.append(record)

    async def flush(self):
        for record in self._pending:
            if isinstance(record, MemoryFact):
                self.memory_facts.append(record)
                continue
            if record.id is None:
                record.id = max((row.id for row in self.history), default=0) + 1
            self.history.append(record)
        self._pending.clear()


def _seeded_session() -> _RecordingSession:
    """A room whose active branch already holds one answered turn."""

    first = ChatHistory(
        id=1,
        chat_room_id=ROOM_ID,
        message="前のターンの質問",
        sender="user",
        parent_id=None,
        active_child_id=2,
    )
    second = ChatHistory(
        id=2,
        chat_room_id=ROOM_ID,
        message="前のターンの回答",
        sender="assistant",
        parent_id=1,
        active_child_id=None,
    )
    room = ChatRoom(id=ROOM_ID, user_id=USER_ID, title="既存ルーム", mode="normal", active_root_id=1)
    return _RecordingSession(room, [first, second])


def _build_use_case(session: _RecordingSession, tree_reads: list[str]):
    """Wire the chat-post use case to the real repository over ``session``."""

    original_load_room_tree = ChatRepository._load_room_tree

    async def counting_load_room_tree(self, chat_room_id, *, columns=()):
        tree_reads.append(chat_room_id)
        return await original_load_room_tree(self, chat_room_id, columns=columns)

    repository = ChatRepository(session)  # type: ignore[arg-type]
    repository._load_room_tree = counting_load_room_tree.__get__(repository, ChatRepository)  # type: ignore[method-assign]

    async def require_json_dict(request):
        return await request.json(), None

    def validate_payload_model(data, model_cls, **_kwargs):
        return model_cls(**data), None

    deps = ChatPostUseCaseDependencies(
        cleanup_ephemeral_chats=Mock(),
        require_json_dict=require_json_dict,
        validate_payload_model=validate_payload_model,
        jsonify=lambda payload, status_code=200: JSONResponse(payload, status_code=status_code),
        jsonify_rate_limited=Mock(),
        jsonify_service_error=Mock(),
        log_and_internal_server_error=Mock(),
        validate_model_name=Mock(),
        consume_guest_chat_daily_limit=Mock(return_value=(True, None)),
        get_seconds_until_tomorrow=Mock(return_value=60),
        validate_guest_room_access=Mock(),
        resolve_authenticated_room_target=Mock(return_value=("normal", None, None)),
        ensure_ephemeral_room=Mock(),
        get_temporary_user_store_key=Mock(return_value="tmp:user:42"),
        ephemeral_store=SimpleNamespace(append_message=Mock(), get_messages=Mock(return_value=[])),
        save_message_to_db=repository.save_message,
        store_user_message_and_load_turn_context=repository.store_user_message_and_load_turn_context,
        normalize_messages_for_llm=lambda messages: [
            {"role": item["role"], "content": str(item["content"])} for item in messages
        ],
        find_latest_task_launch_request=Mock(return_value=None),
        load_task_prompt_data=Mock(),
        build_task_prompt=Mock(return_value=None),
        get_user_by_id=Mock(return_value={}),
        build_user_profile_prompt=Mock(return_value=None),
        get_room_summary=Mock(return_value={"summary": ""}),
        list_room_memory_facts=Mock(return_value=[]),
        remember_facts_from_message=AsyncMock(return_value=[]),
        rename_chat_room_if_current_title_in=Mock(return_value=False),
        load_project_context=Mock(return_value=None),
        build_context_messages=lambda **kwargs: kwargs["recent_messages"],
        build_base_system_prompt=Mock(return_value="system"),
        build_generation_key=Mock(return_value="user:42:room-1"),
        has_active_generation=Mock(return_value=False),
        consume_llm_daily_quota=Mock(return_value=(True, 1, 300)),
        cleanup_unanswered_user_messages=Mock(),
        get_seconds_until_daily_reset=Mock(return_value=60),
        is_streaming_model=Mock(return_value=False),
        search_personal_knowledge=Mock(return_value={"status": "no_results"}),
        search_shared_prompts=Mock(return_value={"status": "no_results"}),
        start_generation_job=Mock(),
        build_llm_stream_response=Mock(),
        iter_llm_stream_events=Mock(),
        get_llm_response=Mock(return_value="assistant reply"),
        decide_generative_ui_mode=Mock(return_value=None),
        is_retryable_llm_error=Mock(return_value=False),
        rebuild_room_summary=Mock(),
        should_extract_context=Mock(return_value=False),
        schedule_context_extraction=Mock(),
        submit_background_task=Mock(),
        get_session_id=Mock(return_value="sid-1"),
        logger=Mock(),
    )
    return ChatPostUseCase(deps, default_model="test-model"), deps


def _post(use_case) -> dict:
    request = build_request(
        method="POST",
        path="/api/chat",
        json_body={"message": "新しい質問", "chat_room_id": ROOM_ID, "model": "test-model"},
        session={"user_id": USER_ID},
    )
    response = asyncio.run(
        use_case.execute(
            request,
            auth_limit_service=object(),
            llm_daily_limit_service=object(),
            chat_generation_service=object(),
        )
    )
    return json.loads(response.body.decode("utf-8"))


class ChatPostRoomTreeReadTestCase(unittest.TestCase):
    def test_one_chat_post_loads_the_room_tree_once(self):
        session = _seeded_session()
        tree_reads: list[str] = []
        use_case, deps = _build_use_case(session, tree_reads)

        payload = _post(use_case)

        self.assertEqual(payload["response"], "assistant reply")
        # 分岐の末尾・LLM履歴・過去ターンの検索結果・応答後の要約で計4回読んでいたものを1回にする。
        # The branch tip, the LLM history, the prior search evidence and the post-reply summary
        # used to be four separate reads of the same tree; they are one read now.
        self.assertEqual(tree_reads, [ROOM_ID])
        # 応答保存後の要約作り直しは、このターンの履歴に応答を足して組み立てる。
        # The post-reply summary rebuild is assembled in memory instead of reading the room back.
        deps.rebuild_room_summary.assert_called_once()
        summary_messages = deps.rebuild_room_summary.call_args.args[1]
        self.assertEqual(
            [entry["role"] for entry in summary_messages],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(summary_messages[-1]["content"], "assistant reply")

    def test_the_single_read_carries_the_history_and_the_search_evidence(self):
        session = _seeded_session()
        tree_reads: list[str] = []
        use_case, _deps = _build_use_case(session, tree_reads)

        _post(use_case)

        tree_columns = session.chat_history_selects[0]
        self.assertEqual(
            tree_columns,
            [
                "id",
                "parent_id",
                "active_child_id",
                "message",
                "sender",
                "message_parts",
                "attached_file_contents",
                "web_search_context",
            ],
        )
        # 表示専用の列（timestamp / attached_file_names）は、この経路では転送しない。
        # Display-only columns are not transferred on this path.
        self.assertNotIn("timestamp", tree_columns)
        self.assertNotIn("attached_file_names", tree_columns)

    def test_branch_tip_lookup_transfers_no_message_bodies(self):
        session = _seeded_session()
        repository = ChatRepository(session)  # type: ignore[arg-type]

        leaf_id = asyncio.run(repository.get_active_leaf_id(ROOM_ID))

        self.assertEqual(leaf_id, 2)
        # get_active_leaf_id は ID しか使わないため、JSONB 列を一切読まない。
        # get_active_leaf_id only needs ids, so it never reads a JSONB column.
        self.assertEqual(session.chat_history_selects, [["id", "parent_id", "active_child_id"]])

class MemoryFactLookupTestCase(unittest.TestCase):
    def test_a_batch_of_facts_is_looked_up_in_one_query(self):
        session = _seeded_session()
        session.memory_facts.append(
            MemoryFact(id=1, user_id=USER_ID, chat_room_id=ROOM_ID, scope="room", fact="Aは青が好き")
        )
        repository = ChatRepository(session)  # type: ignore[arg-type]

        asyncio.run(
            repository.remember_facts(
                ROOM_ID,
                USER_ID,
                ["aは青が好き", "Bは名古屋在住", "Cは月曜が休み"],
                source_message_id=2,
            )
        )

        # fact ごとに SELECT ... FOR UPDATE を撃っていた箇所を1本にまとめた。
        # The per-fact SELECT ... FOR UPDATE is now a single lookup for the whole batch.
        self.assertEqual(len(session.memory_fact_selects), 1)
        self.assertIn("FOR UPDATE", session.memory_fact_selects[0])
        # 既存行は更新され、残り2件だけが新規行になる。
        # The existing row is updated in place and only the two new facts are inserted.
        self.assertEqual(len(session.memory_facts), 3)
        self.assertEqual(session.memory_facts[0].fact, "aは青が好き")
        self.assertEqual(session.memory_facts[0].source_message_id, 2)

    def test_duplicate_facts_in_one_batch_collapse_to_one_row(self):
        session = _seeded_session()
        repository = ChatRepository(session)  # type: ignore[arg-type]

        asyncio.run(repository.remember_facts(ROOM_ID, USER_ID, ["同じ事実", "同じ事実"]))

        self.assertEqual(len(session.memory_facts), 1)


if __name__ == "__main__":
    unittest.main()
