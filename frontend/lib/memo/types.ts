// ---------------------------------------------------------------------------
// Memo page shared types
// ---------------------------------------------------------------------------

export type Collection = {
  id: number;
  name: string;
  color: string;
  memo_count: number;
};

export type MemoSummary = {
  id: number | string;
  title?: string;
  created_at?: string | null;
  updated_at?: string | null;
  archived_at?: string | null;
  pinned_at?: string | null;
  is_archived?: boolean;
  is_pinned?: boolean;
  excerpt?: string;
  share_token?: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  is_expired?: boolean;
  is_revoked?: boolean;
  is_active?: boolean;
  share_url?: string;
  collection_id?: number | null;
  collection_name?: string | null;
  collection_color?: string | null;
  background_color?: string | null;
};

export type MemoDetail = MemoSummary & {
  ai_response?: string;
};

export type MemoListPayload = { memos?: MemoSummary[]; total?: number; error?: string };
export type MemoListState = { memos: MemoSummary[]; total: number };
export type MemoDetailPayload = { memo?: MemoDetail; error?: string };
export type SharePayload = {
  share_token?: string;
  share_url?: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  is_expired?: boolean;
  is_revoked?: boolean;
  is_active?: boolean;
  is_reused?: boolean;
  error?: string;
};
export type CollectionListPayload = { collections?: Collection[]; error?: string };
export type FlashState = { type: "success" | "error"; text: string };
export type HttpError = Error & { status?: number };
export type DetailSaveStatus = "idle" | "saving" | "saved" | "error";
export type BulkAction = "delete" | "archive" | "unarchive" | "pin" | "unpin" | "set_collection" | "clear_collection";
export type MemoActionMenuPosition = { top: number; left: number; width: number; maxHeight: number };
export type MemoDropPosition = "before" | "after";

export type FrozenRect = { left: number; top: number; right: number; bottom: number };

export type SelectOption = { value: string; label: string };

export type MemoComposeFormState = {
  ai_response: string;
  title: string;
  collection_id: number | null;
  background_color: string | null;
};

// Notebook 画面内の表示切替。"memos" は従来のメモ、"context" はマイコンテキスト金庫。
// View switch inside the notebook: "memos" is the classic memo list, "context" is the vault.
export type MemoView = "memos" | "context";

export type MemoExportFormat = "markdown" | "json" | "csv";
export type MemoExportScope = "all" | "selected";

// ---------------------------------------------------------------------------
// Request payloads for /memo/api/* mutations (see lib/memo/api.ts)
// ---------------------------------------------------------------------------

export type MemoUpdateInput = {
  title: string;
  ai_response: string;
  background_color?: string;
  clear_background_color?: true;
  collection_id?: number;
  clear_collection?: true;
};

export type MemoReorderInput = {
  memo_id: number;
  before_id: number | null;
  after_id: number | null;
};

export type BulkMemoActionInput = {
  action: BulkAction;
  memo_ids: number[];
  collection_id?: number | null;
};

export type CollectionInput = { name: string; color: string };

export type MemoSuggestPayload = { title?: string };
