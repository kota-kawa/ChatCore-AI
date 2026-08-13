import json
import unittest
from unittest.mock import Mock, patch

from services.chat_generation import ChatGenerationJob
from services.shared_prompt_lookup import (
    SHARED_PROMPT_TOOL_NAME,
    SharedPromptResult,
    build_shared_prompt_tool_payload,
    search_shared_prompts,
)


# 日本語: SharedContentService の検索結果を模した最小オブジェクト。
# English: Minimal stand-ins for what SharedContentService returns.
class _FakeSummary:
    def __init__(self, prompt_id, title):
        self.prompt_id = prompt_id
        self.title = title
        self.category = "business"
        self.author = "ユーザー"
        self.content_format = "prompt"
        self.snippet = "丁寧なメール返信を書くためのプロンプト"
        self.public_url = f"https://example.test/shared/prompt/{prompt_id}"


class _FakePage:
    def __init__(self, items):
        self.items = items


class _FakeDetail:
    def __init__(self, content, skill_markdown=""):
        self.content = content
        self.skill_markdown = skill_markdown


class SharedPromptSearchTestCase(unittest.TestCase):
    def _service(self, *, page, detail=None, detail_side_effect=None):
        service = Mock()
        service.list_public_content.return_value = page
        if detail_side_effect is not None:
            service.get_public_content.side_effect = detail_side_effect
        else:
            service.get_public_content.return_value = detail
        return service

    # 日本語: 上位ヒットは本文まで読み込み、公開URLも一緒に返します。
    # English: Top hits are expanded to their body and carry the public URL.
    def test_returns_hits_with_full_body_for_top_results(self):
        service = self._service(
            page=_FakePage([_FakeSummary(11, "丁寧なメール返信")]),
            detail=_FakeDetail("本文テンプレート"),
        )

        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = search_shared_prompts("  メール 返信  ")

        self.assertEqual(result.query, "メール 返信")
        self.assertEqual(result.prompts[0]["title"], "丁寧なメール返信")
        self.assertEqual(result.prompts[0]["content"], "本文テンプレート")
        self.assertEqual(result.prompts[0]["public_url"], "https://example.test/shared/prompt/11")
        service.list_public_content.assert_called_once()

    # 日本語: SKILL投稿は content が空でも、Markdown本文を根拠として渡します。
    # English: SKILL posts have no plain content, so the markdown body is used instead.
    def test_uses_skill_markdown_when_content_is_empty(self):
        service = self._service(
            page=_FakePage([_FakeSummary(12, "レビュー手順")]),
            detail=_FakeDetail("", skill_markdown="# 手順\n1. 差分を読む"),
        )

        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = search_shared_prompts("レビュー")

        self.assertEqual(result.prompts[0]["content"], "# 手順\n1. 差分を読む")

    # 日本語: 本文が読めなくても、スニペットだけで紹介できるようヒットは残します。
    # English: A failed body load still keeps the hit so the snippet can be used.
    def test_keeps_the_hit_when_the_body_cannot_be_loaded(self):
        service = self._service(
            page=_FakePage([_FakeSummary(13, "議事録テンプレ")]),
            detail_side_effect=RuntimeError("db down"),
        )

        with patch("services.shared_prompt_lookup._service", return_value=service):
            result = search_shared_prompts("議事録")

        self.assertEqual(result.prompts[0]["title"], "議事録テンプレ")
        self.assertNotIn("content", result.prompts[0])

    # 日本語: 検索自体が落ちても例外を投げず、ヒット0件として回答を続けさせます。
    # English: A failing search returns no hits instead of raising, so the answer continues.
    def test_failed_search_returns_no_hits(self):
        with patch("services.shared_prompt_lookup._service", side_effect=RuntimeError("boom")):
            result = search_shared_prompts("メール")

        self.assertFalse(result.has_hits)

    # 日本語: 空クエリでは検索そのものを行いません。
    # English: An empty query performs no lookup at all.
    def test_blank_query_skips_the_lookup(self):
        with patch("services.shared_prompt_lookup._service") as service_factory:
            result = search_shared_prompts("   ")

        service_factory.assert_not_called()
        self.assertFalse(result.has_hits)

    # 日本語: ヒット0件は「無かった」と明示し、捏造させないためのメッセージを返します。
    # English: Zero hits must be reported explicitly so the model does not invent a prompt.
    def test_empty_payload_tells_the_model_nothing_matched(self):
        payload = build_shared_prompt_tool_payload(SharedPromptResult(query="メール"))

        self.assertEqual(payload["status"], "no_results")
        self.assertEqual(payload["prompts"], [])


class SharedPromptToolCallTestCase(unittest.TestCase):
    def _build_job(self, search):
        events = []
        job = ChatGenerationJob(
            conversation_messages=[{"role": "user", "content": "丁寧な断りメールを書きたい"}],
            model="test-model",
            persist_response=lambda response, **kwargs: None,
            on_event=lambda event: events.append((event.event, event.payload)),
            shared_prompt_search=search,
        )
        return job, events

    @staticmethod
    def _run(job, tool_call, *, current_messages, step_count, max_steps):
        return job._run_lookup_tool_call(
            tool_call,
            tool_name=SHARED_PROMPT_TOOL_NAME,
            search=job._shared_prompt_search,
            event_prefix="shared_prompt_search",
            result_counts=("prompt_count",),
            failure_log_message="Shared prompt search via tool call failed.",
            failure_tool_message="Shared prompt search failed.",
            current_messages=current_messages,
            step_count=step_count,
            max_steps=max_steps,
        )

    @staticmethod
    def _tool_call(arguments):
        return {
            "id": "call_1",
            "type": "function",
            "function": {"name": SHARED_PROMPT_TOOL_NAME, "arguments": json.dumps(arguments)},
        }

    # 日本語: 検索結果はツール結果メッセージとして会話へ戻り、件数付きのイベントも出ます。
    # English: Results return as a tool message and the completion event carries the hit count.
    def test_tool_call_appends_results_and_publishes_steps(self):
        payload = {"status": "ok", "prompt_count": 3, "prompts": []}
        job, events = self._build_job(lambda query: payload)
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "断り メール"}),
            current_messages=messages,
            step_count=1,
            max_steps=8,
        )

        self.assertEqual(next_step, 2)
        self.assertEqual(messages[0]["role"], "tool")
        self.assertEqual(json.loads(messages[0]["content"])["prompt_count"], 3)
        self.assertEqual(
            [name for name, _ in events],
            ["shared_prompt_search_started", "shared_prompt_search_completed"],
        )
        self.assertEqual(events[1][1]["prompt_count"], 3)

    # 日本語: 検索が例外を投げても生成は続き、失敗をイベントとツール結果で伝えます。
    # English: A failing lookup keeps generation alive and reports the failure both ways.
    def test_failed_lookup_reports_and_continues(self):
        def _raise(query):
            raise RuntimeError("search exploded")

        job, events = self._build_job(_raise)
        messages = []

        next_step = self._run(
            job,
            self._tool_call({"query": "メール"}),
            current_messages=messages,
            step_count=1,
            max_steps=8,
        )

        self.assertEqual(next_step, 2)
        self.assertEqual(json.loads(messages[0]["content"])["status"], "failed")
        self.assertEqual(
            [name for name, _ in events],
            ["shared_prompt_search_started", "shared_prompt_search_failed"],
        )


if __name__ == "__main__":
    unittest.main()
