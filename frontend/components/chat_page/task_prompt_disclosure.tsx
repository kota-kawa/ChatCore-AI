import { memo } from "react";

import type { NormalizedTask } from "../../lib/chat_page/types";

type TaskPromptDisclosureProps = {
  task?: NormalizedTask;
};

type TaskPromptSection = {
  label: string;
  value: string;
};

// タスク定義（裏側で LLM に送られる指示）を表示順のセクション配列に変換する。
// ラベルはタスク詳細モーダルと揃えている。
// Flatten the task definition (the instructions sent to the LLM behind the scenes)
// into ordered sections; labels match the task detail modal.
function buildTaskPromptSections(task: NormalizedTask): TaskPromptSection[] {
  const candidates: TaskPromptSection[] = [
    { label: "プロンプトテンプレート", value: task.prompt_template },
    { label: "回答ルール", value: task.response_rules },
    { label: "出力テンプレート", value: task.output_skeleton },
    { label: "入力例", value: task.input_examples },
    { label: "出力例", value: task.output_examples },
  ];
  return candidates.filter((section) => section.value && section.value.trim().length > 0);
}

// タスク起動メッセージに紐づく「裏側のタスクプロンプト」を折り畳みで表示する。
// 【タスク】名と【状況・作業環境】は呼び出し側で常時表示するため、ここには含めない。
// 表示できる指示が無い場合（タスク未検出・プロンプト未設定）は何も描画しない。
// Collapsible disclosure for the underlying task prompt tied to a task-launch message.
// The 【タスク】 name and 【状況・作業環境】 input stay visible in the caller, so they are
// intentionally excluded here. Renders nothing when there is no prompt to show.
function TaskPromptDisclosureComponent({ task }: TaskPromptDisclosureProps) {
  const sections = task ? buildTaskPromptSections(task) : [];
  if (sections.length === 0) return null;

  return (
    <details className="task-prompt-disclosure">
      <summary className="task-prompt-disclosure__summary">
        <i className="bi bi-chevron-right task-prompt-disclosure__chevron" aria-hidden="true"></i>
        <span className="task-prompt-disclosure__label">タスクプロンプト</span>
      </summary>

      <div className="task-prompt-disclosure__body">
        {sections.map((section) => (
          <section key={section.label} className="task-prompt-disclosure__section">
            <h6 className="task-prompt-disclosure__section-title">{section.label}</h6>
            <div className="task-prompt-disclosure__section-body">{section.value}</div>
          </section>
        ))}
      </div>
    </details>
  );
}

export const TaskPromptDisclosure = memo(TaskPromptDisclosureComponent);
TaskPromptDisclosure.displayName = "TaskPromptDisclosure";
