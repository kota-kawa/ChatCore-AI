import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAiAgentHttpError,
  formatAiAgentModelLabel,
  isActionStep,
  isAllowedNavigationPath,
  isSafeInternalPath,
  isUnexpectedAuthRedirect,
  normalizePathname,
  parseSseBlock,
  pathnamesMatch,
  readSseStream,
} from "../lib/chat_page/ai_agent";

function sseChunk(event: string, data: unknown): Uint8Array {
  return new TextEncoder().encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
}

test("parseSseBlock parses named events with JSON data", () => {
  const event = parseSseBlock("event: progress\ndata: {\"message\":\"確認中\"}\n");

  assert.deepEqual(event, {
    type: "progress",
    message: "確認中",
  });
});

test("isSafeInternalPath rejects external navigation forms", () => {
  assert.equal(isSafeInternalPath("/settings"), true);
  assert.equal(isSafeInternalPath("//example.com"), false);
  assert.equal(isSafeInternalPath("/https://example.com"), false);
  assert.equal(isSafeInternalPath("https://example.com"), false);
});

test("normalizePathname strips trailing slash, query, hash and lowercases", () => {
  assert.equal(normalizePathname("/Settings/"), "/settings");
  assert.equal(normalizePathname("/prompt_share?q=mail#top"), "/prompt_share");
  assert.equal(normalizePathname("/"), "/");
  assert.equal(normalizePathname(undefined), "");
});

test("pathnamesMatch treats trailing slash and sub-route redirects as the same destination", () => {
  assert.equal(pathnamesMatch("/settings", "/settings/"), true);
  assert.equal(pathnamesMatch("/settings", "/settings/profile"), true);
  assert.equal(pathnamesMatch("/memo", "/settings"), false);
  // The root must not prefix-match every path.
  assert.equal(pathnamesMatch("/", "/memo"), false);
  assert.equal(pathnamesMatch("/", "/"), true);
});

test("isUnexpectedAuthRedirect flags only unrequested auth landings", () => {
  assert.equal(isUnexpectedAuthRedirect("/settings", "/login"), true);
  assert.equal(isUnexpectedAuthRedirect("/memo", "/register"), true);
  // Asking to open the login page is not an unexpected redirect.
  assert.equal(isUnexpectedAuthRedirect("/login", "/login"), false);
  assert.equal(isUnexpectedAuthRedirect("/settings", "/settings"), false);
});

test("isAllowedNavigationPath permits app pages and blocks side-effecting endpoints", () => {
  assert.equal(isAllowedNavigationPath("/settings"), true);
  assert.equal(isAllowedNavigationPath("/settings/profile"), true);
  assert.equal(isAllowedNavigationPath("/prompt_share?q=mail"), true);
  // Mutating GET endpoints and unknown/external destinations are rejected.
  assert.equal(isAllowedNavigationPath("/logout"), false);
  assert.equal(isAllowedNavigationPath("/google-login"), false);
  assert.equal(isAllowedNavigationPath("/prompt_share_evil"), false);
  assert.equal(isAllowedNavigationPath("https://example.com"), false);
});

test("isActionStep accepts memo_edit steps and keeps rejecting unknown actions", () => {
  assert.equal(
    isActionStep({ action: "memo_edit", description: "誤字を直した本文へ置き換えます", content: "本文" }),
    true,
  );
  assert.equal(isActionStep({ action: "click", description: "ボタンを押す", selector: "#x" }), true);
  assert.equal(isActionStep({ action: "memo_delete", description: "未知の操作" }), false);
  assert.equal(isActionStep({ action: "memo_edit" }), false);
});

test("buildAiAgentHttpError prefers server error message and retry_after", async () => {
  const response = new Response(
    JSON.stringify({ error: "上限に達しました。", retry_after: 30 }),
    { status: 429, headers: { "Content-Type": "application/json" } },
  );

  const error = await buildAiAgentHttpError(response);

  assert.equal(error.message, "上限に達しました。 30秒ほど待ってから再試行してください。");
});

test("buildAiAgentHttpError localizes fallback retry guidance", async () => {
  const response = new Response(
    JSON.stringify({ error: "Too many requests.", retry_after: 30 }),
    { status: 429, headers: { "Content-Type": "application/json" } },
  );

  const error = await buildAiAgentHttpError(response, "en");

  assert.equal(error.message, "Too many requests. Try again in about 30 seconds.");
});

test("formatAiAgentModelLabel identifies gpt-oss models served by Groq", () => {
  assert.equal(formatAiAgentModelLabel("openai/gpt-oss-120b"), "gpt-oss-120b · Groq");
  assert.equal(formatAiAgentModelLabel("custom-model"), "custom-model");
});

// バグ2: MiniChat は done / action_plan / error を受け取った時点で break する。
// これは成功時の通常経路であり、その場合も reader を解放しないと
// response.body がロックされたまま接続が残る。
// Bug 2: MiniChat breaks as soon as done / action_plan / error arrives. That is
// the normal success path, and failing to release the reader there leaves
// response.body locked and the connection leaking.
test("readSseStream releases the reader when the caller stops early on the success path", async () => {
  let pulls = 0;
  let cancelCalls = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      pulls += 1;
      if (pulls === 1) {
        controller.enqueue(sseChunk("progress", { message: "確認中" }));
      } else if (pulls === 2) {
        controller.enqueue(sseChunk("done", { response: "完了", model: "m" }));
      } else {
        // 呼び出し側が break した後に読まれてはいけないブロック。
        // Never read after the caller breaks.
        controller.enqueue(sseChunk("progress", { message: "読まれてはいけない" }));
        controller.close();
      }
    },
    cancel() {
      // 実際の fetch 実装では、これが接続を実際に切る合図になる。
      // In a real fetch implementation, this is what actually tears down the connection.
      cancelCalls += 1;
    },
  });
  const response = new Response(stream);

  const seen: string[] = [];
  for await (const event of readSseStream(response)) {
    seen.push(event.type);
    if (event.type === "done") break;
  }

  assert.deepEqual(seen, ["progress", "done"]);
  // 呼び出し側が break しても、reader.cancel() が本文の残りを打ち切って
  // 接続を解放していることを確認する。
  // Even though the caller broke out, reader.cancel() must have told the
  // underlying source to tear down the rest of the body/connection.
  assert.equal(cancelCalls, 1);
});

test("readSseStream does not error when the stream already ran to completion", async () => {
  let cancelCalls = 0;
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(sseChunk("done", { response: "完了", model: "m" }));
      controller.close();
    },
    cancel() {
      cancelCalls += 1;
    },
  });
  const response = new Response(stream);

  const seen: string[] = [];
  for await (const event of readSseStream(response)) {
    seen.push(event.type);
  }

  assert.deepEqual(seen, ["done"]);
  // ストリームは既に閉じているので、後始末の cancel() は無害に解決するだけで
  // 追加でキャンセルされることはない。
  // The stream is already closed, so the cleanup cancel() just resolves
  // harmlessly without an extra cancellation.
  assert.equal(cancelCalls, 0);
});
