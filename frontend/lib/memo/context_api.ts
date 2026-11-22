// 記憶（パーソナル・コンテキスト）の API クライアント。事実の取得・作成・更新、
// 自動保存と回答への利用の設定、記憶の書き出しとインポート（確認してから取り込む）を扱う。
// API client for Memory (the personal context): loading, creating and updating facts,
// the auto-saving and use-in-answers settings, and exporting and importing the memory (import is previewed before it is confirmed).

import { resilientFetch } from "../../scripts/core/resilient_fetch";
import { setLoggedInState } from "../../scripts/core/app_state";
import { writeCachedAuthState } from "../../scripts/core/auth_state_cache";
import { memoFetchJsonOrThrow } from "./api";
import { splitSearchTerms } from "./search_highlight";
import type { HttpError } from "./types";
import type {
  ContextExtractionSettings,
  ContextExtractionSettingsUpdateInput,
  ContextMemoryUseSettings,
  ContextMemoryUseSettingsUpdateInput,
  ContextFact,
  ContextFactCreateInput,
  ContextFactListPayload,
  ContextFactMutationPayload,
  ContextFactMutationResult,
  ContextFactRevertResult,
  ContextFactStatus,
  ContextFactType,
  ContextFactUpdateInput,
  ContextVaultExportFormat,
  ContextVaultImportConfirmInput,
  ContextVaultImportPreview,
  ContextVaultImportPreviewInput,
  ContextVaultImportResult,
} from "./context_types";

// 「すべての記憶を削除」がリクエストへ付ける確認の値。サーバーの blueprints/context_vault/constants.py の DELETE_ALL_CONFIRMATION と揃える。
// The confirmation value "delete all memories" sends; keep in step with DELETE_ALL_CONFIRMATION in the server's blueprints/context_vault/constants.py.
const DELETE_ALL_CONFIRMATION = "delete-all";

// 事実の一覧と、次のページを取るためのカーソル。
// A page of facts plus the cursor for fetching the next page.
export type ContextFactListResult = {
  facts: ContextFact[];
  totalActive: number;
  nextCursor: string | null;
};

// 書き出したファイルの中身と、保存する際のファイル名。
// The exported file's contents and the filename to save it under.
export type ContextVaultExportResult = {
  blob: Blob;
  filename: string;
};

// HTTP ステータスを持つエラーを作る。画面側は status で分岐できる。
// Creates an error that carries the HTTP status so the UI can branch on it.
function createContextApiError(message: string, status: number): HttpError {
  const error = new Error(message) as HttpError;
  error.status = status;
  return error;
}

// 認証切れを空データとして扱わず、ページ間で共有する認証状態にも反映する。
// Do not disguise an expired session as empty data; propagate it to shared auth state.
function handleExpiredContextSession(): never {
  writeCachedAuthState(false);
  if (typeof document !== "undefined") {
    setLoggedInState(false);
  }
  throw createContextApiError(
    "ログインセッションが切れました。再ログインしてください。",
    401,
  );
}

// Content-Disposition からファイル名を取り出す。UTF-8 指定の filename* を優先し、無ければ通常の filename を使う。
// Extracts the filename from Content-Disposition, preferring the UTF-8 filename* form over the plain filename.
function parseAttachmentFilename(headerValue: string | null): string | null {
  if (!headerValue) return null;
  const encodedMatch = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1].trim());
    } catch {
      // 復号に失敗したら、通常の filename の取り出しへ進む。
      // Fall through to the plain filename parameter.
    }
  }
  const plainMatch = headerValue.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1]?.trim() || null;
}

// 失敗レスポンスから表示用のメッセージを組み立てて throw する。401 は認証切れとして扱う。
// Builds a user-facing message from a failed response and throws; a 401 is treated as an expired session.
async function throwContextResponseError(response: Response, defaultMessage: string): Promise<never> {
  if (response.status === 401) handleExpiredContextSession();
  const payload = (await response.json().catch(() => ({}))) as { error?: unknown; message?: unknown };
  const message =
    (typeof payload.error === "string" && payload.error.trim()) ||
    (typeof payload.message === "string" && payload.message.trim()) ||
    `${defaultMessage} (${response.status})`;
  throw createContextApiError(message, response.status);
}

// 一覧の 1 件を、出典・置き換えの項目が無い応答（旧バージョンのサーバー）でも同じ形で扱えるよう既定値で補う。
// Fills a list item's defaults so a response without the source and replacement fields (an older server) is handled the same way.
function normalizeContextFact(fact: ContextFact): ContextFact {
  return {
    ...fact,
    source_count: typeof fact.source_count === "number" ? fact.source_count : 0,
    last_mentioned_at: fact.last_mentioned_at ?? null,
    sources: Array.isArray(fact.sources) ? fact.sources : [],
    superseded_by: fact.superseded_by ?? null,
    replaces: fact.replaces ?? null,
  };
}

// 検索語を、サーバーが実際に使う形にそろえる。前後の空白を除き、語に分けて 1 つも残らない（空・空白・句読点だけ）なら空文字にする。
// サーバーは語が 0 個の検索語を「検索なし」として全件を返すので、画面も同じく検索なしとして扱い、取得の条件と表示が食い違わないようにする。
// Normalizes a search query to what the server actually uses: trimmed, and an empty string when no term is left after splitting
// (empty, whitespace or punctuation only). The server treats a query with no terms as "no search" and returns everything, so the
// screen treats it as no search too, keeping what is fetched and what is shown in step.
export function normalizeContextSearchQuery(query: string | null | undefined): string {
  const trimmed = (query ?? "").trim();
  return splitSearchTerms(trimmed).length > 0 ? trimmed : "";
}

// 記憶の一覧を種類・状態・検索語で絞り込んで取得する。検索語は normalizeContextSearchQuery で整え、検索なしなら送らない。
// Load the Memory list, filtered by fact type / status / search query; the query is normalized by normalizeContextSearchQuery and omitted when it means no search.
export async function loadContextFacts(params: {
  factType?: ContextFactType | null;
  status?: ContextFactStatus;
  cursor?: string | null;
  query?: string | null;
}): Promise<ContextFactListResult> {
  const query = new URLSearchParams();
  if (params.factType) query.set("fact_type", params.factType);
  query.set("status", params.status ?? "active");
  if (params.cursor) query.set("cursor", params.cursor);
  const searchText = normalizeContextSearchQuery(params.query);
  if (searchText) query.set("q", searchText);

  const res = await resilientFetch(`/api/context-facts?${query.toString()}`, {
    credentials: "same-origin",
  });
  const data: ContextFactListPayload = await res.json().catch(() => ({}));
  if (res.status === 401) handleExpiredContextSession();
  if (!res.ok) {
    throw createContextApiError(
      data.error || `記憶の取得に失敗しました (${res.status})`,
      res.status,
    );
  }
  return {
    facts: Array.isArray(data.facts) ? data.facts.map(normalizeContextFact) : [],
    totalActive: typeof data.total_active === "number" ? data.total_active : 0,
    nextCursor: data.next_cursor ?? null,
  };
}

// 記憶を新規作成する。
// Create a new context fact.
export async function createContextFact(input: ContextFactCreateInput): Promise<ContextFactMutationResult> {
  const { payload } = await memoFetchJsonOrThrow<ContextFactMutationPayload>(
    "/api/context-facts",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "記憶の保存に失敗しました。", hasApplicationError: (d) => !d.fact },
  );
  return payload.fact as ContextFactMutationResult;
}

// 記憶を更新する（無効化・復元も status で行う）。
// Update a context fact (deprecate/restore handled via status).
export async function updateContextFact(
  factId: number,
  input: ContextFactUpdateInput,
): Promise<ContextFactMutationResult> {
  const { payload } = await memoFetchJsonOrThrow<ContextFactMutationPayload>(
    `/api/context-facts/${factId}`,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "記憶の更新に失敗しました。", hasApplicationError: (d) => !d.fact },
  );
  return payload.fact as ContextFactMutationResult;
}

// 置き換えで入った新しい記憶を無効化し（この内容は再び覚えない）、置き換えられた古い記憶を有効へ戻す。revision は新しい記憶のもの。
// 画面が 409（置き換えが別の場所で先に変わった）で一覧を取り直せるよう、失敗は HTTP ステータスを持つエラーで返す。
// Deprecate the memory that came in by replacement (that content is not remembered again) and make the older memory it replaced active again; revision is the new memory's.
// A failure carries its HTTP status, so the screen can reload the list on a 409 (the replacement changed elsewhere first).
export async function revertContextFactReplacement(factId: number, revision: number): Promise<ContextFactRevertResult> {
  const response = await resilientFetch(`/api/context-facts/${factId}/revert-replacement`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ revision }),
  });
  if (!response.ok) await throwContextResponseError(response, "記憶を元に戻せませんでした");
  const payload = (await response.json().catch(() => ({}))) as Partial<ContextFactRevertResult>;
  if (!payload.fact || !payload.restored_fact) {
    throw createContextApiError("記憶を元に戻せませんでした。", response.status);
  }
  return payload as ContextFactRevertResult;
}

// 記憶 1 件を、有効・無効化済みのどちらでも完全に削除する。無効化と違い、文面と出典も消える。
// Delete one memory for good, active or deprecated; unlike deprecating, its wording and sources are erased too.
export async function deleteContextFact(factId: number, revision: number): Promise<void> {
  await memoFetchJsonOrThrow(
    `/api/context-facts/${factId}?${new URLSearchParams({ revision: String(revision) }).toString()}`,
    { method: "DELETE", credentials: "same-origin" },
    { defaultMessage: "記憶を削除できませんでした。" },
  );
}

// 自分の記憶・出典・候補をすべて削除し、消した記憶の件数を返す。誤操作を防ぐため確認の値を付ける。設定（自動で記憶する・回答に使う）は変わらない。
// Delete all of the owner's memories, sources and candidates and return how many memories were deleted; the confirmation value guards against accidents. The settings (auto-saving, use in answers) are unchanged.
export async function deleteAllContextFacts(): Promise<number> {
  const { payload } = await memoFetchJsonOrThrow<{ deleted_count?: unknown; error?: string }>(
    `/api/context-facts?${new URLSearchParams({ confirm: DELETE_ALL_CONFIRMATION }).toString()}`,
    { method: "DELETE", credentials: "same-origin" },
    { defaultMessage: "記憶を削除できませんでした。" },
  );
  return typeof payload.deleted_count === "number" ? payload.deleted_count : 0;
}

// 「enabled」だけを持つ記憶の設定を読む。未ログイン（401）は無効として返す。
// Read a memory setting that holds only "enabled"; a signed-out session (401) counts as off.
async function loadEnabledSetting(path: string, failureMessage: string): Promise<{ enabled: boolean }> {
  const res = await resilientFetch(path, { credentials: "same-origin" });
  const data = (await res.json().catch(() => ({}))) as { enabled?: unknown; error?: string };
  if (res.status === 401) return { enabled: false };
  if (!res.ok) {
    throw new Error(data.error || `${failureMessage} (${res.status})`);
  }
  return { enabled: data.enabled === true };
}

// 「enabled」だけを持つ記憶の設定を書き、保存された値を返す。
// Write a memory setting that holds only "enabled" and return the stored value.
async function updateEnabledSetting(
  path: string,
  enabled: boolean,
  defaultMessage: string,
): Promise<{ enabled: boolean }> {
  const { payload } = await memoFetchJsonOrThrow<{ enabled?: unknown; error?: string }>(
    path,
    {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
    { defaultMessage },
  );
  return { enabled: payload.enabled === true };
}

// 会話からの記憶の自動保存の設定（初期値は有効）を取得する。
// Load the setting for automatic memory saving from chats (on by default).
export async function loadContextExtractionSettings(): Promise<ContextExtractionSettings> {
  return loadEnabledSetting("/api/context-facts/extraction-settings", "自動抽出設定の取得に失敗しました");
}

// 会話からの記憶の自動保存を明示的に有効化・無効化する。
// Explicitly enable or disable automatic memory saving from chats.
export async function updateContextExtractionSettings(
  input: ContextExtractionSettingsUpdateInput,
): Promise<ContextExtractionSettings> {
  return updateEnabledSetting(
    "/api/context-facts/extraction-settings",
    input.enabled,
    "自動抽出設定を更新できませんでした。",
  );
}

// 保存した記憶をチャットの回答に使う設定（初期値は有効）を取得する。保存の設定とは別。
// Load the setting for using saved memory in chat answers (on by default); separate from the saving setting.
export async function loadContextMemoryUseSettings(): Promise<ContextMemoryUseSettings> {
  return loadEnabledSetting("/api/context-facts/memory-use-settings", "記憶の利用設定の取得に失敗しました");
}

// 保存した記憶をチャットの回答に使うかを、明示的に切り替える。
// Explicitly switch whether saved memory is used in chat answers.
export async function updateContextMemoryUseSettings(
  input: ContextMemoryUseSettingsUpdateInput,
): Promise<ContextMemoryUseSettings> {
  return updateEnabledSetting(
    "/api/context-facts/memory-use-settings",
    input.enabled,
    "記憶の利用設定を更新できませんでした。",
  );
}

// 記憶の全事実をポータブルなJSONまたはMarkdownとして取得する。
// Fetch every Memory fact as a portable JSON or Markdown attachment.
export async function exportContextVault(
  format: ContextVaultExportFormat,
): Promise<ContextVaultExportResult> {
  const response = await resilientFetch(
    `/api/context-facts/export?${new URLSearchParams({ format }).toString()}`,
    { credentials: "same-origin" },
  );
  if (!response.ok) {
    await throwContextResponseError(response, "記憶を書き出せませんでした");
  }
  return {
    blob: await response.blob(),
    filename:
      parseAttachmentFilename(response.headers.get("Content-Disposition")) ??
      `chat-core-context.${format === "json" ? "json" : "md"}`,
  };
}

// インポート内容を保存せず検証し、件数・重複・警告・サンプルを返す。
// Validate an import without saving and return counts, duplicates, warnings, and samples.
export async function previewContextVaultImport(
  input: ContextVaultImportPreviewInput,
): Promise<ContextVaultImportPreview> {
  const { payload } = await memoFetchJsonOrThrow<
    Omit<ContextVaultImportPreview, "sample_facts" | "warnings"> &
      Partial<Pick<ContextVaultImportPreview, "sample_facts" | "warnings">>
  >(
    "/api/context-facts/import/preview",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "インポート内容を確認できませんでした。" },
  );
  return {
    ...payload,
    sample_facts: Array.isArray(payload.sample_facts) ? payload.sample_facts : [],
    warnings: Array.isArray(payload.warnings) ? payload.warnings : [],
  };
}

// preview_tokenで確認済みの同一内容だけを明示的に取り込む。
// Import only the same payload explicitly confirmed through its preview token.
export async function confirmContextVaultImport(
  input: ContextVaultImportConfirmInput,
): Promise<ContextVaultImportResult> {
  const { payload } = await memoFetchJsonOrThrow<ContextVaultImportResult>(
    "/api/context-facts/import",
    {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    { defaultMessage: "記憶をインポートできませんでした。" },
  );
  return payload;
}
