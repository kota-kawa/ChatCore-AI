import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { FlashAction, FlashState } from "../../lib/memo/types";

// 通常の通知は 4 秒で消す。「元に戻す」付きは、読んで手を伸ばす時間を見て長めにする
// Plain notices hide after 4s; one carrying an undo stays longer so there is time to read it and reach for it
const FLASH_DURATION_MS = 4000;
const FLASH_ACTION_DURATION_MS = 6000;

// メモ画面のフラッシュメッセージ（成功・エラーの一時表示）と ?saved=1 の処理
// Flash messages for the memo page (transient success/error) plus the ?saved=1 query handling
export function useMemoPageFlash() {
  const { t } = useTranslation();
  const router = useRouter();

  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 表示中の通知に付いた操作。押された時点で取り出して空にし、連打や再描画前の二重押しで 2 回走らせない
  // The action of the notice on screen. It is taken and cleared the moment it is pressed so a double
  // tap, or a second press before the re-render, cannot run it twice
  const flashActionRef = useRef<FlashAction | null>(null);

  // アンマウント時に表示タイマーを破棄する
  // Drop the pending hide timer on unmount
  useEffect(() => {
    return () => {
      if (flashTimerRef.current) {
        clearTimeout(flashTimerRef.current);
        flashTimerRef.current = null;
      }
    };
  }, []);

  // URLクエリパラメータから保存成功などのフラッシュメッセージを表示する副作用
  // Effect to show flash messages like save success from URL query parameters
  useEffect(() => {
    if (!router.isReady) return;
    if (router.query.saved !== "1") return;
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashState({ type: "success", text: t("memo.memoSaved") });
    flashTimerRef.current = setTimeout(() => {
      setFlashState(null);
      flashTimerRef.current = null;
    }, FLASH_DURATION_MS);
    const nextQuery = { ...router.query };
    delete nextQuery.saved;
    void router.replace({ pathname: router.pathname, query: nextQuery }, undefined, { shallow: true });
  }, [router, router.isReady, router.pathname, router.query]);

  // 表示中の通知を消し、タイマーと操作も破棄する
  // Hide the notice on screen and drop its timer and action
  const dismissFlash = useCallback(() => {
    if (flashTimerRef.current) {
      clearTimeout(flashTimerRef.current);
      flashTimerRef.current = null;
    }
    flashActionRef.current = null;
    setFlashState(null);
  }, []);

  // 新しい通知は前の通知（とその「元に戻す」）を置き換える。取り消しは直前の操作にだけ効かせる
  // A new notice replaces the previous one together with its undo, so an undo only ever applies to the latest action
  const showFlash = useCallback((type: "success" | "error", text: string, action?: FlashAction) => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    flashActionRef.current = action ?? null;
    setFlashState(action ? { type, text, action } : { type, text });
    flashTimerRef.current = setTimeout(() => {
      flashActionRef.current = null;
      setFlashState(null);
      flashTimerRef.current = null;
    }, action ? FLASH_ACTION_DURATION_MS : FLASH_DURATION_MS);
  }, []);

  // 通知の操作ボタンが押されたとき。先に通知を消してから操作を走らせる（結果は操作側が新しい通知で知らせる）
  // The notice's action button was pressed: hide the notice first, then run the action (which reports its own result)
  const runFlashAction = useCallback(() => {
    const action = flashActionRef.current;
    if (!action) return;
    dismissFlash();
    void action.onAction();
  }, [dismissFlash]);

  return { flashState, setFlashState, showFlash, runFlashAction };
}
