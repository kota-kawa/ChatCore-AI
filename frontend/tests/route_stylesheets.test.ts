import assert from "node:assert/strict";
import test from "node:test";

import { getAllRouteStylesheetHrefs, getRouteStylesheetHrefs } from "../lib/route_stylesheets";

test("getRouteStylesheetHrefs resolves static routes", () => {
  assert.deepEqual(getRouteStylesheetHrefs("/"), ["/static/css/pages/chat/page.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/memo"), ["/memo/static/css/memo_form.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/prompt_share"), ["/prompt_share/static/css/pages/prompt_share.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/prompt_share/manage_prompts"), [
    "/prompt_share/static/css/pages/prompt_manage.css"
  ]);
  assert.deepEqual(getRouteStylesheetHrefs("/settings"), ["/static/css/pages/user_settings/index.css"]);
});

test("getRouteStylesheetHrefs resolves dynamic shared routes", () => {
  assert.deepEqual(getRouteStylesheetHrefs("/shared/abc123"), ["/static/css/pages/chat/shared_chat.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/shared/memo/abc123"), ["/static/css/pages/shared_memo.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/shared/prompt/42"), ["/static/css/pages/shared_prompt.css"]);
  assert.deepEqual(getRouteStylesheetHrefs("/shared/prompt/42/my-prompt-slug"), [
    "/static/css/pages/shared_prompt.css"
  ]);
});

test("getRouteStylesheetHrefs returns an empty array for routes without page CSS", () => {
  assert.deepEqual(getRouteStylesheetHrefs("/login"), []);
  assert.deepEqual(getRouteStylesheetHrefs("/register"), []);
  assert.deepEqual(getRouteStylesheetHrefs("/admin"), []);
  assert.deepEqual(getRouteStylesheetHrefs("/unknown"), []);
  assert.deepEqual(getRouteStylesheetHrefs(""), []);
});

test("getAllRouteStylesheetHrefs contains every route stylesheet", () => {
  const all = getAllRouteStylesheetHrefs();
  assert.ok(all.includes("/static/css/pages/chat/page.css"));
  assert.ok(all.includes("/memo/static/css/memo_form.css"));
  assert.ok(all.includes("/static/css/pages/user_settings/index.css"));
  assert.ok(all.includes("/static/css/pages/shared_memo.css"));
  assert.ok(all.length >= 8);
});
