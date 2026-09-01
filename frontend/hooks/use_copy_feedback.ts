// コピーボタンの「押した瞬間だけアイコンをチェックマークに差し替える」挙動を一元化するフック。
// A hook that centralises the copy-button behaviour: swap the icon to a check mark for a
// few seconds right after a copy, then restore it.
//
// 画面ごとにバラバラだったコピーボタンの見た目とタイミングを揃えるための土台。
// アイコンだけのボタン（ラベル文字なし）と、成功時のチェックマーク表示時間をここで統一する。
// 実際のボタン描画は components/ui/copy_button.tsx（CopyButton）が担う。
// This is the single source of truth that keeps every copy button consistent: icon only
// (no text label) and the same "show a check mark" duration on success.
// The button markup lives in components/ui/copy_button.tsx (CopyButton).

import { useCallback, useEffect, useRef, useState } from "react";

import { COPY_FEEDBACK_RESET_MS } from "../lib/copy_feedback";
import { copyTextToClipboard } from "../scripts/core/clipboard";

// React 非依存の共有定数を、これまで通りこのフックからも参照できるよう再エクスポートする。
// Re-export the React-free shared constant so callers can keep importing it from this hook.
export { COPY_FEEDBACK_RESET_MS };

// コピーボタンの視覚状態。idle=通常アイコン / copied=チェックマーク / error=失敗アイコン。
// Visual state of a copy button: idle (normal icon) / copied (check mark) / error (failure icon).
export type CopyFeedbackState = "idle" | "copied" | "error";

export type UseCopyFeedbackResult = {
  state: CopyFeedbackState;
  copied: boolean;
  failed: boolean;
  // テキストを直接クリップボードへコピーし、結果に応じてアイコンを一定時間切り替える。
  // Copy text to the clipboard directly and flip the icon for a while based on the outcome.
  copy: (source: string | (() => string)) => Promise<boolean>;
  // 任意のコピー処理（共有リンクのコピー＋ステータス表示など）を実行し、結果でアイコンを切り替える。
  // task は成否を boolean で返す（拒否 or false で失敗扱い）。
  // Run an arbitrary copy routine (e.g. copy a share link + show a status) and flip the icon from its result.
  run: (task: () => Promise<boolean> | boolean) => Promise<boolean>;
  // 外部で完結したコピー処理の成否だけを受け取ってアイコンを切り替える低レベル API。
  // Low-level API: flip the icon from the success/failure of a copy that completed elsewhere.
  markResult: (succeeded: boolean) => void;
};

// resetMs: チェックマーク／失敗アイコンを表示してから通常アイコンへ戻すまでの時間。
// resetMs: how long the check mark / failure icon stays before the normal icon returns.
export function useCopyFeedback(resetMs: number = COPY_FEEDBACK_RESET_MS): UseCopyFeedbackResult {
  const [state, setState] = useState<CopyFeedbackState>("idle");
  const timerRef = useRef<number | null>(null);
  const inFlightRef = useRef(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // アンマウント時にタイマーを片付けて、消えたボタンへの setState を防ぐ。
  // Clean the timer up on unmount so we never setState on a button that is gone.
  useEffect(() => clearTimer, [clearTimer]);

  const markResult = useCallback(
    (succeeded: boolean) => {
      clearTimer();
      setState(succeeded ? "copied" : "error");
      timerRef.current = window.setTimeout(() => {
        setState("idle");
        inFlightRef.current = false;
        timerRef.current = null;
      }, resetMs);
    },
    [clearTimer, resetMs],
  );

  const run = useCallback(
    async (task: () => Promise<boolean> | boolean) => {
      // フィードバック表示中の連打で同じコピーが二重に走らないようにする。
      // Guard against a double click during the feedback window firing the same copy twice.
      if (inFlightRef.current) return false;
      inFlightRef.current = true;
      try {
        const succeeded = (await task()) !== false;
        markResult(succeeded);
        return succeeded;
      } catch {
        markResult(false);
        return false;
      }
    },
    [markResult],
  );

  const copy = useCallback(
    (source: string | (() => string)) =>
      run(async () => {
        await copyTextToClipboard(typeof source === "function" ? source() : source);
        return true;
      }),
    [run],
  );

  return {
    state,
    copied: state === "copied",
    failed: state === "error",
    copy,
    run,
    markResult,
  };
}
