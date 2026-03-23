import type { PromptAssistAction, PromptAssistTarget } from "./types";

export const PROMPT_ASSIST_ACTION_META: Record<
  PromptAssistAction,
  { label: string; icon: string; accent: string }
> = {
  generate_draft: {
    label: "AIで下書き生成",
    icon: "bi bi-stars",
    accent: "draft",
  },
  improve: {
    label: "改善する",
    icon: "bi bi-magic",
    accent: "refine",
  },
  shorten: {
    label: "短くする",
    icon: "bi bi-text-paragraph",
    accent: "trim",
  },
  expand: {
    label: "詳しくする",
    icon: "bi bi-arrows-angle-expand",
    accent: "expand",
  },
  generate_examples: {
    label: "入出力例を作る",
    icon: "bi bi-bezier2",
    accent: "examples",
  },
};

export const PROMPT_ASSIST_ACTION_ORDER: PromptAssistAction[] = [
  "generate_draft",
  "improve",
  "shorten",
  "expand",
  "generate_examples",
];

export const PROMPT_ASSIST_TARGET_META: Record<
  PromptAssistTarget,
  { title: string; lead: string; toggleLabel: string }
> = {
  task_modal: {
    title: "タスクの輪郭を整える",
    lead: "入力の抜けや重さを見ながら、タイトル・本文・例を滑らかに補います。",
    toggleLabel: "AI補助を開く",
  },
  shared_prompt_modal: {
    title: "公開用の見せ方まで磨く",
    lead: "投稿前に本文と例を引き上げ、共有しやすい完成度へ寄せます。",
    toggleLabel: "AI補助を開く",
  },
};
