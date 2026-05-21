import assert from "node:assert/strict";
import test from "node:test";

import {
  buildAiAgentHttpError,
  isAllowedNavigationPath,
  isDestructiveActionLabel,
  isSafeInternalPath,
  isUnexpectedAuthRedirect,
  normalizePathname,
  parseSseBlock,
  pathnamesMatch,
} from "../lib/chat_page/ai_agent";

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

test("isDestructiveActionLabel detects irreversible-control wording", () => {
  assert.equal(isDestructiveActionLabel("削除する"), true);
  assert.equal(isDestructiveActionLabel("Delete account"), true);
  assert.equal(isDestructiveActionLabel("送信"), true);
  assert.equal(isDestructiveActionLabel("ログアウト"), true);
  assert.equal(isDestructiveActionLabel("もっと見る"), false);
  assert.equal(isDestructiveActionLabel(null), false);
});

test("buildAiAgentHttpError prefers server error message and retry_after", async () => {
  const response = new Response(
    JSON.stringify({ error: "上限に達しました。", retry_after: 30 }),
    { status: 429, headers: { "Content-Type": "application/json" } },
  );

  const error = await buildAiAgentHttpError(response);

  assert.equal(error.message, "上限に達しました。 30秒ほど待ってから再試行してください。");
});
