export type NormalizedTask = {
  name: string;
  prompt_template: string;
  response_rules: string;
  output_skeleton: string;
  input_examples: string;
  output_examples: string;
  is_default: boolean;
};

export type ChatRoom = {
  id: string;
  title: string;
  createdAt?: string;
};

export type ChatSender = "user" | "assistant" | "thinking";

export type UiChatMessage = {
  id: string;
  sender: ChatSender;
  text: string;
  streaming?: boolean;
  error?: boolean;
};

export type ChatHistoryMessagePayload = {
  id?: number;
  message?: string;
  sender?: string;
  timestamp?: string;
};

export type ChatHistoryPaginationPayload = {
  has_more?: boolean;
  next_before_id?: number | null;
};

export type ChatHistoryPayload = {
  error?: string;
  messages?: ChatHistoryMessagePayload[];
  pagination?: ChatHistoryPaginationPayload;
};

export type ChatHistoryPagination = {
  hasMore: boolean;
  nextBeforeId: number | null;
};

export type GenerationStatusPayload = {
  error?: string;
  is_generating?: boolean;
  has_replayable_job?: boolean;
};

export type StreamParsedEvent = {
  event: string;
  id?: number;
  data: Record<string, unknown>;
};

export type PromptAssistController = {
  reset: () => void;
};

export type PromptStatusVariant = "info" | "success" | "error";

export type PromptStatus = {
  message: string;
  variant: PromptStatusVariant;
};

export type ShareStatus = {
  message: string;
  error: boolean;
};

export type TaskEditFormState = {
  old_task: string;
  new_task: string;
  prompt_template: string;
  response_rules: string;
  output_skeleton: string;
  input_examples: string;
  output_examples: string;
};

export type StoredHistoryEntry = {
  text: string;
  sender: string;
};

export type ModelOption = {
  value: string;
  label: string;
  shortLabel: string;
};
