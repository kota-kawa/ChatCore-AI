export type PromptType = "text" | "image";

export type PromptPagination = {
  page?: number;
  per_page?: number;
  total?: number;
  total_pages?: number;
  has_next?: boolean;
  has_prev?: boolean;
};

export type PromptData = {
  id?: string | number;
  title: string;
  content: string;
  category?: string;
  author?: string;
  prompt_type?: PromptType | string;
  reference_image_url?: string;
  input_examples?: string;
  output_examples?: string;
  ai_model?: string;
  liked?: boolean;
  bookmarked?: boolean;
  saved_to_list?: boolean;
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

export type CurrentUserResponse = {
  logged_in?: boolean;
  user?: {
    id?: number;
    email?: string;
    username?: string;
  };
};
