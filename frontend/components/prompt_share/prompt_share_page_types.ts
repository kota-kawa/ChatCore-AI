import type { PromptType } from "../../scripts/prompt_share/types";

// プロンプトカテゴリーの型（値・アイコン・表示ラベル）
// Type for a prompt category (value, icon, display label)
export type PromptCategory = {
  value: string;
  iconClass: string;
  label: string;
};

// プロンプトのタイプフィルター（全件表示または特定タイプのみ）
// Prompt type filter (show all or only a specific type)
export type PromptTypeFilter = "all" | PromptType;

// タイプフィルターの選択肢の型
// Type for a type filter option
export type PromptTypeFilterOption = {
  value: PromptTypeFilter;
  iconClass: string;
  label: string;
};

// 現在開いているモーダルを識別するキー（nullの場合はモーダル非表示）
// Key identifying the currently open modal (null means no modal is shown)
export type ModalKey = "post" | "detail" | "share" | null;

// プロンプト操作に対するフィードバックメッセージの型
// Type for feedback messages from prompt actions
export type PromptFeedback = {
  message: string;
  variant: "empty" | "error";
};

// プロンプト投稿ステータスのバリアント
// Variant for the prompt post status
export type PromptPostStatusVariant = "info" | "success" | "error";

// プロンプト投稿ステータスの型（メッセージとバリアント）
// Type for the prompt post status (message and variant)
export type PromptPostStatus = {
  message: string;
  variant: PromptPostStatusVariant;
};
