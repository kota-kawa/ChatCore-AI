"""The generated native-UI prompt mirrors the code-free Pydantic contract."""

import unittest
from typing import get_args

from services.structured_ui_models import StructuredUiV1, UiExpression
from services.structured_ui_prompt import STRUCTURED_UI_EXECUTION_CONTRACT


class StructuredUiPromptTests(unittest.TestCase):
    def test_prompt_names_required_fields_and_all_supported_expression_operators(self):
        prompt = STRUCTURED_UI_EXECUTION_CONTRACT
        self.assertIn("one or more independent ```chatcore-ui fenced JSON blocks", prompt)
        self.assertIn("non-empty `fallback_text`", prompt)
        self.assertIn("flat array", prompt)

        for field_name in StructuredUiV1.model_fields:
            with self.subTest(field=field_name):
                self.assertIn(f"`{field_name}`", prompt)
        for operation in get_args(UiExpression.model_fields["op"].annotation):
            with self.subTest(operation=operation):
                self.assertIn(f"`{operation}`", prompt)

    def test_prompt_preserves_surrounding_prose_and_prevents_duplicate_choice_questions(self):
        prompt = STRUCTURED_UI_EXECUTION_CONTRACT
        for requirement in (
            "do not delete it, move it into a block",
            "do not repeat that question in prose",
            "second `chatcore-buttons` block for the same choice",
            "In NONE mode",
            "All IDs",
            "begin with an ASCII letter",
            "300 nodes total across the entire reply",
            "numeric offset added to the current zero-based sample index",
            "A static table alone does not fulfill an adjustable-calculation request",
            "Emit each top-level key exactly once",
            "do not append another object",
            "`images` and `sources` are server-managed",
            "omit them",
            "put the requested values in a static `table`",
            "such as three default comparison points",
            "do not recreate those rows with states, expressions, or a series",
            "Keep that table and its adjustable calculation in one block",
            "Use one dynamic calculation path",
            "the smallest expression graph needed for the result",
            "one chart with a state-dependent series",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, prompt)

    def test_prompt_does_not_embed_a_large_calculator_example(self):
        prompt = STRUCTURED_UI_EXECUTION_CONTRACT
        self.assertNotIn("Working loan example", prompt)
        self.assertNotIn("sample_payment", prompt)
        self.assertNotIn("payment_curve", prompt)

    def test_prompt_restricts_series_index_and_expression_syntax(self):
        prompt = STRUCTURED_UI_EXECUTION_CONTRACT
        self.assertIn("literal integer count from 0 to 500", prompt)
        self.assertIn("arg 1 is an expression reference", prompt)
        self.assertIn("index values may appear only in that referenced series-body expression", prompt)
        self.assertIn("No JavaScript, arbitrary code, expression strings", prompt)


if __name__ == "__main__":
    unittest.main()
