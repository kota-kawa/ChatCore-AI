import unittest

from services import llm
from services.llm_tool_schema import (
    prepare_provider_tools,
    relax_tool_parameters_schema,
)
from services.personal_knowledge import get_personal_knowledge_tool_definition
from services.shared_prompt_lookup import get_shared_prompt_tool_definition
from services.web_search import get_web_search_tool_definition


def _sample_tool():
    """
    テスト用に、拒否につながる制約を一通り含むツール定義を組み立てます。
    Build a tool definition carrying every rejection-causing constraint, for testing.
    """
    return {
        "type": "function",
        "function": {
            "name": "sample_tool",
            "description": "Sample tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "mode": {
                        "type": "string",
                        "description": "Lookup mode.",
                        "enum": ["fast", "deep"],
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["a", "b"]},
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }


class LlmToolSchemaTests(unittest.TestCase):
    # 日本語: プロバイダ側の検証で拒否されうる制約が、渡す直前に落ちることを検証します。
    # English: Verify the constraints a provider can reject on are dropped before handoff.
    def test_prepare_provider_tools_drops_rejectable_constraints(self):
        prepared = prepare_provider_tools([_sample_tool()])
        parameters = prepared[0]["function"]["parameters"]

        self.assertNotIn("required", parameters)
        self.assertNotIn("enum", parameters["properties"]["mode"])
        self.assertNotIn("enum", parameters["properties"]["tags"]["items"])
        self.assertTrue(parameters["additionalProperties"])

    # 日本語: 落とした制約が説明文へ残り、モデルへの誘導が失われないことを検証します。
    # English: Verify the dropped constraints survive in the description, keeping model guidance.
    def test_prepare_provider_tools_moves_constraints_into_descriptions(self):
        prepared = prepare_provider_tools([_sample_tool()])
        properties = prepared[0]["function"]["parameters"]["properties"]

        self.assertIn("Allowed values: fast, deep.", properties["mode"]["description"])
        self.assertIn("Required.", properties["query"]["description"])
        self.assertIn("Search keywords", properties["query"]["description"])

    # 日本語: 元のツール定義を書き換えず、コピーだけを緩めることを検証します。
    # English: Verify the original tool definition is left untouched and only a copy is relaxed.
    def test_prepare_provider_tools_does_not_mutate_the_source_definition(self):
        tool = _sample_tool()

        prepare_provider_tools([tool])

        self.assertEqual(tool, _sample_tool())

    # 日本語: 空リストやNoneでもツール指定を出さないことを検証します。
    # English: Verify no tool payload is produced for an empty or missing tool list.
    def test_prepare_provider_tools_handles_missing_tools(self):
        self.assertEqual(prepare_provider_tools(None), [])
        self.assertEqual(prepare_provider_tools([]), [])

    # 日本語: 実際に配布している全ツール定義が、緩和後に拒否要因を持たないことを検証します。
    # English: Verify none of the shipped tool definitions keep a rejection cause after relaxing.
    def test_shipped_tool_definitions_carry_no_rejectable_constraint(self):
        definitions = [
            get_web_search_tool_definition(),
            get_personal_knowledge_tool_definition(),
            get_shared_prompt_tool_definition(),
        ]

        for tool in prepare_provider_tools(definitions):
            parameters = tool["function"]["parameters"]
            with self.subTest(tool=tool["function"]["name"]):
                self.assertNotIn("required", parameters)
                self.assertIsNot(parameters.get("additionalProperties"), False)
                for name, schema in parameters["properties"].items():
                    self.assertNotIn("enum", schema, msg=name)

    # 日本語: 日本語の検索言語がenumで拒否されず、説明文で案内されることを検証します。
    # English: Verify the Japanese search language is guided by description, not a rejecting enum.
    def test_web_search_language_is_guided_without_a_rejecting_enum(self):
        prepared = prepare_provider_tools([get_web_search_tool_definition()])
        language = prepared[0]["function"]["parameters"]["properties"]["search_language"]

        self.assertNotIn("enum", language)
        self.assertIn("jp", language["description"])

    # 日本語: OpenAI互換の送信引数が、緩めたスキーマだけを載せることを検証します。
    # English: Verify the OpenAI-compatible request payload carries only the relaxed schema.
    def test_chat_completion_tool_kwargs_sends_relaxed_schema(self):
        kwargs = llm._chat_completion_tool_kwargs([_sample_tool()])
        parameters = kwargs["tools"][0]["function"]["parameters"]

        self.assertEqual(kwargs["tool_choice"], "auto")
        self.assertNotIn("required", parameters)
        self.assertNotIn("enum", parameters["properties"]["mode"])

    # 日本語: Claude向けの入力スキーマにも同じ契約が渡ることを検証します。
    # English: Verify the Claude input schema receives the same relaxed contract.
    def test_claude_tools_receive_the_same_relaxed_schema(self):
        claude_tools = llm._prepare_claude_tools([_sample_tool()])
        input_schema = claude_tools[0]["input_schema"]

        self.assertNotIn("required", input_schema)
        self.assertNotIn("enum", input_schema["properties"]["mode"])

    # 日本語: 入れ子のオブジェクト定義でも制約が落ちることを検証します。
    # English: Verify constraints are dropped inside nested object definitions too.
    def test_relax_tool_parameters_schema_walks_nested_objects(self):
        relaxed = relax_tool_parameters_schema(
            {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "object",
                        "properties": {"kind": {"type": "string", "const": "news"}},
                        "required": ["kind"],
                        "additionalProperties": False,
                    }
                },
            }
        )
        nested = relaxed["properties"]["filter"]

        self.assertNotIn("required", nested)
        self.assertTrue(nested["additionalProperties"])
        self.assertNotIn("const", nested["properties"]["kind"])
        self.assertIn("Allowed values: news.", nested["properties"]["kind"]["description"])


if __name__ == "__main__":
    unittest.main()
