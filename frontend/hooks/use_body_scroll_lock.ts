import { useEffect } from "react";

import { acquireBodyScrollLock } from "../scripts/core/body_scroll_lock";

/**
 * ボディのスクロールをロックするカスタムフック
 * Custom hook to lock the body scroll
 */
export function useBodyScrollLock(isLocked: boolean) {
  useEffect(() => {
    // ロックされていない場合は何もしない
    // Do nothing if not locked
    if (!isLocked) return;
    
    // スクロールロックを取得し、クリーンアップ関数を返す
    // Acquire the scroll lock and return the cleanup function
    return acquireBodyScrollLock();
  }, [isLocked]);
}
