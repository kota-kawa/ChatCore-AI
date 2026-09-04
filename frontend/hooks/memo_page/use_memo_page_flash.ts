import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";

import { useTranslation } from "../../contexts/locale_context";
import type { FlashState } from "../../lib/memo/types";

// メモ画面のフラッシュメッセージ（成功・エラーの一時表示）と ?saved=1 の処理
// Flash messages for the memo page (transient success/error) plus the ?saved=1 query handling
export function useMemoPageFlash() {
  const { t } = useTranslation();
  const router = useRouter();

  const [flashState, setFlashState] = useState<FlashState | null>(null);
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
    }, 4000);
    const nextQuery = { ...router.query };
    delete nextQuery.saved;
    void router.replace({ pathname: router.pathname, query: nextQuery }, undefined, { shallow: true });
  }, [router, router.isReady, router.pathname, router.query]);

  const showFlash = useCallback((type: "success" | "error", text: string) => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashState({ type, text });
    flashTimerRef.current = setTimeout(() => {
      setFlashState(null);
      flashTimerRef.current = null;
    }, 4000);
  }, []);

  return { flashState, setFlashState, showFlash };
}
