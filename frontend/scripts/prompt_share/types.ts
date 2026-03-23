export type PromptType = "text" | "image";

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
  bookmarked?: boolean;
  saved_to_list?: boolean;
  created_at?: string;
};

export type CurrentUserResponse = {
  logged_in?: boolean;
  user?: {
    id?: number;
    email?: string;
    username?: string;
  };
};
