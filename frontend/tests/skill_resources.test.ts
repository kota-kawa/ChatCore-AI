import assert from "node:assert/strict";
import test from "node:test";

import {
  inferSkillResourceLanguage,
  normalizeSkillResources
} from "../scripts/prompt_share/skill_resources";

test("skill resource language is inferred from common extensions", () => {
  assert.equal(inferSkillResourceLanguage("scripts/run.py"), "python");
  assert.equal(inferSkillResourceLanguage("scripts/setup.sh"), "shell");
  assert.equal(inferSkillResourceLanguage("src/index.tsx"), "typescript");
  assert.equal(inferSkillResourceLanguage("config/settings.yaml"), "yaml");
  assert.equal(inferSkillResourceLanguage("Dockerfile"), "dockerfile");
  assert.equal(inferSkillResourceLanguage("references/notes.unknown"), "text");
});

test("skill resources are normalized while preserving arbitrary text languages", () => {
  assert.deepEqual(
    normalizeSkillResources([
      {
        path: "scripts/run.kt",
        role: "script",
        language: "kotlin",
        content: "fun main() = println(\"hello\")"
      }
    ]),
    [
      {
        path: "scripts/run.kt",
        role: "script",
        language: "kotlin",
        content: "fun main() = println(\"hello\")"
      }
    ]
  );
});

test("legacy Python script becomes the canonical main.py resource for reading", () => {
  assert.deepEqual(normalizeSkillResources(undefined, "print('legacy')"), [
    {
      path: "scripts/main.py",
      role: "script",
      language: "python",
      content: "print('legacy')"
    }
  ]);
});
