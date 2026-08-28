import assert from "node:assert/strict";
import test from "node:test";

import { createUserSkill, fetchUserSkills, updateUserSkillState } from "../lib/chat_page/skill_api";

function response(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

test("fetchUserSkills validates and returns the list", async () => {
  let request: RequestInfo | URL | undefined;
  const skills = [{ id: 1, name: "要約", instructions: "結論から", is_enabled: true }];
  const result = await fetchUserSkills(async (input) => {
    request = input;
    return response({ skills });
  });

  assert.equal(request, "/api/skills");
  assert.deepEqual(result, skills.map((item) => ({ ...item, created_at: null, updated_at: null })));
});

test("create and toggle use the user-skill endpoints", async () => {
  const calls: Array<{ url: string; method: string; body?: string }> = [];
  const fetchImpl = async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), method: init?.method ?? "GET", body: init?.body as string | undefined });
    return response({ skill: { id: 2, name: "校正", instructions: "誤字を直す", is_enabled: false } }, 200);
  };

  await createUserSkill("校正", "誤字を直す", fetchImpl);
  await updateUserSkillState(2, false, fetchImpl);

  assert.deepEqual(calls, [
    { url: "/api/skills", method: "POST", body: JSON.stringify({ name: "校正", instructions: "誤字を直す" }) },
    { url: "/api/skills/2", method: "PATCH", body: JSON.stringify({ is_enabled: false }) },
  ]);
});
