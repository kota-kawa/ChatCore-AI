import assert from "node:assert/strict";
import test from "node:test";

import { CurrentUserAuthError, readCurrentUserLoggedIn } from "../lib/chat_page/auth_status";

test("readCurrentUserLoggedIn reads successful current_user payloads", async () => {
  assert.equal(
    await readCurrentUserLoggedIn(
      new Response(JSON.stringify({ logged_in: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
    true,
  );
  assert.equal(
    await readCurrentUserLoggedIn(
      new Response(JSON.stringify({ logged_in: false }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    ),
    false,
  );
});

test("readCurrentUserLoggedIn throws auth errors for 401 and 403", async () => {
  await assert.rejects(
    () => readCurrentUserLoggedIn(new Response(JSON.stringify({ error: "ログインが必要です。" }), { status: 401 })),
    (error) => error instanceof CurrentUserAuthError && error.status === 401,
  );
  await assert.rejects(
    () => readCurrentUserLoggedIn(new Response(JSON.stringify({ error: "Forbidden" }), { status: 403 })),
    (error) => error instanceof CurrentUserAuthError && error.status === 403,
  );
});

test("readCurrentUserLoggedIn rejects non-ok current_user responses", async () => {
  await assert.rejects(
    () => readCurrentUserLoggedIn(new Response(JSON.stringify({ error: "Server error" }), { status: 500 })),
    /current_user request failed/,
  );
});
