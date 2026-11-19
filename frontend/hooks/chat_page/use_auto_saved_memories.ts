// チャットで自動保存された記憶の通知（「記憶しました」）の取得と取り消しを持つ hook。ログイン中の通常ルームを開いたときと、
// 回答が確定した後の数秒・十数秒後（抽出は回答の外で LLM を呼ぶので完了直後は空）にだけ取りにいき、常時ポーリングはしない。
// 取得の失敗は黙って何も出さず、回答の表示や操作には影響させない。呼び出し元は components/chat_page/chat_main_section.tsx。
// Hook owning the fetch and undo of the chat's "remembered" notices for auto-saved memory. It loads only when a
// signed-in normal room opens and a few / a dozen seconds after an answer settles (extraction calls an LLM off
// the response path, so right after the answer the list is empty); there is no continuous polling. A failed
// fetch shows nothing and never affects the answer or chat actions. Used by components/chat_page/chat_main_section.tsx.
import { useCallback, useEffect, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import { fetchAutoSavedMemories, type AutoSavedMemory } from "../../lib/chat_page/auto_saved_memory_api";
import {
  markAutoSavedMemoryUndone,
  mergeAutoSavedMemories,
  NO_AUTO_SAVED_MEMORIES,
  type AutoSavedMemoriesByMessage,
} from "../../lib/chat_page/auto_saved_memory_state";
import type { ChatRoomMode } from "../../lib/chat_page/types";
import { updateContextFact } from "../../lib/memo/context_api";
import { showToast } from "../../scripts/core/toast";

// 回答が確定してから取り直すまでの待ち時間（最大 2 回）。1 回目で間に合わなかった抽出を 2 回目で拾う。
// Delays between an answer settling and the re-fetches (at most two); the second catches slower extractions.
export const AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS = [5_000, 15_000] as const;

type UseAutoSavedMemoriesOptions = {
  roomId: string | null;
  roomMode: ChatRoomMode;
  loggedIn: boolean;
  isGenerating: boolean;
  // 最新の確定した回答のサーバー ID。これが取れて生成が終わった時点を「回答が確定した」とみなす。
  // Server id of the latest settled answer; once it is known and generation has ended, the answer counts as settled.
  lastAssistantServerId: number | null;
};

export function useAutoSavedMemories({
  roomId,
  roomMode,
  loggedIn,
  isGenerating,
  lastAssistantServerId,
}: UseAutoSavedMemoriesOptions) {
  const { t } = useTranslation();
  const [memoriesByMessageId, setMemoriesByMessageId] = useState<AutoSavedMemoriesByMessage>(NO_AUTO_SAVED_MEMORIES);
  // ゲストと一時チャットでは取得しない。 / Guests and temporary chats never fetch.
  const activeRoomId = loggedIn && roomMode === "normal" ? roomId : null;
  // 取得結果が古い部屋のものなら捨てるための、現在の部屋。 / The current room, so a result for a previous room is dropped.
  const activeRoomIdRef = useRef<string | null>(null);
  // サーバーが「自動抽出は無効」と返したら false。このあいだは回答後の取り直しをしない。
  // False once the server says auto-extraction is off; no re-fetch after answers while it is.
  const extractionEnabledRef = useRef(true);
  // 生成が走っていた（回答の確定待ち）か。部屋の作成が生成の途中で起きても取りこぼさないよう、現在の生成状態も ref に写す。
  // Whether a generation ran and its settling is awaited. The current generation state is mirrored too, so a room
  // created mid-generation does not lose the wait.
  const answerPendingRef = useRef(false);
  const isGeneratingRef = useRef(isGenerating);
  const timerIdsRef = useRef<number[]>([]);
  const undoInFlightRef = useRef<Set<number>>(new Set());

  const clearTimers = useCallback(() => {
    timerIdsRef.current.forEach((timerId) => window.clearTimeout(timerId));
    timerIdsRef.current = [];
  }, []);

  const load = useCallback(async (targetRoomId: string) => {
    try {
      const result = await fetchAutoSavedMemories(targetRoomId);
      if (!result || activeRoomIdRef.current !== targetRoomId) return;
      extractionEnabledRef.current = result.enabled;
      setMemoriesByMessageId((previous) => mergeAutoSavedMemories(previous, result.memories));
    } catch {
      // 通知が出ないだけで、チャットは止めない。
      // Only the notice is missed; the chat carries on.
    }
  }, []);

  useEffect(() => {
    isGeneratingRef.current = isGenerating;
  }, [isGenerating]);

  // 通常ルームを開いたとき、またはルーム・ログイン状態が変わったときに、状態を作り直して取得する。
  // When a normal room opens (or the room / sign-in state changes), reset the state and load.
  useEffect(() => {
    activeRoomIdRef.current = activeRoomId;
    answerPendingRef.current = isGeneratingRef.current;
    setMemoriesByMessageId(NO_AUTO_SAVED_MEMORIES);
    if (activeRoomId) void load(activeRoomId);
    return clearTimers;
  }, [activeRoomId, clearTimers, load]);

  // 回答が確定したら、抽出の完了を見込んで 2 回だけ取り直す。無効と分かっているセッションでは取り直さない。
  // Once an answer settles, re-fetch twice to catch the extraction. Skipped while extraction is known to be off.
  useEffect(() => {
    if (isGenerating) {
      answerPendingRef.current = true;
      return;
    }
    const targetRoomId = activeRoomIdRef.current;
    if (!answerPendingRef.current || lastAssistantServerId === null || !targetRoomId) return;
    answerPendingRef.current = false;
    if (!extractionEnabledRef.current) return;
    clearTimers();
    timerIdsRef.current = AUTO_SAVED_MEMORY_REFETCH_DELAYS_MS.map((delayMs) =>
      window.setTimeout(() => {
        if (extractionEnabledRef.current) void load(targetRoomId);
      }, delayMs),
    );
  }, [clearTimers, isGenerating, lastAssistantServerId, load]);

  // 取り消しは既存の記憶の更新 API（status を deprecated にする）。成功したら通知を「取り消しました」にする。
  // 失敗したら（記憶の画面で先に編集された場合の競合など）エラーを出し、最新の revision を取り直す。
  // Undo uses the existing memory update API (status becomes deprecated). On success the notice turns into
  // "undone"; on failure (e.g. a conflict because the memory was edited in the memory screen) an error is
  // shown and the latest revision is re-fetched.
  const undo = useCallback(
    async (memory: AutoSavedMemory) => {
      if (undoInFlightRef.current.has(memory.id)) return;
      undoInFlightRef.current.add(memory.id);
      try {
        await updateContextFact(memory.id, { revision: memory.revision, status: "deprecated" });
        setMemoriesByMessageId((previous) => markAutoSavedMemoryUndone(previous, memory));
      } catch {
        showToast(t("chat.memoryNotice.undoFailed"), { variant: "error" });
        const targetRoomId = activeRoomIdRef.current;
        if (targetRoomId) void load(targetRoomId);
      } finally {
        undoInFlightRef.current.delete(memory.id);
      }
    },
    [load, t],
  );

  return { memoriesByMessageId, undo };
}
