// メモ画面で共有する型定義。メモとコレクション、API のペイロード、通知やドラッグ＆ドロップなど画面の状態、変更系リクエストの入力を含む。
// Shared type definitions for the memo page: memos and collections, API payloads, UI state such as notices and drag-and-drop, and mutation request inputs.

// ---------------------------------------------------------------------------
// メモ画面で共有する型
// Memo page shared types
// ---------------------------------------------------------------------------

// メモをまとめるコレクション（フォルダ）。memo_count はそこに入っているメモの数。
// A collection (folder) that groups memos; memo_count is how many memos it holds.
export type Collection = {
  id: number;
  name: string;
  color: string;
  memo_count: number;
};

// 一覧に表示するメモ 1 件。共有リンク・ゴミ箱の情報も含み、API が返さない項目は省略される。
// One memo as shown in the list, including share-link and trash information; fields the API does not return are omitted.
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
  deleted_at?: string | null;
  trash_expires_at?: string | null;
};

// 詳細表示用のメモ。一覧の項目に加えて本文（ai_response）を持つ。
// A memo for the detail view: the list fields plus the body (ai_response).
export type MemoDetail = MemoSummary & {
  ai_response?: string;
};

export type MemoListPayload = { memos?: MemoSummary[]; total?: number; error?: string };
export type MemoListState = { memos: MemoSummary[]; total: number };
export type MemoDetailPayload = { memo?: MemoDetail; error?: string };
// 共有リンクの状態を返す API のレスポンス。
// Response of the API that returns the state of a share link.
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
// 通知に添える操作（「元に戻す」など）。押されたときに onAction を 1 回だけ呼ぶ
// An action attached to a notice ("Undo" and the like); onAction runs once when it is pressed
export type FlashAction = { label: string; onAction: () => void | Promise<void> };
export type FlashState = { type: "success" | "error"; text: string; action?: FlashAction };
export type HttpError = Error & { status?: number };
// 詳細モーダルの自動保存の状態。
// State of the detail modal's autosave.
export type DetailSaveStatus = "idle" | "saving" | "saved" | "error";
// delete はゴミ箱への移動。restore と purge はゴミ箱の中のメモにだけ使う
// delete moves memos to the trash; restore and purge apply to memos already in the trash
export type BulkAction = "delete" | "restore" | "purge" | "archive" | "unarchive" | "pin" | "unpin" | "set_collection" | "clear_collection";
// メモの操作メニューを表示する位置と、メニューが取れる最大の高さ。
// Where the memo action menu is placed and the maximum height it may take.
export type MemoActionMenuPosition = { top: number; left: number; width: number; maxHeight: number };
// ドラッグしたメモを、対象のメモの手前と後ろのどちらに置くか。
// Whether a dragged memo is dropped before or after the target memo.
export type MemoDropPosition = "before" | "after";

// ドラッグ開始時に固定して記録したカードの矩形。
// A card's rectangle frozen when the drag started.
export type FrozenRect = { left: number; top: number; right: number; bottom: number };

export type SelectOption = { value: string; label: string };

// 新規メモの作成フォームの入力内容。
// Inputs of the new-memo composer form.
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
// /memo/api/* の変更系リクエストのペイロード（lib/memo/api.ts を参照）
// Request payloads for /memo/api/* mutations (see lib/memo/api.ts)
// ---------------------------------------------------------------------------

// メモ更新の入力。clear_background_color と clear_collection に true を渡すと、背景色とコレクションをそれぞれ外す。
// Input for updating a memo; passing true for clear_background_color or clear_collection removes the background color or the collection respectively.
export type MemoUpdateInput = {
  title?: string;
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
