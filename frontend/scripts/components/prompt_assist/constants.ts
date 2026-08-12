import { localized } from "./strings";
import type { PromptAssistTarget } from "./types";

// 主フィールド（本文）はプレビューで先頭に表示する
// Primary content fields are shown first in the suggestion preview.
export const PROMPT_ASSIST_PRIMARY_FIELDS = ["prompt_content", "skill_markdown", "content"] as const;

type PromptAssistMeta = { title: string; lead: string; briefLabel: string; briefPlaceholder: string };

// 文言は表示時に解決する必要があるため、定数ではなく関数として公開する
// The copy must resolve at render time, so these are exposed as functions rather than constants
export function getPromptAssistTargetMeta(target: PromptAssistTarget): PromptAssistMeta {
  if (target === "shared_prompt_modal") {
    return {
      title: localized("AIにプロンプトを作ってもらう", "Have AI draft a prompt"),
      lead: localized(
        "どんな内容を共有したいか書いて「AIで作成」を押すと、本文の下書きを作ります。",
        "Describe what you want to share, then choose Create with AI to draft the body."
      ),
      briefLabel: localized("どんなプロンプトを共有したいか（任意）", "What prompt do you want to share? (optional)"),
      briefPlaceholder: localized(
        "例: ブログ記事のタイトル案を10個出すプロンプト。読者層とトーンを指定できるようにしたい。",
        "For example: a prompt that suggests ten blog post titles, with the audience and tone as inputs."
      ),
    };
  }
  return {
    title: localized("AIにプロンプトを作ってもらう", "Have AI draft a prompt"),
    lead: localized(
      "作りたいプロンプトの内容を書いて「AIで作成」を押すと、タイトルと本文の下書きを作ります。",
      "Describe the prompt you want, then choose Create with AI to draft a title and body."
    ),
    briefLabel: localized("作りたいプロンプトの内容（任意）", "What prompt do you want to create? (optional)"),
    briefPlaceholder: localized(
      "例: 議事録を要点ごとに要約するプロンプト。決定事項とToDoを分けて箇条書きで出力したい。",
      "For example: a prompt that summarizes meeting notes, listing decisions and to-dos separately."
    ),
  };
}

export function getPromptAssistSkillMeta(): PromptAssistMeta {
  return {
    title: localized("AIにSKILL定義を作ってもらう", "Have AI draft a SKILL definition"),
    lead: localized(
      "どんなSKILLを共有したいか書いて「AIで作成」を押すと、Markdown定義の下書きを作ります。",
      "Describe the SKILL you want to share, then choose Create with AI to draft the Markdown definition."
    ),
    briefLabel: localized("どんなSKILLを共有したいか（任意）", "What SKILL do you want to share? (optional)"),
    briefPlaceholder: localized(
      "例: SKILLの利用手順をMarkdownで整理し、必要なら補助Pythonスクリプトも付けたい。",
      "For example: organize the SKILL's usage steps in Markdown and add a helper Python script if needed."
    ),
  };
}

export function getPromptAssistImageMeta(): PromptAssistMeta {
  return {
    title: localized("AIに画像生成プロンプトを作ってもらう", "Have AI draft an image prompt"),
    lead: localized(
      "作りたい画像を説明すると、被写体・構図・スタイル・光を含む下書きを作ります。",
      "Describe the image you want to create, and AI will draft a prompt covering subject, composition, style, and lighting."
    ),
    briefLabel: localized("どんな画像を生成したいか（任意）", "What image do you want to generate? (optional)"),
    briefPlaceholder: localized(
      "例: 雨上がりの東京を歩く猫。映画のような光、低い視点、横長の構図。",
      "For example: a cat walking through Tokyo after rain, cinematic lighting, low angle, widescreen composition."
    ),
  };
}
