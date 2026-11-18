"""Native UI contract, bounded incremental parsing and legacy preservation."""

import copy
import json
import unittest
from unittest.mock import patch

from services.generative_ui import (
    build_message_parts_context,
    decode_message_parts,
    encode_message_parts,
    normalize_response_with_artifact_retry,
    normalize_response_with_artifacts,
)
from services.message_parts_display import normalize_message_parts_for_display
from services.structured_ui import StructuredUiStream, project_ui_payload, split_structured_ui, validate_structured_ui


def document():
    return {
        "version": 1,
        "id": "comparison",
        "fallback_text": "A: 10, B: 20",
        "root_id": "root",
        "nodes": [
            {"id": "root", "type": "card", "children": ["a", "b"]},
            {"id": "a", "type": "heading", "text": "A"},
            {"id": "b", "type": "text", "text": "B"},
        ],
    }


def fence(ui=None):
    return "```chatcore-ui\n" + json.dumps(ui or document(), ensure_ascii=False) + "\n```\n"


class StructuredUiTests(unittest.TestCase):
    def test_calculator_repair_connects_all_numeric_controls(self):
        ui = document()
        ui["nodes"] = [
            {"id": "root", "type": "column", "children": ["price_input", "quantity_input", "result", "chart"]},
            {"id": "price_input", "type": "input", "input_type": "number", "label": "Price", "state_id": "price"},
            {"id": "quantity_input", "type": "slider", "label": "Quantity", "state_id": "quantity"},
            {"id": "result", "type": "text", "binding": "total"},
            {"id": "chart", "type": "chart", "series": [{"label": "Total", "binding": "series"}]},
        ]
        price = {"kind": "state", "value": "price"}
        quantity = {"kind": "state", "value": "quantity"}
        ui["state"] = [{"id": "price", "initial": 10}, {"id": "quantity", "initial": 2}]
        ui["expressions"] = [
            {"id": "total", "op": "mul", "args": [price, {"kind": "literal", "value": 2}]},
            {"id": "sample", "op": "mul", "args": [price, {"kind": "index", "value": 1}]},
            {"id": "series", "op": "series", "args": [{"kind": "literal", "value": 3}, {"kind": "expression", "value": "sample"}]},
        ]
        repaired_ui = copy.deepcopy(ui)
        repaired_ui["expressions"][1]["args"][0] = quantity

        normalized = normalize_response_with_artifact_retry(
            fence(ui), conversation_messages=[], model="test", generate_response=lambda *_: fence(repaired_ui),
            user_request="スライダーで数量を変更して金額を計算して", ui_mode="STRUCTURED_UI",
        )

        self.assertEqual(normalized.structured_ui_quality_errors, ["structured_ui_calculation_not_connected"])
        self.assertTrue(normalized.structured_ui_repair_succeeded)
        self.assertEqual(normalized.parts[0]["ui"]["expressions"][1]["args"][0], quantity)

    def test_storage_roundtrip_and_context_excludes_code(self):
        normalized = normalize_response_with_artifacts("Before\n" + fence() + "After")
        self.assertEqual([p["type"] for p in normalized.parts], ["text", "structured_ui", "text"])
        self.assertEqual([normalized.parts[0]["text"], normalized.parts[2]["text"]], ["Before\n", "After"])
        self.assertIn("A: 10", normalized.text)
        decoded = decode_message_parts(encode_message_parts(normalized.parts))
        self.assertEqual(decoded, normalized.parts)
        self.assertIn("A: 10", build_message_parts_context(decoded))
        self.assertNotIn('"nodes"', build_message_parts_context(decoded))

    def test_all_chunk_boundaries_and_no_payload_leaks(self):
        source = "Before\n" + fence() + "After"
        for width in (1, 2, 3, 7, 61, 3000):
            stream = StructuredUiStream()
            with patch("services.structured_ui.validate_structured_ui", wraps=validate_structured_ui) as validate:
                visible = "".join(stream.feed(source[index : index + width]) for index in range(0, len(source), width))
                visible += stream.feed("", final=True)
                self.assertEqual(validate.call_count, 1)
            self.assertEqual(visible, "Before\nAfter")
            self.assertEqual([p["type"] for p in stream.parts()], ["text", "structured_ui", "text"])

    def test_whitespace_alias_and_malformed_header_never_leak_payload(self):
        for header in ("``` chatcore-ui", "```chatcore_ui", "```chatcore ui:"):
            stream = StructuredUiStream()
            source = header + "\n" + json.dumps(document()) + "\n```\n"
            visible = "".join(stream.feed(char) for char in source)
            visible += stream.feed("", final=True)
            self.assertNotIn('"root_id"', visible)
            self.assertNotIn("chatcore", visible)
            self.assertTrue(any(part["type"] == "structured_ui" for part in stream.parts()))

    def test_incomplete_and_invalid_blocks_do_not_consume_following_prose(self):
        stream = split_structured_ui("A\n```chatcore-ui\n{broken}\n```\nB")
        self.assertEqual(len(stream.errors), 1)
        self.assertTrue(stream.parts()[-1]["text"].endswith("B"))
        for source in ("```chatcore-ui", '```chatcore-ui\n{"version":1'):
            result = normalize_response_with_artifacts(source)
            self.assertNotIn("chatcore-ui", result.text)
            self.assertNotIn('"version"', result.text)

    def test_code_examples_stay_examples(self):
        source = "````markdown\n" + fence() + "````\n"
        result = normalize_response_with_artifacts(source)
        self.assertFalse(any(p["type"] == "structured_ui" for p in result.parts or []))
        self.assertIn("chatcore-ui", result.text)

    def test_cycles_missing_refs_unknown_fields_and_resource_limits(self):
        invalid = []
        ui = document()
        ui["nodes"][0]["children"].append("root")
        invalid.append(ui)
        ui = document()
        ui["nodes"][0]["children"].append("missing")
        invalid.append(ui)
        ui = document()
        ui["nodes"][1]["onclick"] = "fetch('/api/write')"
        invalid.append(ui)
        ui = document()
        ui["nodes"][1]["type"] = "iframe"
        invalid.append(ui)
        ui = document()
        ui["expressions"] = [{"id": "a", "op": "sum", "args": [{"kind": "expression", "value": "a"}]}]
        invalid.append(ui)
        ui = document()
        ui["expressions"] = [{"id": "a", "op": "series", "args": [{"value": 1000000}, {"kind": "expression", "value": "a"}]}]
        invalid.append(ui)
        ui = document()
        ui["state"] = [{"id": "amount", "initial": float("inf")}]
        invalid.append(ui)
        for ui in invalid:
            with self.subTest(ui=ui), self.assertRaises(ValueError):
                validate_structured_ui(ui)
        stream = split_structured_ui("".join(fence({**document(), "id": "block" + str(i)}) for i in range(7)))
        self.assertEqual(sum(p["type"] == "structured_ui" for p in stream.parts()), 6)
        self.assertTrue(stream.errors)

    def test_legacy_fallback_cannot_load_images_or_html_resources(self):
        ui = document()
        ui["fallback_text"] = '<img src="https://evil.test/leak"> ![x](https://evil.test/leak)'
        result = normalize_response_with_artifacts(fence(ui))
        self.assertNotIn("<img", result.text)
        self.assertIn(r"\![", result.text)
        delivered = project_ui_payload({"parts": result.parts})
        self.assertNotIn("<img", delivered["parts"][0]["text"])

    def test_local_input_types_and_unsafe_images_are_rejected(self):
        ui = document()
        ui["nodes"] = [{"id": "root", "type": "checkbox", "label": "Done", "state_id": "done"}]
        ui["state"] = [{"id": "done", "initial": "not boolean"}]
        with self.assertRaises(ValueError):
            validate_structured_ui(ui)
        ui = document()
        ui["images"] = [{"ref": 1, "url": "https://evil.test/image", "source_url": "https://example.test"}]
        with self.assertRaises(ValueError):
            validate_structured_ui(ui)

    def test_native_coexists_with_images_and_legacy_projection_keeps_order(self):
        ui = validate_structured_ui(document())
        parts = [{"type": "text", "text": "A"}, {"type": "structured_ui", "ui": ui}, {"type": "web_search_image", "image": {}}]
        self.assertEqual(len(normalize_message_parts_for_display(parts)), 3)
        projected = project_ui_payload({"parts": parts})
        self.assertEqual(projected["parts"][1], {"type": "text", "text": ui["fallback_text"]})
        self.assertEqual(parts[1]["type"], "structured_ui")

    def test_same_id_replaces_in_place(self):
        newer = copy.deepcopy(document())
        newer["nodes"][1]["text"] = "Updated"
        result = normalize_response_with_artifacts(fence() + "Between\n" + fence(newer))
        self.assertEqual(sum(p["type"] == "structured_ui" for p in result.parts), 1)
        self.assertEqual(result.parts[0]["ui"]["nodes"][1]["text"], "Updated")

    def test_same_root_updates_use_current_not_cumulative_node_budget(self):
        ui = document()
        ui["nodes"] = [
            {"id": "root", "type": "column", "children": ["left", "right"]},
            {"id": "left", "type": "column", "children": ["n" + str(index) for index in range(99)]},
            {"id": "right", "type": "column", "children": ["n" + str(index) for index in range(99, 198)]},
        ]
        ui["nodes"] += [{"id": "n" + str(index), "type": "text", "text": "value"} for index in range(198)]
        newer = copy.deepcopy(ui)
        newer["nodes"][-1]["text"] = "updated"
        stream = split_structured_ui(fence(ui) + fence(newer))
        self.assertFalse(stream.errors)
        self.assertEqual(stream.parts()[0]["ui"]["nodes"][-1]["text"], "updated")

    def test_combined_chart_limit_includes_expression_series_and_saved_parts(self):
        first = document()
        first.update(
            id="chart_one",
            root_id="chart",
            nodes=[
                {
                    "type": "chart",
                    "id": "chart",
                    "series": [{"label": "Fixed", "values": [1] * 300}],
                }
            ],
        )
        second = document()
        second.update(
            id="chart_two",
            root_id="chart",
            nodes=[
                {
                    "type": "chart",
                    "id": "chart",
                    "series": [{"label": "Calculated", "binding": "series"}],
                }
            ],
            expressions=[
                {"id": "value", "op": "abs", "args": [{"kind": "index", "value": 0}]},
                {"id": "series", "op": "series", "args": [{"value": 300}, {"kind": "expression", "value": "value"}]},
            ],
        )
        stream = split_structured_ui(fence(first) + fence(second))
        self.assertEqual(sum(part["type"] == "structured_ui" for part in stream.parts()), 1)
        self.assertTrue(stream.errors)
        stored = decode_message_parts([{"type": "structured_ui", "ui": ui} for ui in (first, second)])
        self.assertEqual([part["type"] for part in stored], ["structured_ui", "text"])

    def test_duplicate_json_keys_rejected(self):
        source = fence().replace('"version": 1,', '"version": 1, "version": 1,')
        result = normalize_response_with_artifacts(source)
        self.assertIn("structured_ui_validation_failed", result.structured_ui_errors)
        self.assertNotIn("structured_ui", [part["type"] for part in result.parts])

    def test_native_citation_becomes_numbered_reference_and_validated_source(self):
        from services.structured_ui_citations import resolve_message_part_citations
        from services.web_search import WebSearchResult, WebSearchSource

        source = WebSearchSource("https://example.test/evidence", "Evidence", "example.test", "", ())
        evidence = WebSearchResult("test", "", (source,))
        marker = f"[[source:{source.evidence_id}]]"
        ui = document()
        ui["nodes"][1]["text"] = "Fact " + marker
        ui["nodes"][2]["text"] = "Another fact " + marker
        parts = normalize_response_with_artifacts(fence(ui)).parts
        resolved = resolve_message_part_citations(parts, evidence)[0]["ui"]
        self.assertEqual(resolved["nodes"][1]["text"], "Fact [1]")
        self.assertEqual(resolved["nodes"][2]["text"], "Another fact [1]")
        self.assertEqual(resolved["sources"], [{"url": source.url, "title": source.title}])

    def test_mixed_repair_replaces_native_slot_and_adds_missing_artifact(self):
        from tests.unit.test_generated_ui_reliability import _artifact_block

        broken = document()
        broken["nodes"][1]["type"] = "unsupported"
        repaired = normalize_response_with_artifact_retry(
            fence(broken),
            conversation_messages=[],
            model="test",
            generate_response=lambda *_: fence() + _artifact_block(),
            user_request="Compare the results and include a custom visual",
            ui_mode="MIXED_2D",
        )
        self.assertEqual([part["type"] for part in repaired.parts], ["structured_ui", "sandbox_artifact"])
        self.assertTrue(repaired.structured_ui_repair_succeeded)

        partial = normalize_response_with_artifact_retry(
            fence(broken),
            conversation_messages=[],
            model="test",
            generate_response=lambda *_: _artifact_block(),
            user_request="Compare the results and include a custom visual",
            ui_mode="MIXED_2D",
        )
        self.assertEqual([part["type"] for part in partial.parts], ["text", "sandbox_artifact"])
        self.assertFalse(partial.structured_ui_repair_succeeded)

    def test_repair_replaces_failed_slot_without_losing_surrounding_text(self):
        ui = document()
        broken = copy.deepcopy(ui)
        broken["nodes"][1]["type"] = "unsupported"
        call = unittest.mock.Mock(return_value=fence(ui))
        repaired = normalize_response_with_artifact_retry(
            "Before\n" + fence(broken) + "After",
            conversation_messages=[],
            model="test",
            generate_response=call,
            user_request="比較して",
            ui_mode="STRUCTURED_UI",
        )
        self.assertEqual([part["type"] for part in repaired.parts], ["text", "structured_ui", "text"])
        self.assertEqual(repaired.parts[0]["text"], "Before\n")
        self.assertEqual(repaired.parts[-1]["text"], "After")
        call.assert_called_once()
        self.assertTrue(repaired.structured_ui_repair_succeeded)
        self.assertTrue(repaired.structured_ui_errors)  # The original validation failure remains observable.
        self.assertFalse(repaired.repair_attempted)  # It is not an Artifact repair.

    def test_citation_mapping_does_not_duplicate_interleaved_prose(self):
        from services.structured_ui_citations import resolve_message_part_citations

        parts = normalize_response_with_artifacts("Before\n" + fence() + "After").parts
        mapped = resolve_message_part_citations(parts, None)
        self.assertEqual([part["text"] for part in mapped if part["type"] == "text"], ["Before\n", "After"])

    def test_text_only_flattens_standard_buttons_without_suppressing_ui_off_choices(self):
        buttons = '```chatcore-buttons\n{"type":"multiple_select","question":"Which?","options":["A","B"]}\n```'
        text = normalize_response_with_artifacts(buttons, explicit_text_only=True)
        self.assertNotIn("interactive_buttons", [p["type"] for p in text.parts or []])
        self.assertIn("Which?", text.text)
        keep = normalize_response_with_artifacts(buttons, explicit_ui_opt_out=True)
        self.assertIn("interactive_buttons", [p["type"] for p in keep.parts or []])


if __name__ == "__main__":
    unittest.main()
