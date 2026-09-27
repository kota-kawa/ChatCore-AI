"""チャットの承認カード（tool_approval パーツ）と承認 API のモデルの契約を検証する。

Verifies the contract of chat approval cards (the tool_approval part) and the approval API models:
payload validation, the summary handed to later turns, and the redacted shape for shared views.
"""

from __future__ import annotations

import unittest
from typing import Any

from pydantic import ValidationError

from services.request_models import ToolApprovalDecisionRequest
from services.response_models import (
    ToolApprovalDecisionResponse,
    ToolAutoApprovalRevokeResponse,
    ToolAutoApprovalsResponse,
)
from services.tool_approval_parts import (
    TOOL_APPROVAL_DECISIONS,
    TOOL_APPROVAL_PART_TYPE,
    TOOL_APPROVAL_STATUSES,
    ToolApprovalValidationError,
    describe_tool_approval_for_context,
    redact_tool_approval_for_share,
    tool_approval_part,
    validate_tool_approval_payload,
)

APPROVAL_ID = "5f0c2a9e-3b7d-4c1e-9a2f-0d6b8e4c7a11"


def _memo_edit_approval(**overrides: Any) -> dict[str, Any]:
    approval: dict[str, Any] = {
        "id": APPROVAL_ID,
        "tool": "memo_edit",
        "family": "memo",
        "status": "pending",
        "always_allowed": True,
        "preview": {
            "kind": "memo_edit",
            "memo_id": 12,
            "memo_title": "買い物 <メモ>",
            "mode": "edits",
            "edits": [{"before": "牛乳  ", "after": "豆乳  "}],
            "base_revision": 3,
        },
        "warnings": ["shared_memo"],
        "expires_at": "2026-09-25T00:00:00+00:00",
    }
    approval.update(overrides)
    return approval


class ValidateToolApprovalPayloadTests(unittest.TestCase):
    def test_valid_payload_round_trips_and_keeps_whitespace(self) -> None:
        approval = validate_tool_approval_payload(_memo_edit_approval())

        self.assertEqual(approval["preview"]["edits"], [{"before": "牛乳  ", "after": "豆乳  "}])
        self.assertEqual(approval["warnings"], ["shared_memo"])
        self.assertFalse(approval["readonly"])
        self.assertNotIn("decision", approval)
        self.assertNotIn("result", approval)

    def test_unknown_keys_are_dropped(self) -> None:
        payload = _memo_edit_approval(arguments={"memo_id": 12})
        payload["preview"]["secret"] = "x"

        approval = validate_tool_approval_payload(payload)

        self.assertNotIn("arguments", approval)
        self.assertNotIn("secret", approval["preview"])

    def test_each_memo_preview_kind_is_accepted(self) -> None:
        previews = [
            {"kind": "memo_create", "title": "", "content": "本文"},
            {"kind": "memo_append", "memo_id": 1, "memo_title": "日記", "text": "追記", "separator": "\n\n"},
            {"kind": "memo_edit", "memo_id": 1, "mode": "content", "content": "", "base_revision": 1},
        ]
        for preview in previews:
            with self.subTest(kind=preview["kind"]):
                approval = validate_tool_approval_payload(_memo_edit_approval(tool=preview["kind"], preview=preview))
                self.assertEqual(approval["preview"]["kind"], preview["kind"])

    def test_invalid_payloads_are_rejected(self) -> None:
        cases = {
            "not a dict": "tool_approval",
            "unknown status": _memo_edit_approval(status="done"),
            "unknown decision": _memo_edit_approval(decision="approve_once"),
            "unknown warning": _memo_edit_approval(warnings=["other"]),
            "unknown tool": _memo_edit_approval(tool="memo_delete"),
            "preview kind differs from tool": _memo_edit_approval(tool="memo_create"),
            "missing preview on an actionable card": _memo_edit_approval(preview=None),
            "edits mode without edits": _memo_edit_approval(
                preview={"kind": "memo_edit", "memo_id": 1, "mode": "edits", "edits": [], "base_revision": 1},
            ),
            "content mode without content": _memo_edit_approval(
                preview={"kind": "memo_edit", "memo_id": 1, "mode": "content", "base_revision": 1},
            ),
            "empty id": _memo_edit_approval(id=""),
        }
        for label, payload in cases.items():
            with self.subTest(label), self.assertRaises(ToolApprovalValidationError):
                validate_tool_approval_payload(payload)

    def test_value_sets_follow_the_response_model(self) -> None:
        self.assertEqual(
            TOOL_APPROVAL_STATUSES,
            ("pending", "succeeded", "failed", "denied", "expired", "superseded", "cancelled"),
        )
        self.assertEqual(TOOL_APPROVAL_DECISIONS, ("once", "always", "auto", "deny"))
        for status in TOOL_APPROVAL_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(validate_tool_approval_payload(_memo_edit_approval(status=status))["status"], status)

    def test_part_wraps_the_approval(self) -> None:
        approval = validate_tool_approval_payload(_memo_edit_approval())

        self.assertEqual(tool_approval_part(approval), {"type": TOOL_APPROVAL_PART_TYPE, "approval": approval})
        self.assertEqual(TOOL_APPROVAL_PART_TYPE, "tool_approval")


class DescribeToolApprovalForContextTests(unittest.TestCase):
    def test_summary_is_escaped_and_leaves_out_the_body(self) -> None:
        approval = _memo_edit_approval(status="succeeded", decision="once", result={"target_id": 12})

        lines = describe_tool_approval_for_context(approval)

        self.assertEqual(
            lines,
            [
                '<tool_approval tool="memo_edit" status="succeeded">',
                "<target>買い物 &lt;メモ&gt;</target>",
                "<result>target_id=12</result>",
                "</tool_approval>",
            ],
        )
        self.assertNotIn("牛乳", "\n".join(lines))

    def test_create_uses_the_new_title_and_failure_reports_the_code(self) -> None:
        approval = _memo_edit_approval(
            tool="memo_create",
            status="failed",
            preview={"kind": "memo_create", "title": "新しい\"メモ\"", "content": "非公開の本文"},
            result={"error_code": "memo_revision_conflict"},
        )

        lines = describe_tool_approval_for_context(approval)

        self.assertIn("<target>新しい&quot;メモ&quot;</target>", lines)
        self.assertIn("<result>error_code=memo_revision_conflict</result>", lines)
        self.assertNotIn("非公開の本文", "\n".join(lines))

    def test_attributes_are_escaped(self) -> None:
        lines = describe_tool_approval_for_context(_memo_edit_approval(tool='x" onload="y', preview=None))

        self.assertEqual(lines[0], '<tool_approval tool="x&quot; onload=&quot;y" status="pending">')
        self.assertEqual(lines[-1], "</tool_approval>")

    def test_malformed_approval_gives_no_lines(self) -> None:
        self.assertEqual(describe_tool_approval_for_context(None), [])
        self.assertEqual(describe_tool_approval_for_context({"tool": "memo_edit"}), [])


class RedactToolApprovalForShareTests(unittest.TestCase):
    def test_redaction_keeps_only_the_outline_and_stays_valid(self) -> None:
        approval = validate_tool_approval_payload(
            _memo_edit_approval(status="succeeded", decision="always", result={"target_id": 12, "target_title": "買い物"}),
        )

        redacted = redact_tool_approval_for_share(approval)

        self.assertEqual(
            redacted,
            {
                "id": APPROVAL_ID,
                "tool": "memo_edit",
                "family": "memo",
                "status": "succeeded",
                "decision": "always",
                "readonly": True,
            },
        )
        self.assertEqual(validate_tool_approval_payload(redacted), {**redacted, "always_allowed": False, "warnings": []})
        self.assertEqual(
            describe_tool_approval_for_context(redacted),
            ['<tool_approval tool="memo_edit" status="succeeded">', "</tool_approval>"],
        )

    def test_pending_card_without_decision_is_redacted(self) -> None:
        redacted = redact_tool_approval_for_share(validate_tool_approval_payload(_memo_edit_approval()))

        self.assertNotIn("decision", redacted)
        self.assertNotIn("preview", redacted)
        self.assertNotIn("warnings", redacted)
        self.assertNotIn("expires_at", redacted)
        self.assertTrue(redacted["readonly"])


class ToolApprovalApiModelTests(unittest.TestCase):
    def test_decision_request_accepts_only_known_actions(self) -> None:
        for decision in ("approve_once", "approve_always", "deny"):
            with self.subTest(decision=decision):
                self.assertEqual(ToolApprovalDecisionRequest.model_validate({"decision": decision}).decision, decision)
        for payload in ({"decision": "always"}, {}, {"decision": "deny", "extra": 1}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                ToolApprovalDecisionRequest.model_validate(payload)

    def test_decision_response_wraps_a_valid_card(self) -> None:
        response = ToolApprovalDecisionResponse.model_validate({"approval": _memo_edit_approval(status="denied", decision="deny")})

        self.assertEqual(response.approval.status, "denied")
        with self.assertRaises(ValidationError):
            ToolApprovalDecisionResponse.model_validate({"approval": _memo_edit_approval(preview=None)})

    def test_auto_approval_responses(self) -> None:
        grants = ToolAutoApprovalsResponse.model_validate(
            {"grants": [{"tool_name": "memo_append", "family": "memo", "created_at": "2026-09-24T00:00:00+00:00"}]},
        )

        self.assertEqual(grants.grants[0].tool_name, "memo_append")
        self.assertEqual(ToolAutoApprovalsResponse().grants, [])
        self.assertFalse(ToolAutoApprovalRevokeResponse(revoked=False).revoked)
        with self.assertRaises(ValidationError):
            ToolAutoApprovalsResponse.model_validate(
                {"grants": [{"tool_name": "publish_prompt", "family": "memo", "created_at": "2026-09-24T00:00:00+00:00"}]},
            )


if __name__ == "__main__":
    unittest.main()
