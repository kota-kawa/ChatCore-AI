import type { NormalizedTask } from "./types";

export function buildTaskOrderForPersistence(tasks: NormalizedTask[]) {
  return tasks
    .filter((task) => !task.is_default)
    .map((task) => task.name.trim())
    .filter((name) => Boolean(name));
}
