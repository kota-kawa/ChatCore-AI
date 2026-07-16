// 旧・単一軸タイプ (派生値として後方互換のため保持: フィード絞り込み・カード表示で使用)。
// Legacy single-axis type kept as a derived value (used by the feed filter and cards).
export type PromptType = "text" | "image" | "skill";

// 2軸モデル: フォーマット軸 × メディア軸 (services/prompt_types.py のミラー)。
// Two-axis model: content format axis × media type axis.
export type ContentFormat = "prompt" | "skill";
export type MediaType = "text" | "image";

// メディア添付の1要素。
// A single media attachment descriptor.
export type PromptAttachment = {
  url: string;
  role?: string;
  media_type?: string;
};

export type PromptPagination = {
  page?: number;
  per_page?: number;
  limit?: number;
  total?: number | null;
  total_pages?: number | null;
  has_next?: boolean;
  has_prev?: boolean;
  next_cursor?: string | null;
};

export type PromptData = {
  id?: string | number;
  title: string;
  content: string;
  category?: string;
  author?: string;
  // 2軸モデルの正準フィールド。
  // Canonical two-axis fields.
  content_format?: ContentFormat | string;
  media_type?: MediaType | string;
  attributes?: Record<string, string>;
  attachments?: PromptAttachment[];
  // 旧フィールドは後方互換の派生値 (サーバが算出して返す)。
  // Legacy fields are derived values returned by the server for compatibility.
  prompt_type?: PromptType | string;
  reference_image_url?: string;
  skill_markdown?: string;
  skill_python_script?: string;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  liked?: boolean;
  used_in_chat?: boolean;
  comment_count?: number;
  created_at?: string;
};

export type PromptCommentData = {
  id: string | number;
  prompt_id: string | number;
  user_id: number;
  author_name: string;
  content: string;
  created_at?: string;
  mine?: boolean;
  can_delete?: boolean;
};

export type PromptFeedResponse = {
  status?: string;
  prompts?: PromptData[];
  pagination?: PromptPagination;
  error?: string;
  message?: string;
};

export type PromptCommentsResponse = {
  status?: string;
  comments?: PromptCommentData[];
  comment?: PromptCommentData;
  comment_count?: number;
  prompt_id?: string | number;
  error?: string;
  message?: string;
  hidden?: boolean;
  already_reported?: boolean;
};
