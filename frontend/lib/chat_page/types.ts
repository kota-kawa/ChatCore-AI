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

// プロジェクト（ChatGPT/Claude のプロジェクトに相当するワークスペース）。
// A project: a workspace grouping chats with shared instructions and knowledge.
export type Project = {
  id: number;
  name: string;
  instructions: string;
  createdAt?: string;
  updatedAt?: string;
  chatCount?: number;
  fileCount?: number;
};

// プロジェクトのナレッジファイル（メタ情報。本文はサーバー側で保持）。
// A project knowledge file (metadata only; content lives server-side).
export type ProjectFile = {
  id: number;
  fileName: string;
  byteSize: number;
  createdAt?: string;
};

// プロジェクト詳細（指示・ナレッジ・所属チャットを含む）。
// Project detail including instructions, knowledge files, and member chats.
export type ProjectDetail = Project & {
  files: ProjectFile[];
  rooms: ChatRoom[];
};

export type ChatRoomsPagination = {
  hasMore: boolean;
  nextCursor: string | null;
};

export type ChatRoomsPage = {
  rooms: ChatRoom[];
  pagination: ChatRoomsPagination;
  error?: string;
};

export type ChatSender = "user" | "assistant" | "thinking";
export type ChatGenerationPhase = "preparing" | "web-search" | "generating";

export type GenerativeUiArtifactV1 = {
  version: 1;
  title: string;
  description?: string;
  height?: number;
  html: string;
  css: string;
  js: string;
};

export type InteractiveButtonsV1 = {
  type: "yes_no" | "multiple_choice";
  question: string;
  options?: string[];
};

export type ChatMessagePart =
  | { type: "text"; text: string }
  | { type: "sandbox_artifact"; artifact: GenerativeUiArtifactV1 }
  | { type: "interactive_buttons"; buttons: InteractiveButtonsV1 };

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
  parts?: ChatMessagePart[];
  generationPhase?: ChatGenerationPhase;
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
  message_parts?: ChatMessagePart[];
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

export type ChatResponsePayload = {
  response?: string;
  parts?: ChatMessagePart[];
  error?: string;
  roomTitle?: string;
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
  parts?: ChatMessagePart[];
};

export type StoredGenerationState = {
  roomId: string;
  roomMode: ChatRoomMode;
  lastEventId: number;
  streamedText: string;
  updatedAt: number;
};

export type ModelOption = {
  value: string;
  label: string;
  shortLabel: string;
};
