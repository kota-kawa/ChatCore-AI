export type PromptAssistTarget = "task_modal" | "shared_prompt_modal";

export type PromptAssistAction =
  | "generate_draft"
  | "improve"
  | "shorten"
  | "expand"
  | "generate_examples";

export type PromptAssistFieldName =
  | "title"
  | "content"
  | "prompt_content"
  | "category"
  | "author"
  | "prompt_type"
  | "input_examples"
  | "output_examples"
  | "ai_model";

export type PromptAssistSuggestionMode = "create" | "refine";

export type PromptAssistResponse = {
  summary?: string;
  warnings?: string[];
  suggested_fields?: Partial<Record<PromptAssistFieldName, string>>;
  suggestion_modes?: Partial<Record<PromptAssistFieldName, PromptAssistSuggestionMode>>;
  model?: string;
};

export type PromptAssistFieldConfig = {
  label: string;
  element: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null;
  getValue?: () => string;
};

export type PromptAssistConfig = {
  root: HTMLElement | null;
  target: PromptAssistTarget;
  fields: Partial<Record<PromptAssistFieldName, PromptAssistFieldConfig>>;
  beforeApplyField?: (fieldName: PromptAssistFieldName) => void;
};
