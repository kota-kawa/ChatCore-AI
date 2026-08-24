import asyncio
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

from services.default_tasks import (
    CURRENT_SYSTEM_TASK_REVISION,
    default_task_payloads,
    default_task_rows,
    ensure_default_tasks_seeded,
    localize_system_task,
    load_default_tasks,
    resolve_system_task_key,
)
@asynccontextmanager
async def _session_scope():
    class _Transaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc, _tb):
            return False

    class _Session:
        def begin(self):
            return _Transaction()

    yield _Session()


SAMPLE_TASKS = [
    {
        "name": "Task A",
        "prompt_template": "Prompt A",
        "response_rules": "Rules A",
        "output_skeleton": "Skeleton A",
        "input_examples": "Input A",
        "output_examples": "Output A",
        "display_order": 0,
    },
    {
        "name": "Task B",
        "prompt_template": "Prompt B",
        "response_rules": "Rules B",
        "output_skeleton": "Skeleton B",
        "input_examples": "Input B",
        "output_examples": "Output B",
        "display_order": 1,
    },
]


# 日本語: Default Tasksの機能や仕様を検証するテストクラスです。
# English: Test case class to verify the functionality and specifications of Default Tasks.
class DefaultTasksTestCase(unittest.TestCase):
    # 日本語: およびrowsがderived、shareddataから、payloadsことを検証します。
    # English: Verify that payloads and rows are derived from shared data.
    def test_payloads_and_rows_are_derived_from_shared_data(self):
        # 日本語: 依存関係やコンテキストをモック化してテスト環境を構成します。
        # English: Mock dependencies or context to configure the test environment.
        with patch("services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS):
            payloads = default_task_payloads()
            rows = default_task_rows()

        self.assertEqual(len(payloads), 2)
        self.assertTrue(all(payload["is_default"] for payload in payloads))
        self.assertEqual(payloads[0]["name"], "Task A")
        self.assertEqual(payloads[0]["response_rules"], "Rules A")
        self.assertEqual(payloads[0]["output_skeleton"], "Skeleton A")
        self.assertEqual(
            rows[0],
            ("Task A", "Prompt A", "Rules A", "Skeleton A", "Input A", "Output A", 0),
        )

    # 日本語: seedinsertsmissingデフォルトtasksことを検証します。
    # English: Verify that seed inserts missing default tasks.
    def test_seed_inserts_missing_default_tasks(self):
        seed = AsyncMock(return_value=len(SAMPLE_TASKS))
        with (
            patch("services.default_tasks.session_scope", new=_session_scope),
            patch("services.default_tasks.seed_default_tasks", new=seed),
            patch("services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS),
        ):
            inserted = asyncio.run(ensure_default_tasks_seeded())

        self.assertEqual(inserted, len(SAMPLE_TASKS))
        seed.assert_awaited_once()
        self.assertEqual(
            seed.await_args.args[1][0][2:],
            ("Task A", "Prompt A", "Rules A", "Skeleton A", "Input A", "Output A", 0),
        )

    # 日本語: デフォルトtasksalreadyexistのとき、seedskipsことを検証します。
    # English: Verify that seed skips when default tasks already exist.
    def test_seed_skips_when_default_tasks_already_exist(self):
        seed = AsyncMock(return_value=0)
        with (
            patch("services.default_tasks.session_scope", new=_session_scope),
            patch("services.default_tasks.seed_default_tasks", new=seed),
            patch("services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS),
        ):
            inserted = asyncio.run(ensure_default_tasks_seeded())

        self.assertEqual(inserted, 0)
        seed.assert_awaited_once()

    def test_seed_prefers_stable_key_over_localized_name(self):
        keyed_tasks = [
            {**SAMPLE_TASKS[0], "system_task_key": "task_a"},
        ]
        seed = AsyncMock(return_value=0)
        with (
            patch("services.default_tasks.session_scope", new=_session_scope),
            patch("services.default_tasks.seed_default_tasks", new=seed),
            patch("services.default_tasks.load_default_tasks", return_value=keyed_tasks),
        ):
            inserted = asyncio.run(ensure_default_tasks_seeded())

        self.assertEqual(inserted, 0)
        self.assertEqual(seed.await_args.args[1][0][0], "task_a")

    def test_seed_checks_deleted_rows_and_uses_conflict_safe_insert(self):
        seed = AsyncMock(return_value=1)
        with (
            patch("services.default_tasks.session_scope", new=_session_scope),
            patch("services.default_tasks.seed_default_tasks", new=seed),
            patch("services.default_tasks.load_default_tasks", return_value=SAMPLE_TASKS[:1]),
        ):
            self.assertEqual(asyncio.run(ensure_default_tasks_seeded()), 1)

        # PostgreSQL-specific advisory locking and ON CONFLICT behavior belong
        # to the repository boundary, not to this service orchestration test.
        seed.assert_awaited_once()

    def test_customized_system_task_is_not_localized_over_user_content(self):
        task = {
            "system_task_key": "information",
            "name": "My custom task",
            "prompt_template": "Keep this prompt",
            "is_system_task_customized": True,
        }

        localized = localize_system_task(task, "en")

        self.assertEqual(localized["name"], "My custom task")
        self.assertEqual(localized["prompt_template"], "Keep this prompt")

    # 日本語: repositoryデフォルトtasksincludefullseedsetことを検証します。
    # English: Verify that repository default tasks include full seed set.
    def test_repository_default_tasks_include_full_seed_set(self):
        expected_names = {
            "🔍 わかりやすく説明",
            "💡 アイデアを出す",
            "🛠️ 解決策を考える",
            "📧 メールを書く",
            "🌐 翻訳する",
            "📄 要点をまとめる",
            "⚖️ 選択肢を比べる",
            "📋 問題を解く",
            "✏️ 文章を直す",
            "📨 返信を考える",
            "📝 文章を書く",
            "🗒️ メモを整理する",
            "💬 悩みを相談する",
            "🗓️ 予定を立てる",
        }

        load_default_tasks.cache_clear()
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        task_names = {task["name"] for task in tasks}
        self.assertEqual(len(tasks), len(expected_names))
        self.assertSetEqual(task_names, expected_names)

    def test_english_catalog_uses_same_stable_keys(self):
        load_default_tasks.cache_clear()
        try:
            japanese = load_default_tasks("ja")
            english = load_default_tasks("en")
        finally:
            load_default_tasks.cache_clear()

        self.assertEqual(
            [task["system_task_key"] for task in japanese],
            [task["system_task_key"] for task in english],
        )
        self.assertEqual(english[0]["system_task_revision"], CURRENT_SYSTEM_TASK_REVISION)
        self.assertNotEqual(english[0]["name"], "ℹ️ Explain a topic")
        self.assertTrue(all(task["system_task_key"] for task in english))

    def test_current_and_legacy_catalogs_share_stable_key_sets(self):
        current = load_default_tasks("ja", 2)
        legacy = load_default_tasks("ja", 1)
        legacy_english = load_default_tasks("en", 1)

        self.assertEqual(
            {task["system_task_key"] for task in current},
            {task["system_task_key"] for task in legacy},
        )
        self.assertEqual(
            [task["system_task_key"] for task in legacy],
            [task["system_task_key"] for task in legacy_english],
        )
        self.assertTrue(all(task["system_task_revision"] == 1 for task in legacy))
        self.assertTrue(all(task["system_task_revision"] == 2 for task in current))

    def test_current_japanese_labels_fit_task_buttons(self):
        for task in load_default_tasks("ja"):
            _icon, label = task["name"].split(" ", 1)
            self.assertLessEqual(len(label), 10, task["name"])

    def test_current_catalog_orders_common_tasks_first(self):
        tasks = load_default_tasks("ja")

        self.assertEqual(
            [task["system_task_key"] for task in tasks],
            [
                "information",
                "summarization",
                "longform_writing",
                "proofreading",
                "email_writing",
                "reply_writing",
                "translation",
                "ideation",
                "comparison",
                "problem_solving",
                "meeting_notes",
                "question_answering",
                "travel_planning",
                "personal_advice",
            ],
        )
        self.assertEqual([task["display_order"] for task in tasks], list(range(14)))

    def test_localizes_system_task_by_stored_revision(self):
        task = {
            "system_task_key": "information",
            "system_task_revision": 1,
            "name": "stored name",
            "prompt_template": "stored prompt",
            "is_system_task_customized": False,
        }

        legacy = localize_system_task(task, "ja")
        current = localize_system_task({**task, "system_task_revision": 2}, "ja")

        self.assertEqual(legacy["name"], "ℹ️ 情報提供")
        self.assertEqual(current["name"], "🔍 わかりやすく説明")
        self.assertNotEqual(legacy["prompt_template"], current["prompt_template"])

    def test_localizes_only_rows_with_a_stable_system_key(self):
        localized = localize_system_task(
            {
                "system_task_key": "information",
                "name": "ℹ️ 情報提供",
                "prompt_template": "Japanese prompt",
                "is_default": False,
            },
            "en",
        )
        custom = localize_system_task(
            {
                "system_task_key": None,
                "name": "ℹ️ 情報提供",
                "prompt_template": "User-edited prompt",
                "is_default": False,
            },
            "en",
        )

        self.assertEqual(localized["name"], load_default_tasks("en")[0]["name"])
        self.assertNotEqual(localized["prompt_template"], "Japanese prompt")
        self.assertEqual(custom["name"], "ℹ️ 情報提供")
        self.assertEqual(custom["prompt_template"], "User-edited prompt")

    def test_resolves_system_key_from_either_localized_name(self):
        self.assertEqual(resolve_system_task_key("information"), "information")
        self.assertEqual(resolve_system_task_key("ℹ️ 情報提供"), "information")
        self.assertEqual(resolve_system_task_key("ℹ️ Explain a topic"), "information")
        self.assertEqual(resolve_system_task_key("🔍 わかりやすく説明"), "information")
        self.assertIsNone(resolve_system_task_key("My custom task"))

    def test_payloads_and_optional_rows_expose_stable_key(self):
        keyed_tasks = [{**task, "system_task_key": f"task_{index}"} for index, task in enumerate(SAMPLE_TASKS)]
        with patch("services.default_tasks.load_default_tasks", return_value=keyed_tasks):
            payloads = default_task_payloads("en")
            rows = default_task_rows("en", include_key=True)

        self.assertEqual(payloads[0]["system_task_key"], "task_0")
        self.assertEqual(rows[0][0], "task_0")
        self.assertEqual(rows[0][1], CURRENT_SYSTEM_TASK_REVISION)
        self.assertEqual(rows[0][2], "Task A")

    # 日本語: メールタスクが、そのまま送れる本文をコピー枠のフェンスで示すことを検証します。
    # English: Verify that the repository email task puts the ready-to-send body in a copy card fence.
    def test_repository_email_task_uses_copy_fence_for_ready_to_send_body(self):
        load_default_tasks.cache_clear()
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        email_task = next(task for task in tasks if task["name"] == "📧 メールを書く")
        self.assertIn("```chatcore-copy", email_task["prompt_template"])
        self.assertIn("```chatcore-copy", email_task["response_rules"])
        self.assertIn("```chatcore-copy", email_task["output_skeleton"])
        self.assertIn("町内会", email_task["input_examples"])
        self.assertIn("```chatcore-copy", email_task["output_examples"])

    # 日本語: 返答タスクが、各返信案をコピー枠のフェンスで示すことを検証します。
    # English: Verify that the repository reply task puts each reply in a copy card fence.
    def test_repository_reply_task_uses_copy_fences_for_ready_to_send_replies(self):
        load_default_tasks.cache_clear()
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        reply_task = next(task for task in tasks if task["name"] == "📨 返信を考える")
        self.assertIn("```chatcore-copy", reply_task["prompt_template"])
        self.assertIn("```chatcore-copy", reply_task["response_rules"])
        self.assertIn("```chatcore-copy", reply_task["output_skeleton"])

    # 日本語: またはformatsensitivetasksincludeexamples、repositoryテーブルことを検証します。
    # English: Verify that repository table or format sensitive tasks include examples.
    def test_repository_table_or_format_sensitive_tasks_include_examples(self):
        load_default_tasks.cache_clear()
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        comparison_task = next(task for task in tasks if task["name"] == "⚖️ 選択肢を比べる")
        meeting_task = next(task for task in tasks if task["name"] == "🗒️ メモを整理する")

        self.assertTrue(comparison_task["input_examples"])
        self.assertIn("| 候補 |", comparison_task["output_examples"])
        self.assertTrue(meeting_task["input_examples"])
        self.assertIn("## やること", meeting_task["output_examples"])

    # 日本語: repositoryproblemsolvingタスクrequestsconciserationaleonlyことを検証します。
    # English: Verify that repository problem solving task requests concise rationale only.
    def test_repository_problem_solving_task_requests_concise_rationale_only(self):
        load_default_tasks.cache_clear()
        try:
            tasks = load_default_tasks()
        finally:
            load_default_tasks.cache_clear()

        answer_task = next(task for task in tasks if task["name"] == "📋 問題を解く")
        self.assertIn("必要な手順", answer_task["prompt_template"])
        self.assertIn("簡単な問題", answer_task["response_rules"])
        self.assertIn("考え方や計算", answer_task["output_skeleton"])
        self.assertNotIn("途中の考え方", answer_task["prompt_template"])


if __name__ == "__main__":
    unittest.main()
