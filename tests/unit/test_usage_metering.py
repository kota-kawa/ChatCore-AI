"""API 使用量の計測 (料金換算、計上先の決定と伝播、プロバイダ別の使用量記録、日次 upsert) のテスト。

Tests for API usage metering: pricing, billing-subject resolution and propagation, per-provider usage recording, and the daily upsert.
"""

import asyncio
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from services import llm
from services.async_utils import iterate_blocking, run_blocking
from services.background_executor import submit_background_task
from services.repositories.usage_repository import UsageIncrement, UsageRepository
from services.usage_metering import (
    BRAVE_WEB_SEARCH_RESOURCE,
    record_token_usage,
    record_web_search_request,
    set_usage_sink,
    usage_date,
)
from services.usage_pricing import (
    BRAVE_WEB_SEARCH_REQUEST_NANO_USD,
    FALLBACK_TOKEN_PRICE,
    token_cost_nano_usd,
)
from services.usage_subject import (
    SYSTEM_USAGE_SUBJECT,
    UsageSubjectMiddleware,
    _usage_subject_var,
    current_usage_subject,
    guest_usage_subject,
    resolve_usage_subject,
    user_usage_subject,
)


# ASGI の HTTP スコープを最小限で組み立てるヘルパー。session を渡したときだけ scope に入れる。
# Helper that builds a minimal ASGI HTTP scope; the session is included only when given.
def _http_scope(*, session=None, client=("203.0.113.7", 1234)):
    scope = {"type": "http", "headers": [], "client": client, "path": "/", "method": "GET"}
    if session is not None:
        scope["session"] = session
    return scope


# 使用量の書き込み先 (sink) をテスト内のリストに差し替え、DB へ書かずに記録内容を検査できるようにする。終了時に元の no-op へ戻す。
# Swaps the usage sink for an in-test list so records can be inspected without touching the DB; restored to a no-op on cleanup.
class _RecordingSinkMixin:
    def setUp(self):
        super().setUp()
        self.records: list[UsageIncrement] = []
        set_usage_sink(self.records.append)
        self.addCleanup(set_usage_sink, lambda _increment: None)


# トークン数から料金 (nano USD) への換算を確かめる。
# Checks the conversion from token counts to cost in nano USD.
class UsagePricingTests(unittest.TestCase):
    def test_cost_uses_published_per_million_prices(self):
        # GPT-6 Luna の単価: 入力 $0.10、キャッシュ入力 $0.01、出力 $0.50 (いずれも 100 万トークンあたり)。
        # GPT-6 Luna: $0.10 in / $0.01 cached in / $0.50 out per 1M tokens.
        cost = token_cost_nano_usd(
            "gpt-6-luna",
            input_tokens=1_000_000,
            cached_input_tokens=400_000,
            output_tokens=1_000_000,
        )
        self.assertEqual(cost, 600_000 * 100 + 400_000 * 10 + 1_000_000 * 500)

    def test_cached_input_without_a_discount_is_billed_at_the_input_rate(self):
        with_cache = token_cost_nano_usd(
            "qwen/qwen3.8-27b", input_tokens=1000, cached_input_tokens=1000, output_tokens=0
        )
        without_cache = token_cost_nano_usd("qwen/qwen3.8-27b", input_tokens=1000, output_tokens=0)
        self.assertEqual(with_cache, without_cache)

    # 単価表に無いモデルは過小計上を避けるため最も高い単価 (FALLBACK_TOKEN_PRICE) で数え、警告を出す。
    # A model missing from the price table is billed at the highest rate (FALLBACK_TOKEN_PRICE) to avoid
    # under-counting, and a warning is logged.
    def test_unknown_model_is_billed_at_the_most_expensive_rate(self):
        with self.assertLogs("services.usage_pricing", level="WARNING"):
            cost = token_cost_nano_usd("mystery-model", input_tokens=10, output_tokens=10)
        self.assertEqual(cost, 10 * FALLBACK_TOKEN_PRICE.input + 10 * FALLBACK_TOKEN_PRICE.output)

    def test_every_selectable_chat_model_has_a_price(self):
        for model_name in (
            llm.GPT_6_LUNA_MODEL,
            llm.QWEN_3_8_27B_MODEL,
            llm.GPT_OSS_120B_MODEL,
            llm.GPT_OSS_20B_MODEL,
            llm.CLAUDE_HAIKU_4_5_MODEL,
            llm.CLAUDE_HAIKU_5_5_MODEL,
        ):
            with self.subTest(model_name=model_name), self.assertNoLogs(
                "services.usage_pricing", level="WARNING"
            ):
                token_cost_nano_usd(model_name, input_tokens=1, output_tokens=1)

    # Haiku 5.5 は入力が 100,000 トークンを超えると単価が 5 倍の層になる。層の判定にはキャッシュ分も含めた入力の合計を使う。
    # Haiku 5.5 moves to a 5x price tier once input exceeds 100,000 tokens; the tier is decided on total input including cached tokens.
    def test_haiku_5_5_price_tier_includes_all_cached_input(self):
        for total_input in (99_999, 100_000, 100_001):
            with self.subTest(total_input=total_input):
                cached, written, output = 60_000, 20_000, 1_000
                factor = 5 if total_input > 100_000 else 1
                cost = token_cost_nano_usd(
                    llm.CLAUDE_HAIKU_5_5_MODEL,
                    input_tokens=total_input,
                    cached_input_tokens=cached,
                    cache_write_input_tokens=written,
                    output_tokens=output,
                )
                self.assertEqual(cost, factor * (
                    (total_input - cached - written) * 100 + cached * 10 + written * 125 + output * 500
                ))

    # プロバイダ形式の使用量 (キャッシュ読み出し・書き込みを別項目で持つ) を合計して層を決め、長い文脈の単価で記録する。
    # Provider-shaped usage (cache reads and writes reported separately) is summed to pick the tier, and recorded at the long-context rate.
    def test_haiku_5_5_provider_usage_selects_long_context_tier(self):
        from services.llm_usage import record_claude_usage

        records = []
        set_usage_sink(records.append)
        self.addCleanup(set_usage_sink, lambda _increment: None)
        record_claude_usage(llm.CLAUDE_HAIKU_5_5_MODEL, {
            "input_tokens": 20_001,
            "cache_read_input_tokens": 60_000,
            "cache_creation_input_tokens": 20_000,
            "output_tokens": 1_000,
        })
        self.assertEqual(records[0].cost_nano_usd, 20_001 * 500 + 60_000 * 50 + 20_000 * 625 + 1_000 * 2_500)


# 課金日の区切りは日本時間の 0 時 (UTC の 15:00)。
# The billing day rolls over at midnight Japan time (15:00 UTC).
class UsageDateTests(unittest.TestCase):
    def test_day_boundary_is_midnight_japan_time(self):
        self.assertEqual(usage_date(datetime(2026, 9, 23, 14, 59, tzinfo=UTC)), date(2026, 9, 23))
        self.assertEqual(usage_date(datetime(2026, 9, 23, 15, 0, tzinfo=UTC)), date(2026, 9, 24))


# リクエストから計上先を決めるルール: ログイン済みはユーザー、ゲストは接続元 IP のハッシュ、セッションなしは system。
# Rules for choosing the billing subject: signed-in users by id, guests by a hash of the client IP, sessionless requests as system.
class UsageSubjectTests(unittest.TestCase):
    def test_signed_in_user_is_the_subject(self):
        self.assertEqual(resolve_usage_subject(_http_scope(session={"user_id": 42})), "user:42")

    def test_guest_is_identified_by_a_hash_of_the_client_ip(self):
        subject = resolve_usage_subject(_http_scope(session={}))
        self.assertEqual(subject, guest_usage_subject("203.0.113.7"))
        self.assertNotIn("203.0.113.7", subject)

    def test_request_without_a_session_is_billed_to_the_system(self):
        self.assertEqual(resolve_usage_subject(_http_scope()), SYSTEM_USAGE_SUBJECT)

    def test_middleware_binds_the_subject_only_for_the_request(self):
        seen = []

        async def app(scope, receive, send):
            seen.append(current_usage_subject())

        middleware = UsageSubjectMiddleware(app)
        asyncio.run(middleware(_http_scope(session={"user_id": 7}), None, None))

        self.assertEqual(seen, ["user:7"])
        self.assertEqual(current_usage_subject(), SYSTEM_USAGE_SUBJECT)


# 計上先 (ContextVar) が、ワーカースレッドやバックグラウンドタスクへコンテキストごと引き継がれることを確かめる。
# Checks the billing subject (a ContextVar) is carried into worker threads and background tasks along with the context.
class UsageSubjectPropagationTests(unittest.TestCase):
    def setUp(self):
        token = _usage_subject_var.set(user_usage_subject(5))
        self.addCleanup(_usage_subject_var.reset, token)

    def test_run_blocking_carries_the_subject_to_the_worker_thread(self):
        self.assertEqual(asyncio.run(run_blocking(current_usage_subject)), "user:5")

    def test_iterate_blocking_carries_the_subject_to_each_step(self):
        def subjects():
            yield current_usage_subject()
            yield current_usage_subject()

        async def collect():
            return [item async for item in iterate_blocking(subjects())]

        self.assertEqual(asyncio.run(collect()), ["user:5", "user:5"])

    def test_background_task_carries_the_subject(self):
        self.assertEqual(submit_background_task(current_usage_subject).result(timeout=5), "user:5")

    # 専用の 1 スレッドのプールに差し替えてスケジュールし、終了を待つ。他のテストとスレッドを共有しないため。
    # Schedules work on a dedicated single-thread pool and waits for it, so the test does not share threads with others.
    def _run_on_fresh_background_pool(self, schedule):
        executor = ThreadPoolExecutor(max_workers=1)
        with patch("services.background_executor.get_background_executor", return_value=executor):
            schedule()
        executor.shutdown(wait=True)

    def test_memo_embedding_is_billed_to_the_requesting_user(self):
        from services import memo_embedding_service

        seen = []

        def fake_embedding(_text):
            seen.append(current_usage_subject())

        with (
            patch.object(memo_embedding_service, "embeddings_available", return_value=True),
            patch.object(memo_embedding_service, "generate_embedding", side_effect=fake_embedding),
        ):
            self._run_on_fresh_background_pool(
                lambda: memo_embedding_service.schedule_embedding(1, "title", "body")
            )

        self.assertEqual(seen, ["user:5"])

    def test_context_extraction_is_billed_to_the_requesting_user(self):
        from services.context_vault_extraction import schedule_context_extraction

        seen = []

        def extractor(*_args, **_kwargs):
            seen.append(current_usage_subject())
            return []

        self._run_on_fresh_background_pool(
            lambda: schedule_context_extraction(
                5,
                room_id="room-1",
                assistant_message_id=1,
                user_message="message",
                assistant_response="response",
                extractor=extractor,
                store_candidates=MagicMock(),
            )
        )

        self.assertEqual(seen, ["user:5"])


# record_* が現在の計上先へ料金を付けて記録し、sink の失敗が呼び出し元へ伝わらないことを確かめる。
# Checks that record_* attributes costs to the current subject and that a failing sink never reaches the caller.
class UsageMeteringTests(_RecordingSinkMixin, unittest.TestCase):
    def test_token_usage_is_costed_and_attributed_to_the_current_subject(self):
        token = _usage_subject_var.set("user:9")
        self.addCleanup(_usage_subject_var.reset, token)

        record_token_usage("gpt-6-luna", input_tokens=2000, cached_input_tokens=500, output_tokens=300)

        [record] = self.records
        self.assertEqual(record.subject_key, "user:9")
        self.assertEqual(record.resource, "gpt-6-luna")
        self.assertEqual(record.cost_nano_usd, 1500 * 100 + 500 * 10 + 300 * 500)
        self.assertEqual(
            (record.input_tokens, record.cached_input_tokens, record.output_tokens, record.request_count),
            (2000, 500, 300, 1),
        )

    def test_web_search_request_is_billed_per_request(self):
        record_web_search_request()

        [record] = self.records
        self.assertEqual(record.resource, BRAVE_WEB_SEARCH_RESOURCE)
        self.assertEqual(record.cost_nano_usd, BRAVE_WEB_SEARCH_REQUEST_NANO_USD)
        self.assertEqual(record.subject_key, SYSTEM_USAGE_SUBJECT)

    def test_a_failing_sink_never_breaks_the_caller(self):
        def broken(_increment):
            raise RuntimeError("database down")

        set_usage_sink(broken)
        with self.assertLogs("services.usage_metering", level="ERROR"):
            record_token_usage("gpt-6-luna", input_tokens=1, output_tokens=1)


# プロバイダのストリーム応答を模したリスト。close() が呼ばれたかを記録する。
# A list standing in for a provider streaming response; records whether close() was called.
class _Stream(list):
    def __init__(self, *items):
        super().__init__(items)
        self.closed = False

    def close(self):
        self.closed = True


# Groq / Claude / OpenAI の各クライアントをモックし、ストリーミング・非ストリーミングの応答から使用量が記録されることを確かめる。
# Mocks the Groq / Claude / OpenAI clients and checks usage is recorded from both streaming and non-streaming responses.
class ProviderUsageMeteringTests(_RecordingSinkMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.messages = [{"role": "user", "content": "hello"}]

    def test_chat_completion_stream_requests_and_records_final_usage(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _Stream(
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(
                    prompt_tokens=120,
                    completion_tokens=30,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=100),
                ),
            ),
        )
        with patch.object(llm, "groq_client", client):
            self.assertEqual(list(llm.get_groq_response_stream(self.messages, llm.GPT_OSS_120B_MODEL)), ["hi"])

        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["stream_options"], {"include_usage": True}
        )
        [record] = self.records
        self.assertEqual((record.input_tokens, record.cached_input_tokens, record.output_tokens), (120, 100, 30))

    def test_groq_usage_extension_is_read_when_usage_is_missing(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _Stream(
            SimpleNamespace(
                choices=[],
                usage=None,
                x_groq={"usage": {"prompt_tokens": 50, "completion_tokens": 5}},
            ),
        )
        with patch.object(llm, "groq_client", client):
            list(llm.get_groq_response_stream(self.messages, llm.GPT_OSS_120B_MODEL))

        [record] = self.records
        self.assertEqual((record.input_tokens, record.output_tokens), (50, 5))

    # 使用量が届く前にストリームを閉じた場合は、送受信した文字量からの推定値で記録する。
    # If the stream is closed before usage arrives, the usage is recorded from an estimate based on the text exchanged.
    def test_stream_closed_before_usage_arrives_is_recorded_from_an_estimate(self):
        client = MagicMock()
        stream = _Stream(
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="partial"), finish_reason=None)],
                usage=None,
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=" more"), finish_reason=None)],
                usage=None,
            ),
        )
        client.chat.completions.create.return_value = stream
        with patch.object(llm, "groq_client", client):
            generator = llm.get_groq_response_stream(self.messages, llm.GPT_OSS_120B_MODEL)
            self.assertEqual(next(generator), "partial")
            generator.close()

        self.assertTrue(stream.closed)
        [record] = self.records
        self.assertGreater(record.input_tokens, 0)
        self.assertGreater(record.output_tokens, 0)
        self.assertGreater(record.cost_nano_usd, 0)

    # リクエストが始まる前に失敗したときは課金が発生していないので、記録しない。
    # A request that failed before starting incurred no charge, so nothing is recorded.
    def test_failed_request_that_never_started_is_not_recorded(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("connection refused")
        with (
            patch.object(llm, "groq_client", client),
            self.assertRaises(llm.LlmServiceError),
            self.assertLogs("services.llm", level="WARNING"),
        ):
            list(llm.get_groq_response_stream(self.messages, llm.GPT_OSS_120B_MODEL))

        self.assertEqual(self.records, [])

    # Claude は message_start に入力側、message_delta に出力側の使用量を分けて返すので、両方を合算して記録する。
    # 入力にはキャッシュ読み出し分を含める。
    # Claude reports input usage in message_start and output usage in message_delta, so both are combined; input includes cache reads.
    def test_claude_stream_combines_start_and_delta_usage(self):
        client = MagicMock()
        client.messages.create.return_value = _Stream(
            SimpleNamespace(
                type="message_start",
                message=SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=40,
                        cache_creation_input_tokens=0,
                        cache_read_input_tokens=60,
                        output_tokens=1,
                    )
                ),
            ),
            SimpleNamespace(
                type="content_block_delta",
                index=0,
                delta=SimpleNamespace(type="text_delta", text="ok"),
            ),
            SimpleNamespace(
                type="message_delta",
                delta=SimpleNamespace(stop_reason="end_turn"),
                usage=SimpleNamespace(output_tokens=25),
            ),
        )
        with patch.object(llm, "claude_client", client):
            list(llm.get_claude_response_stream(self.messages, llm.CLAUDE_HAIKU_4_5_MODEL))

        [record] = self.records
        self.assertEqual((record.input_tokens, record.cached_input_tokens, record.output_tokens), (100, 60, 25))

    def test_responses_stream_records_the_completed_usage(self):
        client = MagicMock()
        stream = _Stream(
            SimpleNamespace(type="response.output_text.delta", delta="done"),
            SimpleNamespace(
                type="response.completed",
                response=SimpleNamespace(
                    usage=SimpleNamespace(
                        input_tokens=300,
                        output_tokens=40,
                        input_tokens_details=SimpleNamespace(cached_tokens=200),
                    )
                ),
            ),
        )
        client.responses.stream.return_value.__enter__.return_value = stream
        with patch.object(llm, "openai_client", client):
            self.assertEqual(list(llm.get_openai_response_stream(self.messages, llm.GPT_6_LUNA_MODEL)), ["done"])

        [record] = self.records
        self.assertEqual((record.input_tokens, record.cached_input_tokens, record.output_tokens), (300, 200, 40))
        self.assertEqual(record.cost_nano_usd, 100 * 100 + 200 * 10 + 40 * 500)

    def test_non_streaming_response_records_reported_usage(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2, prompt_tokens_details=None),
        )
        with patch.object(llm, "groq_client", client):
            self.assertEqual(llm.get_groq_response(self.messages, llm.GPT_OSS_20B_MODEL), "ok")

        [record] = self.records
        self.assertEqual((record.resource, record.input_tokens, record.output_tokens), (llm.GPT_OSS_20B_MODEL, 10, 2))


# 日次の使用量テーブルへの加算が、1 回の upsert (ON CONFLICT DO UPDATE) で行われることを、コンパイルした SQL で確かめる。
# Checks via compiled SQL that the daily usage table is incremented with a single upsert (ON CONFLICT DO UPDATE).
class UsageRepositoryTests(unittest.TestCase):
    def test_add_usage_accumulates_with_a_single_upsert(self):
        session = MagicMock()
        captured = []

        async def execute(statement):
            captured.append(statement)

        session.execute = execute
        asyncio.run(
            UsageRepository().add_usage(
                session,
                UsageIncrement(
                    subject_key="user:1",
                    usage_date=date(2026, 9, 23),
                    resource="gpt-6-luna",
                    cost_nano_usd=123,
                    input_tokens=10,
                    output_tokens=2,
                ),
            )
        )

        [statement] = captured
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("INSERT INTO api_usage_daily", sql)
        self.assertIn("ON CONFLICT (subject_key, usage_date, resource) DO UPDATE", sql)
        self.assertIn("cost_nano_usd = (api_usage_daily.cost_nano_usd + excluded.cost_nano_usd)", sql)
        self.assertIn("request_count = (api_usage_daily.request_count + excluded.request_count)", sql)


if __name__ == "__main__":
    unittest.main()
