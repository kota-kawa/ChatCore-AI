import { STORAGE_KEYS } from "../../scripts/core/constants";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import { MEMO_COLOR_OPTIONS } from "./constants";
import type { MemoComposeFormState } from "./types";

// ---------------------------------------------------------------------------
// Memo composer: draft that survives a reload or a back navigation
// ---------------------------------------------------------------------------

// 保存前のメモを端末に控える。コレクションは復元時に消えている可能性があるので持たない。
// ログアウトやユーザー切り替え時は lib/chat_page/storage.ts の一括破棄がこのキーも消す。
// Keeps the unsaved memo on the device. The collection is left out because it may no longer
// exist when the draft is restored. Logout and user switches wipe this key through the bulk
// clear in lib/chat_page/storage.ts.
export type MemoComposeDraft = Pick<MemoComposeFormState, "title" | "ai_response" | "background_color">;

const KNOWN_COLORS = new Set<string>(MEMO_COLOR_OPTIONS.map((option) => option.value).filter(Boolean));

export function readMemoComposeDraft(): MemoComposeDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.memoComposeDraft);
    if (!raw) return null;
    const parsed = parseJsonText(raw) as Partial<Record<keyof MemoComposeDraft, unknown>> | null;
    if (!parsed || typeof parsed !== "object") return null;
    const title = typeof parsed.title === "string" ? parsed.title.slice(0, 255) : "";
    const aiResponse = typeof parsed.ai_response === "string" ? parsed.ai_response : "";
    const color = typeof parsed.background_color === "string" && KNOWN_COLORS.has(parsed.background_color)
      ? parsed.background_color
      : null;
    if (!title.trim() && !aiResponse.trim() && !color) return null;
    return { title, ai_response: aiResponse, background_color: color };
  } catch {
    return null;
  }
}

export function writeMemoComposeDraft(draft: MemoComposeDraft): void {
  try {
    if (!draft.title.trim() && !draft.ai_response.trim() && !draft.background_color) {
      localStorage.removeItem(STORAGE_KEYS.memoComposeDraft);
      return;
    }
    localStorage.setItem(STORAGE_KEYS.memoComposeDraft, JSON.stringify({
      title: draft.title,
      ai_response: draft.ai_response,
      background_color: draft.background_color,
    }));
  } catch {
    // ignore localStorage failures
  }
}
