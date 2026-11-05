// 共有コンテンツを取り込む操作の状態（待機中・成功・失敗）と二重実行の防止を提供するフック。
// Hooks providing the state (pending, success, error) and double-run guard for actions that import shared content.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

export type ImportActionState = "idle" | "pending" | "success" | "error";

export type ImportActionRunner = (task: () => Promise<void> | void) => Promise<boolean>;

export type UseImportActionStateResult = {
  state: ImportActionState;
  isPending: boolean;
  run: ImportActionRunner;
};

export type UseKeyedImportActionStateResult = {
  states: ReadonlyMap<string, ImportActionState>;
  pendingIds: Set<string>;
  isPending: (key: string) => boolean;
  run: (key: string, task: () => Promise<void> | void) => Promise<boolean>;
};

// 成功・失敗の表示を元の状態（idle）へ戻すまでの時間（ミリ秒）。
// Time (ms) before the success/error feedback returns to idle.
const IMPORT_ACTION_FEEDBACK_RESET_MS = 1800;

/**
 * 共有コンテンツを取り込む操作の状態と再入防止（実行中は再実行しない）。
 * 失敗は再スローするので、各画面が自分のローカライズ済み文言で表示できる。
 *
 * Shared state and re-entry guard for actions that import shared content.
 * Errors are re-thrown so each surface can keep its existing localized copy.
 */
export function useImportActionState(): UseImportActionStateResult {
  const [state, setState] = useState<ImportActionState>("idle");
  const stateRef = useRef<ImportActionState>("idle");
  const resetTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearResetTimer = useCallback(() => {
    if (resetTimerRef.current) {
      clearTimeout(resetTimerRef.current);
      resetTimerRef.current = null;
    }
  }, []);

  const scheduleReset = useCallback(() => {
    clearResetTimer();
    resetTimerRef.current = setTimeout(() => {
      resetTimerRef.current = null;
      stateRef.current = "idle";
      setState("idle");
    }, IMPORT_ACTION_FEEDBACK_RESET_MS);
  }, [clearResetTimer]);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) clearTimeout(resetTimerRef.current);
    };
  }, []);

  // 待機中に再度呼ばれたら何もしない。stateRef を併用するのは、再レンダー前の連続呼び出しでも state の古い値で素通りさせないため。失敗は再スローして、各画面が自分の文言で表示できるようにする。
  // Does nothing when called again while pending. stateRef is used so a second call before the next render cannot slip past on a stale state value. Errors are re-thrown so each screen can show its own message.
  const run = useCallback<ImportActionRunner>(async (task) => {
    if (stateRef.current === "pending") return false;

    clearResetTimer();
    stateRef.current = "pending";
    setState("pending");
    try {
      await task();
      stateRef.current = "success";
      setState("success");
      scheduleReset();
      return true;
    } catch (error) {
      stateRef.current = "error";
      setState("error");
      scheduleReset();
      throw error;
    }
  }, [clearResetTimer, scheduleReset]);

  return {
    state,
    isPending: state === "pending",
    run,
  };
}

/**
 * カード一覧向けのキー付き版。共有アイテムごとに別々の再入防止と状態を持つ。
 *
 * Keyed variant for lists of cards where each shared item needs its own guard.
 */
export function useKeyedImportActionState(): UseKeyedImportActionStateResult {
  const [states, setStates] = useState<Map<string, ImportActionState>>(new Map());
  const statesRef = useRef<Map<string, ImportActionState>>(new Map());
  const resetTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const updateState = useCallback((key: string, nextState: ImportActionState) => {
    statesRef.current.set(key, nextState);
    setStates(new Map(statesRef.current));
  }, []);

  const clearResetTimer = useCallback((key: string) => {
    const existingTimer = resetTimersRef.current.get(key);
    if (!existingTimer) return;
    clearTimeout(existingTimer);
    resetTimersRef.current.delete(key);
  }, []);

  const scheduleReset = useCallback((key: string) => {
    clearResetTimer(key);
    const timer = setTimeout(() => {
      resetTimersRef.current.delete(key);
      updateState(key, "idle");
    }, IMPORT_ACTION_FEEDBACK_RESET_MS);
    resetTimersRef.current.set(key, timer);
  }, [clearResetTimer, updateState]);

  useEffect(() => {
    return () => {
      resetTimersRef.current.forEach((timer) => clearTimeout(timer));
      resetTimersRef.current.clear();
    };
  }, []);

  const isPending = useCallback((key: string) => statesRef.current.get(key) === "pending", []);
  const run = useCallback(
    async (key: string, task: () => Promise<void> | void) => {
      if (isPending(key)) return false;
      clearResetTimer(key);
      updateState(key, "pending");
      try {
        await task();
        updateState(key, "success");
        scheduleReset(key);
        return true;
      } catch (error) {
        updateState(key, "error");
        scheduleReset(key);
        throw error;
      }
    },
    [clearResetTimer, isPending, scheduleReset, updateState],
  );

  const pendingIds = useMemo(() => {
    const pending = new Set<string>();
    states.forEach((state, key) => {
      if (state === "pending") pending.add(key);
    });
    return pending;
  }, [states]);

  return { states, pendingIds, isPending, run };
}
