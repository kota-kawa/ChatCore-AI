import defaultTasks from "../../data/default_tasks.json";
import { formatMultilineHtml } from "../core/html";

import type { TaskItem } from "./setup_types";

export function getFallbackTasks() {
  return (defaultTasks as TaskItem[]).map((task) => ({
    ...task,
    is_default: true
  }));
}

export { formatMultilineHtml };

function normalizeTask(task: TaskItem | null | undefined) {
  if (!task) {
    return {
      name: "",
      prompt_template: "",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false
    };
  }

  return {
    name: task.name ? String(task.name).trim() : "",
    prompt_template: task.prompt_template ? String(task.prompt_template) : "",
    response_rules: task.response_rules ? String(task.response_rules) : "",
    output_skeleton: task.output_skeleton ? String(task.output_skeleton) : "",
    input_examples: task.input_examples ? String(task.input_examples) : "",
    output_examples: task.output_examples ? String(task.output_examples) : "",
    is_default: Boolean(task.is_default)
  };
}

export function createTaskSignature(tasks: TaskItem[]) {
  if (!Array.isArray(tasks) || tasks.length === 0) return "__empty__";
  return tasks
    .map((task) => {
      const normalized = normalizeTask(task);
      return [
        normalized.name,
        normalized.prompt_template,
        normalized.response_rules,
        normalized.output_skeleton,
        normalized.input_examples,
        normalized.output_examples,
        normalized.is_default ? "1" : "0"
      ].join("\u001f");
    })
    .join("\u001e");
}
