import type { PromptAssistTarget } from "./types";

// 主フィールド（本文）はプレビューで先頭に表示する
// Primary content fields are shown first in the suggestion preview.
export const PROMPT_ASSIST_PRIMARY_FIELDS = ["prompt_content", "skill_markdown", "content"] as const;

export const PROMPT_ASSIST_TARGET_META: Record<
  PromptAssistTarget,
  { title: string; lead: string; briefLabel: string; briefPlaceholder: string }
> = {
  task_modal: {
    title: "AIにプロンプトを作ってもらう",
    lead: "作りたいプロンプトの内容を書いて「AIで作成」を押すと、タイトルと本文の下書きを作ります。",
    briefLabel: "作りたいプロンプトの内容（任意）",
    briefPlaceholder:
      "例: 議事録を要点ごとに要約するプロンプト。決定事項とToDoを分けて箇条書きで出力したい。",
  },
  shared_prompt_modal: {
    title: "AIにプロンプトを作ってもらう",
    lead: "どんな内容を共有したいか書いて「AIで作成」を押すと、本文の下書きを作ります。",
    briefLabel: "どんなプロンプトを共有したいか（任意）",
    briefPlaceholder:
      "例: ブログ記事のタイトル案を10個出すプロンプト。読者層とトーンを指定できるようにしたい。",
  },
};

export const PROMPT_ASSIST_SKILL_META = {
  title: "AIにSKILL定義を作ってもらう",
  lead: "どんなSKILLを共有したいか書いて「AIで作成」を押すと、Markdown定義の下書きを作ります。",
  briefLabel: "どんなSKILLを共有したいか（任意）",
  briefPlaceholder:
    "例: SKILLの利用手順をMarkdownで整理し、必要なら補助Pythonスクリプトも付けたい。",
} as const;
