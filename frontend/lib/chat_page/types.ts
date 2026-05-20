export type ChatRoomMode = "normal" | "temporary";

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
  mode: ChatRoomMode;
};

export type ChatSender = "user" | "assistant" | "thinking";

export type AttachedFile = {
  id: string;
  name: string;
  size: number;
  content?: string;
  mediaType?: string;
  dataBase64?: string;
};

export type UiChatMessage = {
  id: string;
  sender: ChatSender;
  text: string;
  streaming?: boolean;
  error?: boolean;
  attachedFileNames?: string[];
  /** Server-side chat_history id; present for persisted (DB-backed) messages. */
  serverId?: number;
  /** 1-based position of this version among its sibling branches. */
  versionIndex?: number;
  /** Total number of sibling branches at this point (>1 means it is switchable). */
  versionCount?: number;
  /** Ordered server ids of all sibling branches, used to switch versions. */
  siblingIds?: number[];
};

export type ChatHistoryMessagePayload = {
  id?: number;
  message?: string;
  sender?: string;
  timestamp?: string;
  attached_file_names?: string[];
  version_index?: number;
  version_count?: number;
  sibling_ids?: number[];
};

export type ChatHistoryPaginationPayload = {
  has_more?: boolean;
  next_before_id?: number | null;
};

export type ChatHistoryPayload = {
  error?: string;
  messages?: ChatHistoryMessagePayload[];
  pagination?: ChatHistoryPaginationPayload;
  room_mode?: string;
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
