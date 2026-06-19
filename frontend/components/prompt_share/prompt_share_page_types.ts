import type { ContentFormat, MediaType } from "../../scripts/prompt_share/types";

// プロンプトカテゴリーの型（値・アイコン・表示ラベル）
// Type for a prompt category (value, icon, display label)
export type PromptCategory = {
  value: string;
  iconClass: string;
  label: string;
};

// フォーマットフィルター（全件表示または特定フォーマットのみ）
// Content format filter (show all or only a specific format)
export type ContentFormatFilter = "all" | ContentFormat;

// メディアフィルター（全件表示または特定生成メディアのみ）
// Media type filter (show all or only a specific media type)
export type MediaTypeFilter = "all" | MediaType;

// 軸フィルターの選択肢の型
// Type for an axis filter option
export type PromptAxisFilterOption<TValue extends string> = {
  value: TValue;
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
