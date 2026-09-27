import assert from "node:assert/strict";
import test from "node:test";

import { normalizeChatMessageParts, normalizeToolApproval } from "../lib/chat_page/api_contract";
import { decideToolApproval, ToolApprovalDecisionError } from "../lib/chat_page/tool_approval_api";
import {
  findToolApproval,
  isToolApprovalDecidable,
  isToolApprovalExpired,
  replaceToolApprovalInMessages,
  shouldAutoContinueAfterApproval,
} from "../lib/chat_page/tool_approvals";
import type { UiChatMessage } from "../lib/chat_page/types";
import type { ToolApprovalApi } from "../types/generated/api_schemas";

const NOW = Date.parse("2026-09-24T12:00:00Z");

function rawApproval(overrides: Record<string, unknown> = {}) {
  return {
    id: "a1",
    tool: "memo_create",
    family: "memo",
    status: "pending",
    always_allowed: true,
    preview: { kind: "memo_create", title: "買い物", content: "牛乳" },
    expires_at: "2026-09-25T12:00:00Z",
    ...overrides,
  };
}

function approval(overrides: Record<string, unknown> = {}): ToolApprovalApi {
  const normalized = normalizeToolApproval(rawApproval(overrides));
  assert.ok(normalized, "fixture must be a valid approval");
  return normalized;
}

function assistant(id: string, approvals: ToolApprovalApi[]): UiChatMessage {
  return {
    id,
    sender: "assistant",
    text: "変更案です。",
    parts: [
      { type: "text", text: "変更案です。" },
      ...approvals.map((entry) => ({ type: "tool_approval" as const, approval: entry })),
    ],
  };
}

function user(id: string): UiChatMessage {
  return { id, sender: "user", text: "お願い" };
}

test("a valid approval card passes with the generated defaults filled in", () => {
  const normalized = normalizeToolApproval(rawApproval());
  assert.equal(normalized?.id, "a1");
  assert.equal(normalized?.decision, null);
  assert.equal(normalized?.readonly, false);
  assert.equal(normalized?.result, null);
});

test("a card whose tool, status or shape breaks the contract is dropped", () => {
  assert.equal(normalizeToolApproval(rawApproval({ tool: "publish_prompt" })), undefined);
  assert.equal(normalizeToolApproval(rawApproval({ status: "running" })), undefined);
  assert.equal(normalizeToolApproval(rawApproval({ warnings: ["something_else"] })), undefined);
  assert.equal(normalizeToolApproval(rawApproval({ id: "" })), undefined);
  assert.equal(normalizeToolApproval("not an object"), undefined);
});

test("the model validators the generated schema cannot carry are enforced", () => {
  // 操作できるカードはプレビュー必須、共有表示の読み取り専用カードはプレビュー無しで通す
  // An actionable card needs a preview; a readonly shared card passes without one
  assert.equal(normalizeToolApproval(rawApproval({ preview: null })), undefined);
  assert.equal(
    normalizeToolApproval({ id: "a1", tool: "memo_edit", family: "memo", status: "succeeded", readonly: true })?.readonly,
    true,
  );
  // プレビューの種類はツールと一致しなければならない / The preview kind must match the tool
  assert.equal(normalizeToolApproval(rawApproval({ tool: "memo_append" })), undefined);
  // 部分置換は1件以上、全文置換は本文あり / Edits mode needs an edit, content mode needs a body
  const editPreview = { kind: "memo_edit", memo_id: 3, memo_title: "議事録", mode: "edits", base_revision: 2 };
  assert.equal(normalizeToolApproval(rawApproval({ tool: "memo_edit", preview: { ...editPreview, edits: [] } })), undefined);
  assert.equal(
    normalizeToolApproval(rawApproval({ tool: "memo_edit", preview: { ...editPreview, mode: "content" } })),
    undefined,
  );
  assert.ok(
    normalizeToolApproval(rawApproval({ tool: "memo_edit", preview: { ...editPreview, edits: [{ before: "a", after: "b" }] } })),
  );
});

test("message parts keep valid approval cards at their position and drop broken ones", () => {
  const parts = normalizeChatMessageParts([
    { type: "text", text: "変更案です。" },
    { type: "tool_approval", approval: rawApproval() },
    { type: "tool_approval", approval: rawApproval({ id: "a2", tool: "memo_append" }) },
  ]);
  assert.deepEqual(
    parts?.map((part) => part.type),
    ["text", "tool_approval"],
  );
});

test("a pending card past its deadline counts as expired and cannot be decided", () => {
  const pending = approval();
  assert.equal(isToolApprovalExpired(pending, NOW), false);
  assert.equal(isToolApprovalDecidable(pending, NOW), true);

  const pastDeadline = approval({ expires_at: "2026-09-24T11:59:59Z" });
  assert.equal(isToolApprovalExpired(pastDeadline, NOW), true);
  assert.equal(isToolApprovalDecidable(pastDeadline, NOW), false);

  assert.equal(isToolApprovalDecidable(approval({ status: "denied", decision: "deny" }), NOW), false);
  assert.equal(isToolApprovalDecidable(approval({ readonly: true }), NOW), false);
  // 決まった後のカードは期限を過ぎても期限切れと表示しない / A settled card never turns expired
  assert.equal(isToolApprovalExpired(approval({ status: "succeeded", expires_at: "2026-01-01T00:00:00Z" }), NOW), false);
});

test("replacing a card updates only the matching part and keeps the list when nothing matches", () => {
  const messages = [user("u1"), assistant("m1", [approval(), approval({ id: "a2" })])];
  const decided = approval({ status: "succeeded", decision: "once", result: { target_id: 9, target_title: "買い物" } });

  const next = replaceToolApprovalInMessages(messages, decided);
  assert.notEqual(next, messages);
  assert.equal(findToolApproval(next, "a1")?.status, "succeeded");
  assert.equal(findToolApproval(next, "a2")?.status, "pending");
  assert.equal(next[0], messages[0]);

  assert.equal(replaceToolApprovalInMessages(messages, approval({ id: "missing" })), messages);
});

test("auto-continue waits until every card on the latest reply is settled and one succeeded", () => {
  const succeeded = approval({ status: "succeeded", decision: "once" });
  const pendingOther = approval({ id: "a2" });
  assert.equal(shouldAutoContinueAfterApproval([user("u1"), assistant("m1", [succeeded, pendingOther])], "a1"), false);

  const deniedOther = approval({ id: "a2", status: "denied", decision: "deny" });
  assert.equal(shouldAutoContinueAfterApproval([user("u1"), assistant("m1", [succeeded, deniedOther])], "a1"), true);
});

test("auto-continue does not fire when every card was denied or failed", () => {
  const denied = approval({ status: "denied", decision: "deny" });
  const failed = approval({ id: "a2", status: "failed", decision: "once", result: { error_code: "target_not_found" } });
  assert.equal(shouldAutoContinueAfterApproval([user("u1"), assistant("m1", [denied, failed])], "a2"), false);
});

test("auto-continue ignores cards on an older reply or one the user already answered", () => {
  const succeeded = approval({ status: "succeeded", decision: "once" });
  // 後ろに利用者の発言がある / The user already wrote after the reply
  assert.equal(shouldAutoContinueAfterApproval([user("u1"), assistant("m1", [succeeded]), user("u2")], "a1"), false);
  // 決めたカードが最新の回答に無い / The decided card is not on the latest reply
  const older = [user("u1"), assistant("m1", [succeeded]), user("u2"), assistant("m2", [])];
  assert.equal(shouldAutoContinueAfterApproval(older, "a1"), false);
  assert.equal(shouldAutoContinueAfterApproval([user("u1"), assistant("m1", [succeeded])], "unknown"), false);
  assert.equal(shouldAutoContinueAfterApproval([], "a1"), false);
});

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

test("the decision API posts the decision and returns the updated card", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init });
    return jsonResponse(200, { approval: rawApproval({ status: "succeeded", decision: "always", result: { target_id: 5 } }) });
  };

  const decided = await decideToolApproval("a1", "approve_always", "失敗", fetchImpl);

  assert.equal(decided.status, "succeeded");
  assert.equal(calls[0].url, "/api/chat/tool-approvals/a1/decision");
  assert.equal(calls[0].init?.method, "POST");
  assert.equal(calls[0].init?.body, JSON.stringify({ decision: "approve_always" }));
});

test("the decision API surfaces the server's error code and message", async () => {
  const fetchImpl = async () => jsonResponse(409, { error: "承認の期限が切れています。", code: "approval_expired" });

  await assert.rejects(decideToolApproval("a1", "approve_once", "失敗", fetchImpl), (error: unknown) => {
    assert.ok(error instanceof ToolApprovalDecisionError);
    assert.equal(error.code, "approval_expired");
    assert.equal(error.status, 409);
    assert.equal(error.message, "承認の期限が切れています。");
    return true;
  });
});

test("the decision API attaches the settled card from an approval_already_decided conflict", async () => {
  const fetchImpl = async () =>
    jsonResponse(409, {
      error: "既に決定されています。",
      code: "approval_already_decided",
      approval: rawApproval({ status: "denied", decision: "deny" }),
    });

  await assert.rejects(decideToolApproval("a1", "approve_once", "失敗", fetchImpl), (error: unknown) => {
    assert.ok(error instanceof ToolApprovalDecisionError);
    assert.equal(error.code, "approval_already_decided");
    assert.equal(error.approval?.status, "denied");
    assert.equal(error.approval?.decision, "deny");
    return true;
  });
});

test("the decision API leaves the card undefined when the conflict response carries none", async () => {
  const fetchImpl = async () => jsonResponse(409, { error: "既に決定されています。", code: "approval_already_decided" });

  await assert.rejects(decideToolApproval("a1", "approve_once", "失敗", fetchImpl), (error: unknown) => {
    assert.ok(error instanceof ToolApprovalDecisionError);
    assert.equal(error.approval, undefined);
    return true;
  });
});

test("the decision API rejects a response whose card breaks the contract", async () => {
  const fetchImpl = async () => jsonResponse(200, { approval: rawApproval({ preview: null }) });

  await assert.rejects(decideToolApproval("a1", "deny", "失敗", fetchImpl), (error: unknown) => {
    assert.ok(error instanceof ToolApprovalDecisionError);
    assert.equal(error.code, "invalid_response");
    return true;
  });
});
