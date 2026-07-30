import assert from "node:assert/strict";
import test from "node:test";

import { getStableTaskKey, normalizeTaskList } from "../lib/chat_page/task_utils";

test("normalizeTaskList preserves a valid empty task list", () => {
  assert.deepEqual(normalizeTaskList([]), []);
});

test("normalizeTaskList uses fallback tasks only when the payload is absent", () => {
  assert.ok(normalizeTaskList(null).length > 0);
  assert.ok(normalizeTaskList(undefined).length > 0);
});

test("normalized tasks retain their database identity", () => {
  const [task] = normalizeTaskList([{ task_id: 42, name: "同名タスク" }]);
  assert.equal(task?.task_id, 42);
  assert.equal(task ? getStableTaskKey(task) : null, "task-id-42");
});

test("fallback task keys use the stable system key", () => {
  const [task] = normalizeTaskList(null);
  assert.ok(task);
  assert.equal(task.task_id, null);
  assert.equal(getStableTaskKey(task), `task-system-${task.system_task_key}`);
});
