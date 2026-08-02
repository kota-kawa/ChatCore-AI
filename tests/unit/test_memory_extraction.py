import unittest
from unittest.mock import patch

from services.llm import LIGHTWEIGHT_TASK_MODEL, LlmConfigurationError
from services.memory_extraction import MAX_MEMORY_FACTS_PER_MESSAGE, extract_memory_facts


# 日本語: 記憶ファクト抽出が言語に依存せず、失敗時も誤った事実を残さないことを検証するクラス。
# English: Test class asserting memory fact extraction is language-agnostic and
# never leaves a wrong fact behind when the model call fails.
class MemoryExtractionTestCase(unittest.TestCase):
    # 日本語: 軽量モデルの JSON 応答から事実が抽出されることを検証します。
    # English: Verify facts are read from the lightweight model's JSON response.
    def test_extracts_facts_from_model_response(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            return_value={"facts": ["ユーザーの名前は川越である", "回答は箇条書きを好む"]},
        ) as mocked:
            facts = extract_memory_facts("私の名前は川越です。今後は箇条書きでお願いします。")

        self.assertEqual(facts, ["ユーザーの名前は川越である", "回答は箇条書きを好む"])
        # 単純な処理なので軽量モデルを使うこと
        # A simple extraction task must use the lightweight model
        self.assertEqual(mocked.call_args.args[1], LIGHTWEIGHT_TASK_MODEL)

    # 日本語: 日本語・英語以外の言語でも同じ経路で抽出できることを検証します。
    # English: Verify the same path works for languages beyond Japanese and English.
    def test_extraction_is_language_agnostic(self):
        samples = {
            "Je m'appelle Camille.": "L'utilisateur s'appelle Camille",
            "제 이름은 지훈입니다.": "사용자의 이름은 지훈이다",
            "Meine Antworten bitte immer auf Deutsch.": "Der Nutzer möchte Antworten auf Deutsch",
        }

        for message, expected_fact in samples.items():
            with self.subTest(message=message):
                with patch(
                    "services.memory_extraction.get_llm_json_response",
                    return_value={"facts": [expected_fact]},
                ):
                    self.assertEqual(extract_memory_facts(message), [expected_fact])

    # 日本語: 恒久的な事実がない場合に空リストを返すことを検証します。
    # English: Verify an empty list is returned when nothing durable was found.
    def test_returns_empty_when_nothing_durable(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            return_value={"facts": []},
        ):
            self.assertEqual(extract_memory_facts("今後はこの方針で進めることになりました。"), [])

    # 日本語: モデル呼び出しが失敗しても、誤った事実を保存しないことを検証します。
    # English: Verify a failed model call stores nothing rather than a wrong fact.
    def test_returns_empty_when_model_is_unavailable(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            side_effect=LlmConfigurationError("no key"),
        ):
            self.assertEqual(extract_memory_facts("私の名前は川越です。"), [])

    # 日本語: 解釈できない応答を事実として扱わないことを検証します。
    # English: Verify malformed responses are not treated as facts.
    def test_ignores_malformed_responses(self):
        for payload in ("not json", {"facts": "not a list"}, {"other": ["x"]}, None):
            with self.subTest(payload=payload):
                with patch(
                    "services.memory_extraction.get_llm_json_response",
                    return_value=payload,
                ):
                    self.assertEqual(extract_memory_facts("私の名前は川越です。"), [])

    # 日本語: 文字列で返された JSON も解釈できることを検証します。
    # English: Verify a JSON payload returned as a string is still parsed.
    def test_parses_json_returned_as_text(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            return_value='{"facts": ["The user prefers concise answers"]}',
        ):
            self.assertEqual(
                extract_memory_facts("I prefer concise answers."),
                ["The user prefers concise answers"],
            )

    # 日本語: 重複除去と件数上限が効くことを検証します。
    # English: Verify duplicates are removed and the per-message cap is enforced.
    def test_deduplicates_and_caps_facts(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            return_value={"facts": ["同じ事実", "同じ事実"] + [f"事実{i}" for i in range(10)]},
        ):
            facts = extract_memory_facts("色々な情報です。")

        self.assertEqual(len(facts), MAX_MEMORY_FACTS_PER_MESSAGE)
        self.assertEqual(len(set(facts)), len(facts))

    # 日本語: 保存形式の HTML が抽出器へ渡る前に平文化されることを検証します。
    # English: Verify stored HTML is reduced to plain text before reaching the extractor.
    def test_strips_stored_html_before_extraction(self):
        with patch(
            "services.memory_extraction.get_llm_json_response",
            return_value={"facts": []},
        ) as mocked:
            extract_memory_facts("1行目<br>2行目 &amp; 続き")

        sent = mocked.call_args.args[0][1]["content"]
        self.assertIn("1行目\n2行目", sent)
        self.assertNotIn("<br>", sent)

    # 日本語: 空メッセージではモデルを呼ばないことを検証します。
    # English: Verify the model is not called for an empty message.
    def test_does_not_call_model_for_empty_message(self):
        with patch("services.memory_extraction.get_llm_json_response") as mocked:
            self.assertEqual(extract_memory_facts("   "), [])

        mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
