import defaultTasks from "../../data/default_tasks.json";
import type { TaskItem } from "../../scripts/setup/setup_types";
import type { NormalizedTask } from "./types";

export function normalizeTask(task: TaskItem | null | undefined): NormalizedTask {
  if (!task) {
    return {
      name: "無題",
      prompt_template: "プロンプトテンプレートはありません",
      response_rules: "",
      output_skeleton: "",
      input_examples: "",
      output_examples: "",
      is_default: false,
    };
  }

  const name = typeof task.name === "string" && task.name.trim() ? task.name.trim() : "無題";

  return {
    name,
    prompt_template:
      typeof task.prompt_template === "string" && task.prompt_template
        ? task.prompt_template
        : "プロンプトテンプレートはありません",
    response_rules: typeof task.response_rules === "string" ? task.response_rules : "",
    output_skeleton: typeof task.output_skeleton === "string" ? task.output_skeleton : "",
    input_examples: typeof task.input_examples === "string" ? task.input_examples : "",
    output_examples: typeof task.output_examples === "string" ? task.output_examples : "",
    is_default: Boolean(task.is_default),
  };
}

export const FALLBACK_TASKS: NormalizedTask[] = (defaultTasks as TaskItem[]).map((task) => normalizeTask(task));

export function normalizeTaskList(rawTasks: TaskItem[] | undefined | null): NormalizedTask[] {
  if (!Array.isArray(rawTasks) || rawTasks.length === 0) return FALLBACK_TASKS;
  return rawTasks.map((task) => normalizeTask(task));
}
