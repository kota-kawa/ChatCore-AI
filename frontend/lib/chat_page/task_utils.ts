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

export type ParsedTaskLaunch = {
  taskName: string;
  setupInfo: string;
};

// 履歴から読み込んだユーザーメッセージはサーバー側で html.escape + 改行→<br> 変換されて
// 保存される（services/chat_use_case.py）。送信直後の生テキストと同じ形に戻してから解析する。
// History-loaded user messages are stored html-escaped with newlines turned into <br>
// (services/chat_use_case.py). Restore them to the raw shape used right after sending.
function normalizeStoredUserMessage(message: string): string {
  return message
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/gi, "'")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
}

// 「【タスク】<名前>」で始まる起動メッセージからタスク名と入力（状況・作業環境）を抽出する。
// blueprints/chat/messages.py の _parse_task_launch_message と同じ規則に揃えている。
// Extract the task name and setup input from a task-launch message; mirrors the backend parser.
// 送信直後（生の改行）でも、再読込後（<br>・HTMLエスケープ済み）でも同じ結果になるようにする。
// Produces the same result whether the text is freshly sent (raw newlines) or reloaded
// from history (<br>-joined and html-escaped).
export function parseTaskLaunchMessage(message: string | null | undefined): ParsedTaskLaunch | null {
  if (!message) return null;

  const normalized = normalizeStoredUserMessage(message);

  const taskMatch = /^【タスク】([^\n]+)/m.exec(normalized);
  if (!taskMatch) return null;

  const setupMatch = /【状況・作業環境】([\s\S]+)/.exec(normalized);
  return {
    taskName: taskMatch[1].trim(),
    setupInfo: setupMatch ? setupMatch[1].trim() : "",
  };
}
