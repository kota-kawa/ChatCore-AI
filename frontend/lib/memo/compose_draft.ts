import { STORAGE_KEYS } from "../../scripts/core/constants";
import { parseJsonText } from "../../scripts/core/runtime_validation";
import { MEMO_COLOR_OPTIONS } from "./constants";
import type { MemoComposeFormState } from "./types";

// ---------------------------------------------------------------------------
// Memo composer: draft that survives a reload or a back navigation
// ---------------------------------------------------------------------------

// 保存前のメモを端末に控える。コレクションは復元時に消えている可能性があるので持たない。
// 控えには持ち主の利用者 id を付け、同じ利用者にだけ復元する。メモ画面はログアウトを
// 経由しないアカウント切り替えでも開けるため、一括破棄（lib/chat_page/storage.ts）だけでは
// 前の利用者の書きかけが次の利用者に見えてしまう。
// Keeps the unsaved memo on the device. The collection is left out because it may no longer
// exist when the draft is restored. The draft carries its owner's user id and is restored only
// for that user: the memo page can be opened after an account switch that skips logout, so the
// bulk clear in lib/chat_page/storage.ts alone would show one user's draft to the next.
export type MemoComposeDraft = Pick<MemoComposeFormState, "title" | "ai_response" | "background_color">;

const KNOWN_COLORS = new Set<string>(MEMO_COLOR_OPTIONS.map((option) => option.value).filter(Boolean));

export function readMemoComposeDraft(ownerId: string): MemoComposeDraft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.memoComposeDraft);
    if (!raw) return null;
    const parsed = parseJsonText(raw) as Partial<Record<keyof MemoComposeDraft | "owner", unknown>> | null;
    if (!parsed || typeof parsed !== "object" || parsed.owner !== ownerId) {
      localStorage.removeItem(STORAGE_KEYS.memoComposeDraft);
      return null;
    }
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

export function writeMemoComposeDraft(ownerId: string, draft: MemoComposeDraft): void {
  try {
    if (!draft.title.trim() && !draft.ai_response.trim() && !draft.background_color) {
      localStorage.removeItem(STORAGE_KEYS.memoComposeDraft);
      return;
    }
    localStorage.setItem(STORAGE_KEYS.memoComposeDraft, JSON.stringify({
      owner: ownerId,
      title: draft.title,
      ai_response: draft.ai_response,
      background_color: draft.background_color,
    }));
  } catch {
    // ignore localStorage failures
  }
}
